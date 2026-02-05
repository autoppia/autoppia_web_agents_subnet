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


def check_image(image_name: str) -> bool:
    client = get_client()
    try:
        client.images.get(image_name)
        return True
    except NotFound:
        return False


def build_image(context_path: str, tag: str) -> None:
    client = get_client()
    client.images.build(path=context_path, tag=tag, quiet=False)


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

