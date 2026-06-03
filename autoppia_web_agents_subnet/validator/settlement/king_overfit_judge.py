from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from autoppia_web_agents_subnet.opensource.utils_git import clone_repo
from autoppia_web_agents_subnet.utils.logging import ColoredLogger
from autoppia_web_agents_subnet.validator import config as validator_config


_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".cache",
    "logs",
}
_EXCLUDED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
}
_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".json",
    ".jsonl",
    ".toml",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".md",
    ".txt",
    ".sh",
    ".dockerfile",
}
_TEXT_FILENAMES = {
    "Dockerfile",
    "Makefile",
    "Procfile",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
}
_BENCHMARK_TERMS = [
    "autocinema",
    "autobooks",
    "autozone",
    "autodining",
    "autocrm",
    "automail",
    "autodelivery",
    "autolodge",
    "autoconnect",
    "autowork",
    "autocalendar",
    "autolist",
    "autodrive",
    "autohealth",
    "autostats",
    "autodiscord",
    "demo_web",
    "demo-web",
    "84.247.180.192",
    "ADD_EVENT",
    "QUICK_REORDER",
    "ABOUT_PAGE_VIEW",
]


@dataclass
class KingOverfitLLMJudgeVerdict:
    decision: str
    is_overfitted: bool
    confidence: float
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    bundle_chars: int = 0
    files_included: int = 0
    files_considered: int = 0

    @property
    def rejects(self) -> bool:
        if self.error:
            return False
        if not self.is_overfitted:
            return False
        if self.decision.strip().lower() not in {"reject", "disqualify", "fail"}:
            return False
        if self.confidence < float(getattr(validator_config, "KING_OVERFIT_LLM_REJECT_CONFIDENCE", 0.80) or 0.80):
            return False
        return bool(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "is_overfitted": bool(self.is_overfitted),
            "confidence": float(self.confidence),
            "summary": self.summary,
            "evidence": self.evidence,
            "error": self.error,
            "bundle_chars": int(self.bundle_chars),
            "files_included": int(self.files_included),
            "files_considered": int(self.files_considered),
            "raw": self.raw,
        }


def _is_probably_text_file(path: Path) -> bool:
    if path.name in _TEXT_FILENAMES:
        return True
    suffix = path.suffix.lower()
    return suffix in _TEXT_EXTENSIONS


def _safe_read_text(path: Path, *, max_chars: int) -> str | None:
    try:
        raw = path.read_bytes()
    except Exception:
        return None
    if b"\x00" in raw[:4096]:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except Exception:
            return None
    if len(text) > max_chars:
        return f"{text[:max_chars]}\n\n[TRUNCATED file_chars={len(text)}]"
    return text


