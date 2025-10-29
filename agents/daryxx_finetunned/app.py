from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

SYSTEM_PROMPT_DEFAULT = (
    "You are a web automation planner. Given a target URL and a natural-language task, "
    "return only a JSON array describing the minimal sequence of actions to complete the task. "
    "Use the schema: [{\\\"type\\\": \\\"navigate|click|input|type|search|extract|submit|open_tab|close_tab|wait|scroll|screenshot|other\\\", "
    "\\\"selector\\\": string|null, \\\"value\\\": string|null}]. Do not include timestamps or explanations; "
    "respond with the JSON array only."
)


# ---------------------------- Data models ----------------------------
class TaskPayload(BaseModel):
    id: Optional[str] = None
    url: str
    prompt: str
    relevant_data: Optional[Dict[str, Any]] = None


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v is not None else default


def _parse_actions_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract and parse the first JSON array from the model output."""
    # Fast-path: exact JSON
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            return json.loads(text)
        except Exception:
            pass

    # Fallback: find the first balanced JSON array
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    snippet = match.group(0)
    try:
        return json.loads(snippet)
    except Exception:
        return []


def _selector_from_string(selector: Optional[str]) -> Optional[Dict[str, Any]]:
    if not selector:
        return None
    return {
        "type": "attributeValueSelector",
        "attribute": "custom",
        "value": selector,
        "case_sensitive": False,
    }


def _normalize_action(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map LLM action dict into IWA BaseAction.create_action()-friendly dict."""
    if not isinstance(item, dict):
        return None

    t = str(item.get("type", "")).strip().lower()
    if not t:
        return None

    # Map aliases to supported action ids
    alias = {
        "input": "type",
        "search": "type",  # map to typing; validator may follow with SubmitAction via tests
        "open_tab": "sendkeysiwa",
        "close_tab": "sendkeysiwa",
        "other": "idle",
        "extract": "undefined",
    }
    mapped_t = alias.get(t, t)

    out: Dict[str, Any] = {"type": mapped_t}

    # Map navigate value → url
    if mapped_t == "navigate":
        url = item.get("url") or item.get("value")
        if url:
            out["url"] = str(url)

    # map 'selector' string → Selector model dict
    raw_selector = item.get("selector")
    if isinstance(raw_selector, dict):
        out["selector"] = raw_selector
    elif isinstance(raw_selector, str):
        out["selector"] = _selector_from_string(raw_selector)

    # Key mapping for open/close tab → SendKeysIWAAction
    if t == "open_tab":
        out["keys"] = os.getenv("OPEN_TAB_KEYS", "Control+T")
    if t == "close_tab":
        out["keys"] = os.getenv("CLOSE_TAB_KEYS", "Control+W")

    # Common properties
    for key in ("value", "text", "x", "y", "go_back", "go_forward", "time_seconds", "timeout_seconds", "up", "down", "left", "right"):
        if key in item and item[key] is not None:
            out[key] = item[key]

    return out


def _build_messages(url: str, prompt: str, system_prompt: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"URL: {url}\nTask: {prompt}"},
    ]


def _call_openai(messages: List[Dict[str, str]], *, model: str, temperature: float, max_tokens: int) -> str:
    # New SDK (>=1.0)
    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=_get_env("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception:
        pass

    # Legacy SDK fallback
    try:
        import openai  # type: ignore

        openai.api_key = _get_env("OPENAI_API_KEY")
        resp = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"OpenAI call failed: {exc}")


app = FastAPI(title="Daryxx Finetuned Agent", version="0.1.0")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "agent": "daryxx_finetunned"}


@app.post("/solve_task")
def solve_task(task: TaskPayload) -> Dict[str, Any]:
    model = _get_env("OPENAI_MODEL")
    if not model:
        raise HTTPException(status_code=500, detail="OPENAI_MODEL env var not set")
    api_key = _get_env("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY env var not set")

    temperature = float(_get_env("OPENAI_TEMPERATURE", "0.0") or 0.0)
    max_tokens = int(_get_env("OPENAI_MAX_TOKENS", "1024") or 1024)
    system_prompt = _get_env("SYSTEM_PROMPT", SYSTEM_PROMPT_DEFAULT) or SYSTEM_PROMPT_DEFAULT

    # Build prompt and call model
    messages = _build_messages(task.url, task.prompt, system_prompt)
    content = _call_openai(messages, model=model, temperature=temperature, max_tokens=max_tokens)

    # Parse actions
    raw_actions = _parse_actions_from_text(content)
    norm_actions = []
    for it in raw_actions:
        norm = _normalize_action(it)
        if norm:
            norm_actions.append(norm)

    return {
        "task_id": task.id or "unknown",
        "web_agent_id": os.getenv("WEB_AGENT_ID", "daryxx_finetunned"),
        "actions": norm_actions,
        "success": bool(norm_actions),
    }


if __name__ == "__main__":
    import uvicorn

    host = _get_env("AGENT_HOST", "0.0.0.0") or "0.0.0.0"
    port = int(_get_env("AGENT_PORT", "8080") or 8080)
    uvicorn.run(app, host=host, port=port)
