from __future__ import annotations

import os
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
