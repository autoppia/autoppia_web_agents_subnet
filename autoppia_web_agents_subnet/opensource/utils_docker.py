from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Iterable

import docker
from docker.errors import NotFound


def get_client() -> docker.DockerClient:
    return docker.from_env()


def ensure_network(name: str, internal: bool = True) -> None:
    client = get_client()
    try:
        client.networks.get(name)
    except NotFound:
        client.networks.create(name, driver="bridge", internal=internal)


def build_image(context_path: str, tag: str) -> None:
    client = get_client()
    client.images.build(path=context_path, tag=tag, quiet=False)


def stop_and_remove(container) -> None:
    try:
        container.stop(timeout=3)
    except Exception:
        pass
    try:
        container.remove(force=True)
    except Exception:
        pass


def cleanup_containers(names: Iterable[str]) -> None:
    client = get_client()
    for name in names:
        try:
            c = client.containers.get(name)
            stop_and_remove(c)
        except NotFound:
            continue


def clone_repo(
    github_url: str,
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
    os.makedirs(dst_dir, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", github_url, dst_dir]
    subprocess.run(cmd, check=True, timeout=timeout)

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
