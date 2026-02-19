import asyncio
import json
import logging
import os
import random
import time
from typing import Optional
from logging.handlers import RotatingFileHandler

import httpx
from fastapi import FastAPI, Request, HTTPException, Response
import secrets

from models import LLMUsage, DEFAULT_PROVIDER_CONFIGS
from config import (
    COST_LIMIT_PER_TASK,
    OPENAI_API_KEY,
    CHUTES_API_KEY,
    SANDBOX_GATEWAY_ADMIN_TOKEN,
    GATEWAY_ALLOWED_PROVIDERS,
    OPENAI_ALLOWED_MODELS,
    CHUTES_ALLOWED_MODELS,
    OPENAI_ALLOWED_PATHS,
    CHUTES_ALLOWED_PATHS,
    GATEWAY_STRICT_PRICING,
    CHUTES_PRICING_TTL_SECONDS,
    CHUTES_PRICING_TIMEOUT_SECONDS,
    GATEWAY_FORCE_JSON_RESPONSE_FORMAT,
    GATEWAY_OPENAI_MAX_CONCURRENCY,
    GATEWAY_CHUTES_MAX_CONCURRENCY,
    GATEWAY_UPSTREAM_MAX_RETRIES,
    GATEWAY_UPSTREAM_RETRY_BASE_DELAY_S,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(
            "/app/logs/gateway.log",
            maxBytes=int(os.getenv("SANDBOX_GATEWAY_LOG_MAX_BYTES", str(10 * 1024 * 1024))),
            backupCount=int(os.getenv("SANDBOX_GATEWAY_LOG_BACKUP_COUNT", "3")),
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class LLMGateway:
    """Simplified gateway for single agent evaluation"""

    def __init__(self):
        self.providers = DEFAULT_PROVIDER_CONFIGS.copy()
        unknown = sorted(set(GATEWAY_ALLOWED_PROVIDERS) - set(self.providers.keys()))
        if unknown:
            logger.warning(f"Ignoring unknown providers in GATEWAY_ALLOWED_PROVIDERS: {unknown}")
        self.providers = {name: cfg for name, cfg in self.providers.items() if name in GATEWAY_ALLOWED_PROVIDERS}
        if not self.providers:
            raise RuntimeError("No gateway providers enabled")
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self.allowed_task_ids = set()
        self.usage_per_task: dict[str, LLMUsage] = {}
        self._chutes_pricing_lock = asyncio.Lock()
        self._chutes_pricing_last_refresh = 0.0
        # Best-effort upstream concurrency limits to reduce 429s.
        self._provider_semaphores = {
            "openai": asyncio.Semaphore(max(1, int(GATEWAY_OPENAI_MAX_CONCURRENCY))),
            "chutes": asyncio.Semaphore(max(1, int(GATEWAY_CHUTES_MAX_CONCURRENCY))),
        }

    def _maybe_force_json_response_format(self, provider: str, suffix: str, body: dict) -> tuple[dict, bool]:
        """
        Force response_format=json_object when talking to OpenAI-compatible chat endpoints.

        This is a practical hardening so miners can reliably parse model output. If the
        upstream rejects it, we will retry without response_format.
        """
        if not GATEWAY_FORCE_JSON_RESPONSE_FORMAT:
            return body, False
        if provider not in {"openai", "chutes"}:
            return body, False
        # Only for chat completions. Responses API is left untouched.
        if suffix != "/v1/chat/completions":
            return body, False
        if not isinstance(body, dict):
            return body, False
        if isinstance(body.get("response_format"), dict):
            return body, False
        b2 = dict(body)
        b2["response_format"] = {"type": "json_object"}
        return b2, True

    def detect_provider(self, path: str) -> Optional[str]:
        """Detect LLM provider from request."""
        for provider in self.providers.keys():
            # Require an exact provider match or a slash-delimited prefix.
            # This prevents SSRF-style host override via paths like "openai@evil.com/...".
            if path == provider or path.startswith(f"{provider}/"):
                return provider

        logger.error("Unsupported provider.")
        return None

    def detect_task_id(self, request: Request) -> Optional[str]:
        """Detect task ID from request for usage tracking."""
        task_id = request.headers.get("iwa-task-id", "")
        if task_id in self.allowed_task_ids:
            return task_id

        logger.error("Missing or invalid task ID for usage tracking.")
        logger.error(f"Task ID: {task_id}")
        return None

    def get_usage_for_task(self, task_id: str) -> LLMUsage:
        return self.usage_per_task.get(task_id, LLMUsage())

    def _is_allowed_path(self, provider: str, suffix: str) -> bool:
        allowed = OPENAI_ALLOWED_PATHS if provider == "openai" else CHUTES_ALLOWED_PATHS if provider == "chutes" else set()
        if not allowed:
            return True
        for p in allowed:
            if suffix == p or suffix.startswith(p + "/"):
                return True
        return False

    def _is_allowed_model(self, provider: str, model: str) -> bool:
        allowed = OPENAI_ALLOWED_MODELS if provider == "openai" else CHUTES_ALLOWED_MODELS if provider == "chutes" else set()
        if not allowed:
            return True
        return model in allowed

    def _resolve_pricing_model(self, provider: str, model: str) -> str:
        """
        Resolve a request/response model id to a priced model key.

        OpenAI (and some OpenAI-compatible providers) may return or accept versioned
        model ids like "gpt-4o-2024-08-06". We price these by longest-prefix match
        against our known pricing keys (e.g. "gpt-4o").
        """
        provider_config = self.providers.get(provider)
        if not provider_config or not model:
            return model
        if model in provider_config.pricing:
            return model
        best_key = ""
        for key in provider_config.pricing.keys():
            if model.startswith(key) and len(key) > len(best_key):
                best_key = key
        return best_key or model

    async def refresh_chutes_pricing(self) -> bool:
        """
        Fetch Chutes model pricing from the public OpenAI-compatible models endpoint.

        Expected schema (subset):
          GET https://llm.chutes.ai/v1/models
          {
            "data": [
              {"id": "...", "price": {"input": {"usd": 0.1}, "output": {"usd": 0.3}, "input_cache_read": {"usd": 0.05}}},
              {"id": "...", "pricing": {"prompt": 0.1, "completion": 0.3, "input_cache_read": 0.05}}
            ]
          }
        """
        provider_config = self.providers.get("chutes")
        if not provider_config:
            return False

        url = str(httpx.URL(provider_config.base_url).copy_with(path="/v1/models"))
        headers = {"Accept": "application/json"}
        if CHUTES_API_KEY:
            headers["Authorization"] = f"Bearer {CHUTES_API_KEY}"

        try:
            resp = await self.http_client.get(url, headers=headers, timeout=CHUTES_PRICING_TIMEOUT_SECONDS)
            resp.raise_for_status()
            payload = resp.json() or {}
            models = payload.get("data") or []
        except Exception as e:
            logger.warning(f"Failed to fetch Chutes pricing from {url}: {e}")
            return False

        pricing_map: dict[str, dict[str, float]] = {}
        for m in models:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or "")
            if not mid:
                continue

            entry: dict[str, float] = {}

            # Preferred: structured "price" with USD.
            price = m.get("price")
            if isinstance(price, dict):
                try:
                    in_usd = (price.get("input") or {}).get("usd")
                    out_usd = (price.get("output") or {}).get("usd")
                    cache_usd = (price.get("input_cache_read") or {}).get("usd")
                    if in_usd is not None:
                        entry["input"] = float(in_usd)
                    if out_usd is not None:
                        entry["output"] = float(out_usd)
                    if cache_usd is not None:
                        entry["input_cache_read"] = float(cache_usd)
                except Exception:
                    entry = {}

            # Fallback: flat "pricing" (prompt/completion) in USD per 1M tokens.
            if not entry:
                pricing = m.get("pricing")
                if isinstance(pricing, dict):
                    try:
                        if pricing.get("input") is not None:
                            entry["input"] = float(pricing["input"])
                        if pricing.get("output") is not None:
                            entry["output"] = float(pricing["output"])
                        if pricing.get("prompt") is not None:
                            entry["input"] = float(pricing["prompt"])
                        if pricing.get("completion") is not None:
                            entry["output"] = float(pricing["completion"])
                        if pricing.get("input_cache_read") is not None:
                            entry["input_cache_read"] = float(pricing["input_cache_read"])
                    except Exception:
                        entry = {}

            if "input" in entry and "output" in entry:
                pricing_map[mid] = entry

        if pricing_map:
            provider_config.pricing = pricing_map
            self._chutes_pricing_last_refresh = time.time()
            logger.info(f"Loaded Chutes pricing for {len(pricing_map)} models")
            return True

        logger.warning("Chutes /v1/models returned no models with usable pricing")
        return False

    async def ensure_provider_pricing(self, provider: str) -> None:
        if provider != "chutes":
            return

        now = time.time()
        if self._chutes_pricing_last_refresh and (now - self._chutes_pricing_last_refresh) < CHUTES_PRICING_TTL_SECONDS:
            return

        async with self._chutes_pricing_lock:
            now = time.time()
            if self._chutes_pricing_last_refresh and (now - self._chutes_pricing_last_refresh) < CHUTES_PRICING_TTL_SECONDS:
                return
            # Refresh best-effort.
            await self.refresh_chutes_pricing()

    def update_usage_for_task(self, provider: str, task_id: str, response_data: dict) -> tuple[int, float, str]:
        """Update token usage for a specific task and return (tokens, cost, model)"""
        usage = response_data.get("usage") or {}

        # Support both OpenAI-style {prompt_tokens, completion_tokens} and
        # Responses API-style {input_tokens, output_tokens}.
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is None and output_tokens is None:
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
        if input_tokens is None and output_tokens is None:
            total = usage.get("total_tokens")
            if total is not None:
                input_tokens, output_tokens = total, 0
            else:
                input_tokens, output_tokens = 0, 0
                logger.warning(f"Missing usage in provider response (provider={provider}, task_id={task_id}).")

        input_tokens = int(input_tokens or 0)
        output_tokens = int(output_tokens or 0)
        total_tokens = input_tokens + output_tokens

        cached_input_tokens = 0
        try:
            details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
            if isinstance(details, dict):
                cached_input_tokens = int(details.get("cached_tokens") or details.get("cache_read_tokens") or 0)
        except Exception:
            cached_input_tokens = 0
        if cached_input_tokens < 0:
            cached_input_tokens = 0
        if cached_input_tokens > input_tokens:
            cached_input_tokens = input_tokens

        model = str(response_data.get("model", "") or "")
        provider_config = self.providers[provider]
        pricing_model = self._resolve_pricing_model(provider, model)
        pricing = provider_config.pricing.get(pricing_model, {})

        input_price = float(pricing.get("input", provider_config.default_input_price))
        cached_input_price = float(pricing.get("input_cache_read", input_price))
        output_price = float(pricing.get("output", provider_config.default_output_price))

        non_cached_input_tokens = max(0, input_tokens - cached_input_tokens)
        input_cost = (non_cached_input_tokens / 1_000_000) * input_price
        cached_input_cost = (cached_input_tokens / 1_000_000) * cached_input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        total_cost = input_cost + cached_input_cost + output_cost

        self.usage_per_task[task_id].add_usage(provider, model, total_tokens, total_cost)
        logger.info(f"Updated usage for task: {task_id}")
        if pricing_model and pricing_model != model:
            logger.info(f"Provider: {provider} | Model: {model} (priced_as={pricing_model}) | Tokens: {total_tokens} | Cost: {total_cost}")
        else:
            logger.info(f"Provider: {provider} | Model: {model} | Tokens: {total_tokens} | Cost: {total_cost}")
        return total_tokens, total_cost, model

    def set_allowed_task_ids(self, task_ids: Optional[list[str]] = None):
        """Set allowed task IDs for limiting other requests and tracking usage."""
        if task_ids is None:
            task_ids = []
        self.allowed_task_ids = set(task_ids)
        self.usage_per_task = {task_id: LLMUsage() for task_id in task_ids}

    def is_cost_exceeded(self, task_id: str) -> bool:
        return self.usage_per_task[task_id].total_cost >= COST_LIMIT_PER_TASK


def _looks_like_unsupported_response_format(resp: httpx.Response) -> bool:
    try:
        payload = resp.json()
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    msg = str(err.get("message") or "")
    code = str(err.get("code") or "")
    param = str(err.get("param") or "")
    text = (msg + " " + param + " " + code).lower()
    return "response_format" in text and ("unsupported" in text or "invalid" in text or "unknown" in text or code == "unsupported_parameter")


def _extract_llm_input(provider: str, suffix: str, body: dict) -> Optional[str]:
    try:
        if not isinstance(body, dict):
            return None
        # Responses API
        if suffix == "/v1/responses":
            val = body.get("input") or body.get("messages")
            return json.dumps(val, ensure_ascii=False)
        # Chat completions
        if suffix == "/v1/chat/completions":
            return json.dumps(body.get("messages"), ensure_ascii=False)
        # Fallback
        if "prompt" in body:
            return json.dumps(body.get("prompt"), ensure_ascii=False)
    except Exception:
        return None
    return None


def _extract_llm_output(provider: str, suffix: str, data: dict) -> Optional[str]:
    try:
        if not isinstance(data, dict):
            return None
        # Responses API
        if suffix == "/v1/responses":
            output = data.get("output") or data.get("output_text") or data.get("response") or data.get("content")
            return json.dumps(output, ensure_ascii=False)
        # Chat completions
        if suffix == "/v1/chat/completions":
            choices = data.get("choices") or []
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(msg, dict):
                    return json.dumps(msg.get("content"), ensure_ascii=False)
                return json.dumps(choices[0], ensure_ascii=False)
        # Fallback
        if "text" in data:
            return json.dumps(data.get("text"), ensure_ascii=False)
    except Exception:
        return None
    return None


# Initialize the gateway
gateway = LLMGateway()
app = FastAPI(title="Autoppia LLM Gateway", description="Simple gateway for LLM requests with cost limiting")


@app.on_event("startup")
async def _startup() -> None:
    # Best-effort: populate Chutes pricing so strict pricing works immediately.
    try:
        await gateway.refresh_chutes_pricing()
    except Exception:
        pass


def _require_admin(request: Request) -> None:
    if not SANDBOX_GATEWAY_ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="Gateway admin token not configured")
    token = request.headers.get("x-admin-token", "")
    if not secrets.compare_digest(token, SANDBOX_GATEWAY_ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/usage/{task_id}")
async def get_usage_for_task(task_id: str, request: Request):
    """Get usage for a specific task ID"""
    # Usage is validator-only. Prevent miners from probing cost state.
    _require_admin(request)
    usage = gateway.get_usage_for_task(task_id)
    return {
        "task_id": task_id,
        "total_tokens": usage.total_tokens,
        "total_cost": usage.total_cost,
        "usage_details": {"tokens": usage.tokens, "cost": usage.cost},
        "calls": usage.calls,
    }


@app.post("/set-allowed-task-ids")
async def set_allowed_task_ids(request: Request):
    """Set allowed task IDs for limiting other requests and tracking usage."""
    _require_admin(request)
    try:
        body = await request.json()
        task_ids = body.get("task_ids", [])
        gateway.set_allowed_task_ids(task_ids=task_ids)
    except Exception as e:
        logger.error(f"Error setting allowed task IDs: {e}")
        raise HTTPException(status_code=400, detail=f"Error setting allowed task IDs: {e}")
    return {"status": "allowed task IDs set"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, path: str):
    """Main proxy endpoint for LLM requests"""
    try:
        # Detect provider
        provider = gateway.detect_provider(path)
        if not provider:
            raise HTTPException(status_code=400, detail="Unsupported provider!")

        # Detect task ID for usage tracking
        task_id = gateway.detect_task_id(request)
        if not task_id:
            raise HTTPException(status_code=400, detail="Task ID not found!")

        if gateway.is_cost_exceeded(task_id):
            current_usage = gateway.get_usage_for_task(task_id)
            raise HTTPException(status_code=402, detail=f"Cost limit exceeded. Current: ${current_usage.total_cost:.2f}, Limit: ${COST_LIMIT_PER_TASK:.2f}")

        provider_config = gateway.providers[provider]
        suffix = path.removeprefix(provider)
        if suffix and not suffix.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid provider path")
        if not suffix:
            raise HTTPException(status_code=400, detail="Missing provider path")

        if not gateway._is_allowed_path(provider, suffix):
            raise HTTPException(status_code=400, detail="Unsupported endpoint")

        # Ensure pricing is loaded (Chutes) before we validate model/price.
        await gateway.ensure_provider_pricing(provider)

        # Build upstream URL ensuring the scheme/host always come from the trusted provider config.
        # This prevents authority-section injection like "https://api.openai.com@evil.com/..." .
        base = httpx.URL(provider_config.base_url)
        url = str(base.copy_with(raw_path=suffix.encode("utf-8") if suffix else b""))

        # Forward the request
        headers = {}
        headers["Content-Type"] = "application/json"

        if provider == "openai" and OPENAI_API_KEY:
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

        if provider == "chutes" and CHUTES_API_KEY:
            headers["Authorization"] = f"Bearer {CHUTES_API_KEY}"

        body = await request.body()
        parsed_body = None
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = (request.headers.get("content-type") or "").lower()
            if not content_type.startswith("application/json"):
                raise HTTPException(status_code=400, detail="Content-Type must be application/json")
            if not body:
                raise HTTPException(status_code=400, detail="Missing JSON body")
            try:
                parsed_body = json.loads(body.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid UTF-8 JSON body: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
            if not isinstance(parsed_body, dict):
                raise HTTPException(status_code=400, detail="JSON body must be an object")
            # Disallow streaming: usage accounting (and cost limiting) relies on a
            # usage object in the final JSON response.
            if parsed_body.get("stream") is True:
                raise HTTPException(status_code=400, detail="Streaming is not supported")

        # Enforce per-provider model allowlist and (optionally) strict pricing.
        if request.method in ("POST", "PUT", "PATCH"):
            model = str(parsed_body.get("model") or "")
            if not model:
                raise HTTPException(status_code=400, detail="Missing model")
            if not gateway._is_allowed_model(provider, model):
                raise HTTPException(status_code=400, detail="Model not allowed")
            if GATEWAY_STRICT_PRICING:
                pricing_model = gateway._resolve_pricing_model(provider, model)
                # If Chutes pricing fetch fails (e.g. transient outage), fall back to
                # conservative defaults rather than hard-fail the task.
                if (provider != "chutes" or provider_config.pricing) and pricing_model not in provider_config.pricing:
                    raise HTTPException(status_code=400, detail="Missing pricing for model")

        upstream_body = body
        forced_response_format = False
        if request.method in ("POST", "PUT", "PATCH") and isinstance(parsed_body, dict):
            # Force response_format=json_object for chat completions where possible to
            # reduce miner-side parsing failures (fallback on upstream rejection).
            parsed_body2, forced_response_format = gateway._maybe_force_json_response_format(provider, suffix, parsed_body)
            if forced_response_format:
                upstream_body = json.dumps(parsed_body2).encode("utf-8")

        # Forward request to upstream, with best-effort retries for transient errors.
        # NOTE: max_retries counts additional tries after the initial attempt.
        max_retries = max(0, int(GATEWAY_UPSTREAM_MAX_RETRIES))
        base_delay = max(0.0, float(GATEWAY_UPSTREAM_RETRY_BASE_DELAY_S))
        attempted_without_response_format = False

        sem = gateway._provider_semaphores.get(provider) or asyncio.Semaphore(10_000)

        last_exc: Exception | None = None
        response: httpx.Response | None = None
        attempt = 0

        while True:
            try:
                async with sem:
                    response = await gateway.http_client.request(
                        method=request.method,
                        url=url,
                        headers=headers,
                        params=request.query_params,
                        content=upstream_body,
                    )
            except Exception as e:
                last_exc = e
                response = None
            else:
                # If we forced response_format and upstream rejects it, retry once without it.
                if forced_response_format and not attempted_without_response_format and response.status_code in (400, 422):
                    if _looks_like_unsupported_response_format(response):
                        attempted_without_response_format = True
                        forced_response_format = False
                        upstream_body = body  # original bytes
                        # Do not count this as a retry; it's a compatibility fallback.
                        continue

                # Retry transient upstream errors.
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < max_retries:
                        retry_after_s = 0.0
                        ra = (response.headers.get("retry-after") or "").strip()
                        if ra:
                            try:
                                retry_after_s = float(ra)
                            except Exception:
                                retry_after_s = 0.0
                        delay = max(base_delay * (2**attempt), retry_after_s)
                        delay += random.random() * 0.25
                        attempt += 1
                        await asyncio.sleep(delay)
                        continue

            if response is None:
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    delay += random.random() * 0.25
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue

            break

        if response is None:
            raise HTTPException(status_code=502, detail=f"Upstream request failed: {str(last_exc)[:200] if last_exc else 'unknown error'}")

        # Parse response to extract usage and update tracking
        if response.status_code == 200:
            try:
                response_data = response.json()
                tokens_used, cost_used, model_used = gateway.update_usage_for_task(provider, task_id, response_data)
                # Record call details for downstream logs (best-effort)
                call = {
                    "provider": provider,
                    "model": model_used,
                    "tokens": tokens_used,
                    "cost": cost_used,
                    "timestamp": time.time(),
                }
                call["input"] = _extract_llm_input(provider, suffix, parsed_body) if parsed_body else None
                call["output"] = _extract_llm_output(provider, suffix, response_data)
                gateway.get_usage_for_task(task_id).add_call(call)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(f"Provider returned non-JSON 200 response; skipping usage update (provider={provider}, task_id={task_id}): {exc}")

        # Return response with cost headers
        # NOTE: httpx transparently decodes compressed upstream responses (gzip/br).
        # If we forward the original Content-Encoding header alongside the
        # decoded body, clients may attempt to decompress again and fail
        # (e.g. zlib: "incorrect header check"). Strip hop-by-hop headers and
        # remove content-encoding/length so FastAPI can set correct values.
        response_headers = dict(response.headers)

        # Remove hop-by-hop headers (RFC 7230 §6.1)
        for h in (
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        ):
            response_headers.pop(h, None)
            response_headers.pop(h.title(), None)

        # Prevent double-decompression on the client.
        response_headers.pop("content-encoding", None)
        response_headers.pop("Content-Encoding", None)

        # Let FastAPI compute the correct content-length for the body we return.
        response_headers.pop("content-length", None)
        response_headers.pop("Content-Length", None)

        current_usage = gateway.get_usage_for_task(task_id)
        response_headers["X-Current-Cost"] = str(current_usage.total_cost)
        response_headers["X-Cost-Limit"] = str(COST_LIMIT_PER_TASK)

        return Response(content=response.content, status_code=response.status_code, headers=response_headers)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gateway error: {str(e)}")