def _iter_candidate_files(repo_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_dir.rglob("*"):
        try:
            rel = path.relative_to(repo_dir)
        except Exception:
            continue
        parts = set(rel.parts)
        if parts & _EXCLUDED_DIRS:
            continue
        if path.name in _EXCLUDED_FILES:
            continue
        if not path.is_file():
            continue
        if not _is_probably_text_file(path):
            continue
        files.append(path)
    return sorted(files, key=lambda p: (0 if p.name in {"main.py", "app.py", "server.py", "harvester.py"} else 1, str(p)))


def _suspicion_score(path: Path, text: str) -> int:
    joined = f"{path.as_posix()}\n{text}".lower()
    score = 0
    for term in _BENCHMARK_TERMS:
        if term.lower() in joined:
            score += 5
    for pattern in (
        "if project",
        "if web_project",
        "if task_id",
        "if use_case",
        "trajectory_map",
        "golden",
        "hardcoded",
        "prebuilt",
        "seed=",
        "return [{",
        "\"trajectory\"",
        "'trajectory'",
    ):
        if pattern in joined:
            score += 2
    return score


def build_repo_source_bundle(
    repo_dir: str | Path,
    *,
    max_files: int,
    max_bundle_chars: int,
    max_file_chars: int,
) -> tuple[str, dict[str, Any]]:
    repo = Path(repo_dir)
    candidate_files = _iter_candidate_files(repo)
    loaded: list[tuple[int, Path, str]] = []
    for path in candidate_files:
        text = _safe_read_text(path, max_chars=max_file_chars)
        if text is None:
            continue
        loaded.append((_suspicion_score(path.relative_to(repo), text), path, text))
    loaded.sort(key=lambda item: (-item[0], str(item[1].relative_to(repo))))

    tree_lines = []
    for path in candidate_files[:500]:
        try:
            tree_lines.append(path.relative_to(repo).as_posix())
        except Exception:
            pass

    sections = [
        "# Repository Tree",
        "\n".join(tree_lines),
        "",
        "# Inline Source Files",
    ]
    files_included = 0
    current_chars = sum(len(section) for section in sections)
    for _score, path, text in loaded[: max(max_files, 0)]:
        rel = path.relative_to(repo).as_posix()
        section = f"\n\n--- FILE: {rel} ---\n{text}"
        if current_chars + len(section) > max_bundle_chars:
            remaining = max_bundle_chars - current_chars
            if remaining > 500:
                sections.append(section[:remaining] + "\n[TRUNCATED bundle limit]")
                files_included += 1
            break
        sections.append(section)
        current_chars += len(section)
        files_included += 1

    bundle = "\n".join(sections)
    meta = {
        "files_considered": len(candidate_files),
        "files_included": files_included,
        "bundle_chars": len(bundle),
    }
    return bundle, meta


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("judge response must be a JSON object")
    return parsed


def _coerce_verdict(raw: dict[str, Any], *, meta: dict[str, Any], error: str | None = None) -> KingOverfitLLMJudgeVerdict:
    evidence = raw.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    normalized_evidence = [item for item in evidence if isinstance(item, dict)]
    try:
        confidence = float(raw.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    decision = str(raw.get("decision") or ("reject" if raw.get("is_overfitted") else "pass")).strip().lower()
    return KingOverfitLLMJudgeVerdict(
        decision=decision,
        is_overfitted=bool(raw.get("is_overfitted", False)),
        confidence=max(0.0, min(confidence, 1.0)),
        summary=str(raw.get("summary") or ""),
        evidence=normalized_evidence,
        raw=raw,
        error=error,
        bundle_chars=int(meta.get("bundle_chars", 0) or 0),
        files_included=int(meta.get("files_included", 0) or 0),
        files_considered=int(meta.get("files_considered", 0) or 0),
    )


def _build_prompt(*, miner_uid: int, github_url: str, git_commit: str | None, reward: float, bundle: str) -> list[dict[str, str]]:
    system = (
        "You are KingOverfitLLMJudge for the Autoppia web-agents subnet. "
        "Your job is to detect benchmark-overfitted miner harvester repos. "
        "A valid harvester may use generic browser automation heuristics, DOM/accessibility inspection, Playwright, LLM planning, and generic tools such as navigate/click/type/wait/done. "
        "Reject only when there is concrete evidence that the repo encodes Autoppia/IWA demo-web benchmark knowledge, fixed trajectories, hardcoded task/project/use-case/seed/prompt logic, copied golden traces, or lookup tables that solve known benchmark tasks instead of solving arbitrary tasks at runtime. "
        "Suspicion is not enough. If evidence is weak or generic heuristics could reasonably work on unseen websites, pass."
    )
    user = f"""
Evaluate this candidate king harvester repo.

Miner UID: {miner_uid}
GitHub URL: {github_url}
Commit: {git_commit or "unknown"}
Candidate reward: {reward:.6f}

Known benchmark/demo-web names and terms to treat as suspicious when hardcoded:
{", ".join(_BENCHMARK_TERMS)}

Return ONLY a JSON object with this schema:
{{
  "decision": "pass" | "reject",
  "is_overfitted": boolean,
  "confidence": number,
  "summary": "short explanation",
  "evidence": [
    {{
      "file": "relative/path",
      "line_or_pattern": "line number, symbol, or code pattern",
      "reason": "why this is benchmark-specific overfit"
    }}
  ],
  "allowed_generic_heuristics": ["optional generic mechanisms that are fine"]
}}

Repository bundle:
{bundle}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _call_openai_chat(messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = (os.getenv("KING_OVERFIT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("KING_OVERFIT_LLM_API_KEY/OPENAI_API_KEY is not set")
    base_url = (
        str(getattr(validator_config, "KING_OVERFIT_LLM_BASE_URL", "") or "").strip()
        or "https://api.openai.com/v1"
    ).rstrip("/")
    model = str(getattr(validator_config, "KING_OVERFIT_LLM_MODEL", "gpt-5-mini") or "gpt-5-mini")
    timeout = float(getattr(validator_config, "KING_OVERFIT_LLM_TIMEOUT_SECONDS", 90.0) or 90.0)
    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Autoppia-Task-Id": "king-overfit-llm-judge",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        if response.status_code >= 400:
            body = " ".join((response.text or "").split())[:1000]
            raise RuntimeError(f"LLM judge HTTP {response.status_code}: {body}")
        data = response.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("LLM judge returned empty content")
    return _extract_json_object(content)


async def run_king_overfit_llm_judge(
    *,
    miner_uid: int,
    github_url: str,
    git_commit: str | None,
    reward: float,
) -> KingOverfitLLMJudgeVerdict:
    if not bool(getattr(validator_config, "KING_OVERFIT_LLM_JUDGE_ENABLED", True)):
        return KingOverfitLLMJudgeVerdict(
            decision="pass",
            is_overfitted=False,
            confidence=0.0,
            summary="KingOverfitLLMJudge disabled",
            error="disabled",
        )

    tmp_dir = tempfile.mkdtemp(prefix="autoppia_king_overfit_")
    meta: dict[str, Any] = {}
    try:
        repo_dir = Path(tmp_dir) / "repo"
        clone_repo(str(github_url), str(repo_dir), timeout=90, max_bytes=80 * 1024 * 1024, max_files=3000)
        bundle, meta = build_repo_source_bundle(
            repo_dir,
            max_files=int(getattr(validator_config, "KING_OVERFIT_LLM_MAX_FILES", 80) or 80),
            max_bundle_chars=int(getattr(validator_config, "KING_OVERFIT_LLM_MAX_BUNDLE_CHARS", 180_000) or 180_000),
            max_file_chars=int(getattr(validator_config, "KING_OVERFIT_LLM_MAX_FILE_CHARS", 20_000) or 20_000),
        )
        messages = _build_prompt(
            miner_uid=int(miner_uid),
            github_url=str(github_url),
            git_commit=git_commit,
            reward=float(reward),
            bundle=bundle,
        )
        raw = await _call_openai_chat(messages)
        verdict = _coerce_verdict(raw, meta=meta)
        ColoredLogger.info(
            f"[KingOverfitLLMJudge] uid={miner_uid} decision={verdict.decision} overfit={verdict.is_overfitted} confidence={verdict.confidence:.2f} files={verdict.files_included}/{verdict.files_considered}",
            ColoredLogger.GOLD if verdict.rejects else ColoredLogger.BLUE,
        )
        return verdict
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        ColoredLogger.warning(
            f"[KingOverfitLLMJudge] fail-open for uid={miner_uid}: {error}",
            ColoredLogger.YELLOW,
        )
        return _coerce_verdict(
            {"decision": "pass", "is_overfitted": False, "confidence": 0.0, "summary": "Judge failed open"},
            meta=meta,
            error=error,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


__all__ = [
    "KingOverfitLLMJudgeVerdict",
    "build_repo_source_bundle",
    "run_king_overfit_llm_judge",
]
