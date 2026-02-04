from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse, parse_qs

from autoppia_web_agents_subnet.utils.logging import ColoredLogger


def _normalize_github_ssh(url: str) -> str:
    """
    Support common SSH-style GitHub URLs by rewriting them to https.

    Examples:
      - git@github.com:owner/repo.git  -> https://github.com/owner/repo
    """
    if url.startswith("git@github.com:"):
        path = url[len("git@github.com:") :].strip()
        if path.endswith(".git"):
            path = path[:-4]
        return f"https://github.com/{path}"
    return url


def _looks_like_commit_ref(value: Optional[str]) -> bool:
    if not value:
        return False
    v = value.strip()
    # Accept typical short or full SHA-1 lengths.
    return 7 <= len(v) <= 40 and all(c in "0123456789abcdefABCDEF" for c in v)


def _has_explicit_commit_pin(raw_url: str, parsed) -> bool:
    """
    Best-effort detection that the URL is pinned to a specific commit/ref,
    instead of a moving branch.

    Heuristics:
      - Query params ?ref=<sha>, ?commit=<sha>, or ?sha=<sha>.
      - Path like /owner/repo/commit/<sha> or /owner/repo/tree/<sha>.
      - Trailing @<sha> suffix.
    """
    try:
        qs = parse_qs(parsed.query or "")
    except Exception:
        qs = {}
    for key in ("ref", "commit", "sha"):
        vals = qs.get(key) or []
        if vals and _looks_like_commit_ref(vals[0]):
            return True

    segments = [segment for segment in (parsed.path or "").split("/") if segment]
    if len(segments) >= 4 and segments[2] in {"commit", "tree"} and _looks_like_commit_ref(segments[3]):
        return True

    if "@" in raw_url:
        suffix = raw_url.rsplit("@", 1)[-1]
        if _looks_like_commit_ref(suffix):
            return True

    return False


def normalize_and_validate_github_url(raw_url: Optional[str], *, miner_uid: Optional[int] = None) -> Optional[str]:
    """
    Normalize and validate a miner-provided GitHub repository URL.

    Enforcement:
      - HTTPS scheme only (no http / ssh).
      - Host must be github.com (or www.github.com).
      - Path must look like /owner/repo[…]; extras are stripped.
      - Query/fragment are removed.

    Returns a normalized https://github.com/owner/repo URL, or None when invalid.
    """
    if not raw_url:
        return None

    url = raw_url.strip()
    if not url:
        return None

    # Handle SSH-style URLs first.
    url = _normalize_github_ssh(url)

    # Prefix bare hosts with https://
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)

    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    miner_tag = f" (uid={miner_uid})" if miner_uid is not None else ""

    if parsed.scheme != "https":
        ColoredLogger.warning(
            f"Rejecting miner github_url with non-HTTPS scheme{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None

    if host != "github.com":
        ColoredLogger.warning(
            f"Rejecting miner github_url with unsupported host{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None

    path = (parsed.path or "").strip().rstrip("/")
    if not path or path == "/":
        ColoredLogger.warning(
            f"Rejecting miner github_url with empty repo path{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        ColoredLogger.warning(
            f"Rejecting miner github_url without owner/repo structure{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None

    owner, repo = segments[0], segments[1]
    if not owner or not repo:
        ColoredLogger.warning(
            f"Rejecting miner github_url with invalid owner/repo{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None

    normalized = f"https://github.com/{owner}/{repo}"
    ColoredLogger.debug(
        f"Normalized miner github_url{miner_tag}: {raw_url} -> {normalized}",
        ColoredLogger.GRAY,
    )

    return normalized

