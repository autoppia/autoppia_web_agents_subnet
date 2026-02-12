from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

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


def normalize_and_validate_github_url(
        raw_url: Optional[str], 
        *, 
        miner_uid: Optional[int] = None
    ) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize and validate a GitHub URL, extracting an optional ref (branch/commit).
    Returns (normalized_url, ref) or (None, None) if invalid.
    """
    if not raw_url:
        return None, None

    url = raw_url.strip()
    if not url:
        return None, None

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
        return None, None

    if host != "github.com":
        ColoredLogger.warning(
            f"Rejecting miner github_url with unsupported host{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None, None

    path = (parsed.path or "").strip().rstrip("/")
    if not path or path == "/":
        ColoredLogger.warning(
            f"Rejecting miner github_url with empty repo path{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None, None

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        ColoredLogger.warning(
            f"Rejecting miner github_url without owner/repo structure{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None, None

    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        ColoredLogger.warning(
            f"Rejecting miner github_url with invalid owner/repo{miner_tag}: {raw_url}",
            ColoredLogger.YELLOW,
        )
        return None, None

    normalized = f"https://github.com/{owner}/{repo}"
    ColoredLogger.info(
        f"Normalized miner github_url{miner_tag}: {raw_url} -> {normalized}",
        ColoredLogger.BLUE,
    )

    if len(segments) < 4:
        ColoredLogger.info(
            f"Commit hash or branch not specified in github_url{miner_tag}; defaulting to main branch: {raw_url}",
            ColoredLogger.BLUE,
        )
        return normalized, None

    ref = segments[3]
    ColoredLogger.info(
        f"Extracted ref from github_url{miner_tag}: {raw_url} -> {ref}",
        ColoredLogger.BLUE,
    )

    return normalized, ref


def _github_repo_preflight_size_bytes(normalized_url: str, *, timeout: float = 5.0) -> Optional[int]:
    """
    Best-effort GitHub REST API preflight to estimate repo size before cloning.

    GitHub returns `size` in KB for a repository (not including git history), which is
    useful to quickly reject obviously-too-large repos before running `git clone`.

    If the API request fails (rate limit, private repo, etc.), returns None and the
    caller should fall back to on-disk enforcement during/after clone.
    """
    try:
        parsed = urlparse(normalized_url)
        segments = [s for s in (parsed.path or "").strip("/").split("/") if s]
        if len(segments) < 2:
            return None
        owner, repo = segments[0], segments[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
    except Exception:
        return None

    api_url = f"https://api.github.com/repos/{owner}/{repo}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "autoppia-sandbox-preflight",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = Request(api_url, headers=headers, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        size_kb = payload.get("size")
        if size_kb is None:
            return None
        return int(size_kb) * 1024
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None
    except Exception:
        return None


def clone_repo(
    raw_url: str,
    dst_dir: str,
    timeout: int = 60,
    max_bytes: int = 50 * 1024 * 1024,
    max_files: int = 2000,
) -> None:
    """
    Clone a miner repo with basic resource limits.

    - Shallow clone (--depth=1) to avoid large histories.
    - Enforce a maximum on total bytes and file count under dst_dir to
      mitigate zip-bomb-style or gigantic repositories.
    """
    normalized_url, ref = normalize_and_validate_github_url(raw_url)
    if normalized_url is None:
        raise RuntimeError(f"Invalid GitHub URL: {raw_url}")

    preflight_bytes = _github_repo_preflight_size_bytes(normalized_url, timeout=5.0)
    if preflight_bytes is not None:
        ColoredLogger.info(
            f"GitHub preflight size for {normalized_url}: {preflight_bytes} bytes",
            ColoredLogger.BLUE,
        )
        if preflight_bytes > max_bytes:
            raise RuntimeError(
                f"Sandbox repo too large per GitHub API preflight (bytes={preflight_bytes}, limit={max_bytes})",
            )
    
    os.makedirs(dst_dir, exist_ok=True)    
    cmd_clone = [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        # Partial clone to reduce risk of giant blobs filling disk during clone.
        "--filter=blob:limit=5m",
        normalized_url,
        dst_dir,
    ]

    # Avoid interactive prompts and skip LFS downloads (which can be huge).
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_LFS_SKIP_SMUDGE", "1")

    # Run clone as a subprocess we can kill if it grows beyond our limits.
    proc = subprocess.Popen(
        cmd_clone,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    start = time.time()
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                if rc != 0:
                    raise RuntimeError(f"git clone failed with exit code {rc}")
                break

            if (time.time() - start) > timeout:
                raise TimeoutError("Clone timeout")

            # Fail fast on disk blowups while cloning (not only after clone completes).
            try:
                out = subprocess.check_output(["du", "-sb", dst_dir], stderr=subprocess.DEVNULL, text=True).strip()
                size_bytes = int(out.split()[0]) if out else 0
                if size_bytes > max_bytes:
                    raise RuntimeError(
                        f"Sandbox repo exceeded size limit during clone (bytes={size_bytes}, limit={max_bytes})."
                    )
            except FileNotFoundError:
                # du not available; fall back to post-clone walk only.
                pass
            except subprocess.CalledProcessError:
                # Ignore transient errors during clone (e.g. dir not fully ready).
                pass
            except (ValueError, IndexError):
                pass

            time.sleep(0.2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        # Best-effort cleanup.
        try:
            shutil.rmtree(dst_dir, ignore_errors=True)
        except Exception:
            pass
        raise

    if ref:
        cmd_fetch = ["git", "fetch", "--depth", "1", "origin", ref]
        subprocess.run(cmd_fetch, cwd=dst_dir, check=True, timeout=timeout)

        # Fetching a named ref updates FETCH_HEAD, but does not always create a
        # local branch ref (especially after --single-branch clones). Checkout
        # from FETCH_HEAD to reliably pin the requested branch/tag/commit.
        cmd_checkout = ["git", "checkout", "-B", ref, "FETCH_HEAD"]
        subprocess.run(cmd_checkout, cwd=dst_dir, check=True, timeout=timeout)

    # Ensure cloned repo is readable by non-root users inside the sandbox
    # container (temp directories are typically created with 0700).
    try:
        os.chmod(dst_dir, 0o755)
    except OSError:
        pass

    total_bytes = 0
    total_files = 0
    for root, dirs, files in os.walk(dst_dir):
        for fname in files:
            total_files += 1
            try:
                fpath = os.path.join(root, fname)
                total_bytes += os.path.getsize(fpath)
            except OSError:
                continue
            if total_files > max_files or total_bytes > max_bytes:
                raise RuntimeError(
                    f"Sandbox repo too large (files={total_files}, bytes={total_bytes}); "
                    "rejecting miner repository",
                )


def temp_workdir(prefix: str = "autoppia-sandbox-") -> str:
    path = tempfile.mkdtemp(prefix=prefix)
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    return path
