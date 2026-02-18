from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Iterable

import docker
from docker.errors import NotFound


def get_client() -> docker.DockerClient:
    return docker.from_env()


def ensure_network(name: str, internal: bool = True) -> None:
    client = get_client()
    try:
        net = client.networks.get(name)
        # If the network already exists, verify that it matches the requested
        # isolation guarantees. Otherwise a previously-created non-internal
        # network could silently re-enable outbound internet from sandboxed
        # containers.
        try:
            existing_internal = bool((net.attrs or {}).get("Internal", False))
        except Exception:
            existing_internal = False

        allow_non_internal = os.getenv("SANDBOX_ALLOW_NON_INTERNAL_NETWORK", "false").lower() == "true"
        if internal and not existing_internal and not allow_non_internal:
            raise RuntimeError(
                f"Docker network '{name}' exists but is not internal. "
                "Refusing to use it for sandbox isolation. "
                "Remove/recreate the network or set SANDBOX_ALLOW_NON_INTERNAL_NETWORK=true to override."
            )
    except NotFound:
        client.networks.create(name, driver="bridge", internal=internal)


def check_image(image_name: str) -> bool:
    client = get_client()
    try:
        client.images.get(image_name)
        return True
    except NotFound:
        return False


def build_image(context_path: str, tag: str) -> None:
    client = get_client()
    # IMPORTANT:
    # Docker's API defaults to rm=False (unlike `docker build` CLI, which defaults to --rm=true),
    # which leaves intermediate build containers behind (often in status=created). Those quickly
    # accumulate on validators that rebuild images periodically.
    #
    # rm=True: remove intermediate containers after a successful build
    # forcerm=True: remove intermediate containers even if the build fails
    client.images.build(path=context_path, tag=tag, quiet=False, rm=True, forcerm=True)


_LAST_GC_TS = 0.0


def _docker_created_epoch(created: str) -> float:
    """
    Parse Docker's `Created` timestamps into epoch seconds.

    Typical input:
      2026-02-12T22:28:36.943175655Z
    We only need second-level precision for garbage collection decisions.
    """
    s = (created or "").strip()
    if not s:
        return 0.0
    # Strip timezone suffix and fractional seconds.
    if s.endswith("Z"):
        s = s[:-1]
    # Remove timezone offsets if present (e.g. +00:00 / -05:00).
    for sep in ("+", "-"):
        idx = s.find(sep, 19)  # after YYYY-MM-DDTHH:MM:SS
        if idx != -1:
            s = s[:idx]
            break
    s = s.split(".", 1)[0]
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    except Exception:
        return 0.0


def garbage_collect_stale_containers(
    *,
    max_age_seconds: int = 60 * 60,
    min_interval_seconds: int = 10 * 60,
    limit: int = 200,
) -> int:
    """
    Best-effort garbage collection for stale Docker containers.

    Why:
    - If image builds used the Docker API without rm/forcerm, intermediate build containers
      accumulate (often status=created, Cmd contains '#(nop)').
    - We also want to clean up any leftover sandbox containers that are not running.

    Safety:
    - Only targets non-running containers (created/exited).
    - Only removes:
      - Our own sandbox containers by name prefix, OR
      - Likely build intermediates older than max_age_seconds, detected via:
        - Config.Image is an untagged digest (sha256:...) AND
        - Cmd contains '#(nop)' (typical of Docker build step metadata)
    - Throttled by min_interval_seconds.
    """
    global _LAST_GC_TS
    now = time.time()
    if (now - _LAST_GC_TS) < float(min_interval_seconds):
        return 0
    _LAST_GC_TS = now

    client = get_client()
    removed = 0

    for status in ("created", "exited"):
        try:
            containers = client.containers.list(all=True, filters={"status": status})
        except Exception:
            continue

        for c in containers:
            try:
                c.reload()
                attrs = c.attrs or {}
            except Exception:
                attrs = {}

            name = getattr(c, "name", "") or ""
            cfg = (attrs.get("Config") or {}) if isinstance(attrs, dict) else {}
            labels = cfg.get("Labels") or {}
            keep_label = str(labels.get("autoppia.sandbox.keep") or "").strip().lower()
            keep = keep_label in {"1", "true", "yes", "on"}

            # Always remove our own stale sandbox containers, except those explicitly
            # preserved for debugging via SANDBOX_KEEP_AGENT_CONTAINERS (label-based).
            if name.startswith("sandbox-agent-") and keep:
                continue
            if name == "sandbox-gateway" or name.startswith("sandbox-agent-"):
                try:
                    stop_and_remove(c)
                    removed += 1
                except Exception:
                    pass
                if removed >= int(limit):
                    return removed
                continue

            created_epoch = _docker_created_epoch(str(attrs.get("Created") or ""))
            if created_epoch and (now - created_epoch) < float(max_age_seconds):
                continue

            cmd = cfg.get("Cmd") or []
            image = str(cfg.get("Image") or "")
            if isinstance(cmd, list):
                cmd_s = " ".join(str(x) for x in cmd)
            else:
                cmd_s = str(cmd)

            # Heuristic: Docker build step containers typically have '#(nop)' in Cmd and
            # refer to an untagged digest image. This is intentionally conservative so
            # we don't delete unrelated local containers (e.g. demo websites) that may
            # be running on the same Docker host.
            if image.startswith("sha256:") and "#(nop)" in cmd_s:
                try:
                    stop_and_remove(c)
                    removed += 1
                except Exception:
                    pass

            if removed >= int(limit):
                return removed

    return removed


def stop_and_remove(container) -> None:
    try:
        container.stop(timeout=10)
    except Exception as e:
        # Ignore errors when stopping (container might already be stopped)
        pass
    try:
        container.remove(force=True)
    except Exception as e:
        # Ignore errors when removing (container might not exist)
        pass


def cleanup_containers(names: Iterable[str]) -> None:
    client = get_client()
    for name in names:
        try:
            c = client.containers.get(name)
            stop_and_remove(c)
        except NotFound:
            # Container doesn't exist, nothing to clean up
            continue
        except Exception as e:
            # Ignore any other errors (connection issues, etc.)
            # The container might already be stopped or Docker might be unavailable
            continue
