from __future__ import annotations

import os
import shutil
import time
import subprocess

import hashlib
import secrets
from pathlib import Path
from typing import Dict, Optional

import httpx
import bittensor as bt
from docker.types import LogConfig

from autoppia_web_agents_subnet.opensource.utils_docker import (
    check_image,
    build_image,
    cleanup_containers,
    ensure_network,
    garbage_collect_stale_containers,
    get_client,
    stop_and_remove,
)
from autoppia_web_agents_subnet.opensource.utils_git import (
    clone_repo,
    temp_workdir,
)
from autoppia_web_agents_subnet.validator.config import (
    SANDBOX_NETWORK_NAME,
    SANDBOX_GATEWAY_IMAGE,
    SANDBOX_GATEWAY_HOST,
    SANDBOX_GATEWAY_PORT,
    SANDBOX_AGENT_IMAGE,
    SANDBOX_AGENT_PORT,
    SANDBOX_CLONE_TIMEOUT,
    SANDBOX_KEEP_AGENT_CONTAINERS,
    SANDBOX_AGENT_LOG_ERRORS,
    SANDBOX_AGENT_LOG_DECISIONS,
    SANDBOX_AGENT_RETURN_METRICS,
    COST_LIMIT_ENABLED,
    COST_LIMIT_VALUE,
)


_PROVIDER_TO_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "chutes": "CHUTES_API_KEY",
}


def _fingerprint_ctx(ctx_dir: str) -> str:
    """Stable-ish fingerprint for a build context to force rebuilds on changes."""
    h = hashlib.sha256()
    base = Path(ctx_dir)

    # Hash all files under the context directory (small contexts; deterministic order).
    for fp in sorted(base.rglob("*")):
        if not fp.is_file():
            continue
        if "__pycache__" in fp.parts or ".git" in fp.parts:
            continue
        rel = str(fp.relative_to(base)).replace("\\", "/")
        h.update(rel.encode("utf-8"))
        try:
            h.update(fp.read_bytes())
        except OSError:
            continue

    return h.hexdigest()[:12]


def _tag_with_fingerprint(image: str, fp: str) -> str:
    # If an explicit tag exists, append the fingerprint to it.
    if ":" in image:
        repo, tag = image.rsplit(":", 1)
        return f"{repo}:{tag}-{fp}"
    return f"{image}:{fp}"


def _csv_env(name: str) -> set[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _pick_host_log_dir() -> str:
    preferred = os.getenv("SANDBOX_LOG_DIR") or "/var/log/autoppia-sandbox"
    fallback = os.getenv("SANDBOX_LOG_DIR_FALLBACK") or "/tmp/autoppia-sandbox-logs"
    for candidate in (preferred, fallback):
        try:
            os.makedirs(candidate, exist_ok=True)
            # Ensure non-root containers can write logs regardless of host uid/gid.
            os.chmod(candidate, 0o777)
            if os.access(candidate, os.W_OK):
                return candidate
        except Exception:
            continue
    return fallback


def _ensure_writable_file(path: str, mode: int = 0o666) -> None:
    """
    Ensure an existing file is writable by non-root containers.

    This avoids failures when a previous run created log files as root (0644),
    then we later run containers as an unprivileged user.
    """
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(path):
            # Create the file if missing; permissions will be set next.
            with open(path, "a", encoding="utf-8"):
                pass
        os.chmod(path, mode)
    except Exception:
        pass


def _nano_cpus_from_env(name: str, *, default: Optional[float] = None) -> Optional[int]:
    """
    Convert a CPU limit expressed as a float ("cpus") into Docker's nano_cpus int.

    - name: env var holding a float, e.g. "1.5" for 1.5 CPUs
    - default: used when env var is missing/empty
    """
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        if default is None:
            return None
        cpus = float(default)
    else:
        try:
            cpus = float(str(raw).strip())
        except Exception:
            return None

    if cpus <= 0:
        return None
    return int(cpus * 1_000_000_000)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    s = str(raw).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _docker_log_config(*, kind: str) -> Optional[LogConfig]:
    """
    Best-effort protection against log spam filling validator disk.

    This caps the Docker `json-file` logs written to the host under /var/lib/docker.
    """
    if not _env_bool("SANDBOX_DOCKER_LOG_LIMITS", True):
        return None

    kind_s = (kind or "").strip().lower()
    if kind_s == "gateway":
        max_size = (os.getenv("SANDBOX_GATEWAY_DOCKER_LOG_MAX_SIZE") or "").strip() or (os.getenv("SANDBOX_DOCKER_LOG_MAX_SIZE") or "").strip() or "20m"
        max_files = (os.getenv("SANDBOX_GATEWAY_DOCKER_LOG_MAX_FILES") or "").strip() or (os.getenv("SANDBOX_DOCKER_LOG_MAX_FILES") or "").strip() or "3"
    elif kind_s == "agent":
        max_size = (os.getenv("SANDBOX_AGENT_DOCKER_LOG_MAX_SIZE") or "").strip() or (os.getenv("SANDBOX_DOCKER_LOG_MAX_SIZE") or "").strip() or "10m"
        max_files = (os.getenv("SANDBOX_AGENT_DOCKER_LOG_MAX_FILES") or "").strip() or (os.getenv("SANDBOX_DOCKER_LOG_MAX_FILES") or "").strip() or "3"
    else:
        return None

    if not max_size or not max_files:
        return None

    return LogConfig(
        type=LogConfig.types.JSON,
        config={
            "max-size": str(max_size),
            "max-file": str(max_files),
        },
    )


class AgentInstance:
    def __init__(self, uid: int, container, temp_dir: str, port: int, git_commit: Optional[str] = None):
        self.uid = uid
        self.container = container
        self.temp_dir = temp_dir
        self.port = port
        self.git_commit = git_commit

    @property
    def base_url(self) -> str:
        """
        Base URL for host <-> agent communication.

        Strategy:
          1) Prefer an explicit host port mapping (Ports[<port>/tcp]) so the
             host talks to the agent via 127.0.0.1:HOST_PORT even though the
             container itself lives on the internal sandbox network.
          2) Fallback to container IP if no port mapping is present.
        """
        try:
            net = (self.container.attrs or {}).get("NetworkSettings", {}) or {}
            ports_info = net.get("Ports") or {}
            bindings = ports_info.get(f"{self.port}/tcp") or []
            if bindings:
                host_ip = bindings[0].get("HostIp") or "127.0.0.1"
                host_port = bindings[0].get("HostPort")
                if host_ip and host_port:
                    return f"http://{host_ip}:{host_port}"

            networks = net.get("Networks", {}) or {}
            if SANDBOX_NETWORK_NAME in networks and networks[SANDBOX_NETWORK_NAME].get("IPAddress"):
                ip_addr = networks[SANDBOX_NETWORK_NAME]["IPAddress"]
                return f"http://{ip_addr}:{self.port}"
        except Exception:
            return ""

        return ""


class SandboxManager:
    """
    Lightweight runtime to clone miner repos and serve them in isolated containers
    with LLM usage tracking and cost management via FastAPI gateway.
    """

    def __init__(self):
        self.client = get_client()
        self._agents: Dict[int, AgentInstance] = {}
        self.keep_agent_containers = bool(SANDBOX_KEEP_AGENT_CONTAINERS)

        self.base_dir = os.path.dirname(__file__)
        self.sandbox_ctx = os.path.join(self.base_dir, "sandbox")
        self.gateway_ctx = os.path.join(self.base_dir, "gateway")
        self.sandbox_image = _tag_with_fingerprint(SANDBOX_AGENT_IMAGE, _fingerprint_ctx(self.sandbox_ctx))
        self.gateway_image = _tag_with_fingerprint(SANDBOX_GATEWAY_IMAGE, _fingerprint_ctx(self.gateway_ctx))
        # Admin token is used to protect privileged gateway endpoints from
        # untrusted miner containers on the same Docker network.
        self.gateway_admin_token = os.getenv("SANDBOX_GATEWAY_ADMIN_TOKEN") or secrets.token_urlsafe(32)
        self.host_log_dir = _pick_host_log_dir()

        ensure_network(SANDBOX_NETWORK_NAME, internal=True)
        # Best-effort cleanup of stale Docker build intermediates (from older versions),
        # throttled and scoped to non-running containers.
        try:
            garbage_collect_stale_containers()
        except Exception:
            pass

    def _agent_container_name(self, uid: int, *, git_commit: Optional[str] = None) -> str:
        """
        Return the container name for an agent.

        Default behavior uses a stable per-uid name so we can replace containers cleanly.
        In debugging mode we create a unique name so containers can be preserved for
        post-mortem inspection (docker logs, filesystem, etc.).
        """
        if not self.keep_agent_containers:
            return f"sandbox-agent-{uid}"

        short = (str(git_commit or "").strip()[:7]) if git_commit else ""
        ts_ms = int(time.time() * 1000)
        if short:
            return f"sandbox-agent-{uid}-{short}-{ts_ms}"
        return f"sandbox-agent-{uid}-{ts_ms}"

    def deploy_gateway(self):
        self._validate_gateway_provider_keys()

        if not check_image(self.gateway_image):
            bt.logging.info("Sandbox gateway image not found; building...")
            build_image(self.gateway_ctx, self.gateway_image)

        cleanup_containers([SANDBOX_GATEWAY_HOST])
        _ensure_writable_file(os.path.join(self.host_log_dir, "gateway.log"))
        env = {
            "COST_LIMIT_ENABLED": str(COST_LIMIT_ENABLED),
            "COST_LIMIT_PER_TASK": str(COST_LIMIT_VALUE),
            "COST_LIMIT_VALUE": str(COST_LIMIT_VALUE),
            "SANDBOX_GATEWAY_PORT": str(SANDBOX_GATEWAY_PORT),
            "SANDBOX_GATEWAY_ADMIN_TOKEN": str(self.gateway_admin_token),
        }
        # Propagate optional non-secret gateway tuning knobs (safe to expose inside the
        # gateway container; does not go to miner containers).
        for key in (
            "GATEWAY_ALLOWED_PROVIDERS",
            "OPENAI_ALLOWED_MODELS",
            "CHUTES_ALLOWED_MODELS",
            "OPENAI_ALLOWED_PATHS",
            "CHUTES_ALLOWED_PATHS",
            "GATEWAY_STRICT_PRICING",
            "CHUTES_PRICING_TTL_SECONDS",
            "CHUTES_PRICING_TIMEOUT_SECONDS",
            "GATEWAY_FORCE_JSON_RESPONSE_FORMAT",
            "GATEWAY_OPENAI_MAX_CONCURRENCY",
            "GATEWAY_CHUTES_MAX_CONCURRENCY",
            "GATEWAY_UPSTREAM_MAX_RETRIES",
            "GATEWAY_UPSTREAM_RETRY_BASE_DELAY_S",
        ):
            val = os.getenv(key)
            if val is not None and str(val).strip() != "":
                env[key] = str(val)
        # Propagate API keys to the gateway
        for key in ("OPENAI_API_KEY", "CHUTES_API_KEY"):
            val = os.getenv(key)
            if val:
                env[key] = val

        run_kwargs = dict(
            name=SANDBOX_GATEWAY_HOST,
            image=self.gateway_image,
            volumes={
                self.host_log_dir: {"bind": "/app/logs", "mode": "rw"},
            },
            network=SANDBOX_NETWORK_NAME,
            environment=env,
            ports={f"{SANDBOX_GATEWAY_PORT}/tcp": ("127.0.0.1", SANDBOX_GATEWAY_PORT)},
            # Hardening: the gateway should not need to write outside its log dir and /tmp.
            read_only=True,
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=256m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            pids_limit=512,
            mem_limit=os.getenv("SANDBOX_GATEWAY_MEM_LIMIT", "1g"),
            init=True,
            detach=True,
        )
        log_config = _docker_log_config(kind="gateway")
        if log_config is not None:
            run_kwargs["log_config"] = log_config
        nano_cpus = _nano_cpus_from_env("SANDBOX_GATEWAY_CPU_LIMIT", default=1.0)
        if nano_cpus is not None:
            run_kwargs["nano_cpus"] = nano_cpus

        # Best-effort compatibility: some older Docker daemons may reject NanoCPUs
        # or per-container log config overrides.
        for _ in range(3):
            try:
                self.gateway_container = self.client.containers.run(**run_kwargs)
                break
            except Exception as e:
                msg = str(e)
                if "log" in msg.lower() and "log_config" in run_kwargs:
                    run_kwargs.pop("log_config", None)
                    continue
                if ("nano_cpus" in msg or "NanoCPUs" in msg) and "nano_cpus" in run_kwargs:
                    run_kwargs.pop("nano_cpus", None)
                    continue
                raise
        # Attach to default bridge for egress
        try:
            bridge = self.client.networks.get("bridge")
            bridge.connect(self.gateway_container)
        except Exception:
            pass

        if not self._wait_for_gateway_health():
            try:
                stop_and_remove(self.gateway_container)
            except Exception:
                pass
            raise RuntimeError(f"Gateway failed health check at http://127.0.0.1:{SANDBOX_GATEWAY_PORT}/health")

        # Fail-fast if the gateway cannot reach its upstream providers. This avoids
        # silent "all tasks fail" behavior when the gateway has no internet egress.
        try:
            self._validate_gateway_upstream_egress()
        except Exception:
            try:
                stop_and_remove(self.gateway_container)
            except Exception:
                pass
            raise

    def _validate_gateway_upstream_egress(self) -> None:
        if not _env_bool("SANDBOX_GATEWAY_EGRESS_CHECK", True):
            return

        container = getattr(self, "gateway_container", None)
        if container is None:
            raise RuntimeError("Gateway container not available for egress check")

        timeout_s = float(_env_float("SANDBOX_GATEWAY_EGRESS_CHECK_TIMEOUT_SECONDS", 5.0))
        retries = int(_env_int("SANDBOX_GATEWAY_EGRESS_CHECK_RETRIES", 2))
        allowed = sorted(self._get_allowed_gateway_providers())

        failures: list[str] = []
        for provider in allowed:
            ok = False
            last_err = ""
            for attempt in range(max(retries, 1)):
                ok, last_err = self._gateway_exec_check_provider(provider, timeout_s=timeout_s)
                if ok:
                    break
                # Small backoff to avoid immediate retry storms.
                time.sleep(0.25 * (attempt + 1))
            if not ok:
                failures.append(f"{provider}: {last_err}".strip())

        if failures:
            msg = "Gateway upstream egress check failed:\n  - " + "\n  - ".join(failures)
            raise RuntimeError(msg)

    def _gateway_exec_check_provider(self, provider: str, *, timeout_s: float) -> tuple[bool, str]:
        """
        Execute a lightweight upstream reachability/auth check inside the gateway
        container. We run it inside the container so it reflects *container* egress.
        """
        provider_s = str(provider or "").strip().lower()
        if provider_s == "openai":
            url = "https://api.openai.com/v1/models"
            key_env = "OPENAI_API_KEY"
        elif provider_s == "chutes":
            url = "https://llm.chutes.ai/v1/models"
            key_env = "CHUTES_API_KEY"
        else:
            return False, "unknown provider"

        # Keep the inline script short and robust: print status and a short body prefix.
        py = (
            "import os,sys,httpx\n"
            "url=sys.argv[1]; key_env=sys.argv[2]; timeout=float(sys.argv[3])\n"
            "key=(os.getenv(key_env) or '').strip()\n"
            "headers={'Authorization': f'Bearer {key}'} if key else {}\n"
            "try:\n"
            "  r=httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)\n"
            "  body=(r.text or '')[:200].replace('\\n',' ')\n"
            "  print(f'status={r.status_code} body={body}')\n"
            "  sys.exit(0 if r.status_code < 400 else 10)\n"
            "except Exception as e:\n"
            "  print(f'exception={type(e).__name__}: {e}')\n"
            "  sys.exit(20)\n"
        )

        try:
            res = self.gateway_container.exec_run(  # type: ignore[attr-defined]
                ["python", "-c", py, url, key_env, str(timeout_s)],
                stdout=True,
                stderr=True,
            )
            exit_code = getattr(res, "exit_code", None)
            rc = 1 if exit_code is None else int(exit_code)
            out = getattr(res, "output", b"") or b""
            out_s = out.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return False, f"exec_run failed: {type(e).__name__}: {e}"

        if rc == 0:
            return True, out_s or "ok"
        # 4xx/5xx: provider reachable but request failed; treat as hard-fail
        # because it usually indicates missing/invalid keys or wrong endpoint.
        return False, out_s or f"nonzero exit_code={rc}"

    def _get_allowed_gateway_providers(self) -> set[str]:
        allowed = _csv_env("GATEWAY_ALLOWED_PROVIDERS")
        if allowed:
            return allowed
        return set(_PROVIDER_TO_API_KEY_ENV.keys())

    def _validate_gateway_provider_keys(self) -> None:
        allowed_providers = self._get_allowed_gateway_providers()
        unknown = sorted(p for p in allowed_providers if p not in _PROVIDER_TO_API_KEY_ENV)
        if unknown:
            raise RuntimeError(f"Unknown providers in GATEWAY_ALLOWED_PROVIDERS: {', '.join(unknown)}")

        missing_key_envs: list[str] = []
        for provider in sorted(allowed_providers):
            env_name = _PROVIDER_TO_API_KEY_ENV[provider]
            if not (os.getenv(env_name) or "").strip():
                missing_key_envs.append(env_name)

        if missing_key_envs:
            providers = ", ".join(sorted(allowed_providers))
            missing = ", ".join(missing_key_envs)
            raise RuntimeError(f"Missing API keys for allowed gateway providers ({providers}). Set: {missing}")

    def _wait_for_gateway_health(self, timeout: int = 20, retry_interval: float = 1.0) -> bool:
        health_url = f"http://127.0.0.1:{SANDBOX_GATEWAY_PORT}/health"
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                response = httpx.get(health_url, timeout=3.0)
                if response.status_code < 400:
                    return True
            except Exception:
                pass
            time.sleep(retry_interval)
        return False

    def _clone_repo(self, github_url: str) -> str:
        temp_dir = temp_workdir()
        repo_dir = os.path.join(temp_dir, "repo")
        clone_repo(github_url, repo_dir, timeout=SANDBOX_CLONE_TIMEOUT)
        return repo_dir

    def _start_container(self, uid: int, temp_dir: str, *, git_commit: Optional[str] = None) -> AgentInstance:
        container_name = self._agent_container_name(uid, git_commit=git_commit)
        # In normal mode we replace the stable per-uid container name. In debug
        # keep mode we use unique names; cleanup_containers() is harmless no-op.
        cleanup_containers([container_name])

        gateway_url = f"http://{SANDBOX_GATEWAY_HOST}:{SANDBOX_GATEWAY_PORT}"
        env = {
            "SANDBOX_GATEWAY_URL": gateway_url,
            "OPENAI_BASE_URL": f"{gateway_url}/openai/v1",
            "CHUTES_BASE_URL": f"{gateway_url}/chutes/v1",
            "SANDBOX_AGENT_PORT": str(SANDBOX_AGENT_PORT),
            "SANDBOX_AGENT_UID": str(uid),
            # Ensure any `print(...)` diagnostics appear immediately in `docker logs`.
            "PYTHONUNBUFFERED": "1",
        }
        if SANDBOX_AGENT_LOG_ERRORS:
            env["AGENT_LOG_ERRORS"] = "1"
        if SANDBOX_AGENT_LOG_DECISIONS:
            env["AGENT_LOG_DECISIONS"] = "1"
        if SANDBOX_AGENT_RETURN_METRICS:
            env["AGENT_RETURN_METRICS"] = "1"

        # Ensure the nested mountpoint exists inside the bind-mounted repo dir
        # so Docker can mount /app/logs even when /app itself is read-only.
        try:
            os.makedirs(os.path.join(temp_dir, "logs"), exist_ok=True)
        except Exception:
            pass

        labels = {
            "autoppia.sandbox": "true",
            "autoppia.sandbox.kind": "agent",
            "autoppia.sandbox.uid": str(uid),
        }
        if git_commit:
            labels["autoppia.sandbox.commit"] = str(git_commit)
        if self.keep_agent_containers:
            labels["autoppia.sandbox.keep"] = "true"

        run_kwargs = dict(
            image=self.sandbox_image,
            name=container_name,
            volumes={
                # Untrusted code: mount repo read-only.
                temp_dir: {"bind": "/app", "mode": "ro"},
            },
            network=SANDBOX_NETWORK_NAME,
            environment=env,
            labels=labels,
            # Publish on loopback only to avoid exposing miner APIs externally.
            ports={f"{SANDBOX_AGENT_PORT}/tcp": ("127.0.0.1", None)},
            read_only=True,
            # Writable tmpfs locations are size-limited so miners cannot fill host disk.
            tmpfs={
                "/tmp": f"rw,nosuid,nodev,noexec,size={os.getenv('SANDBOX_AGENT_TMPFS_SIZE', '512m')}",
                "/app/logs": f"rw,nosuid,nodev,noexec,size={os.getenv('SANDBOX_AGENT_LOG_TMPFS_SIZE', '64m')}",
            },
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            pids_limit=int(os.getenv("SANDBOX_AGENT_PIDS_LIMIT", "768")),
            mem_limit=os.getenv("SANDBOX_AGENT_MEM_LIMIT", "2g"),
            init=True,
            detach=True,
        )
        log_config = _docker_log_config(kind="agent")
        if log_config is not None:
            run_kwargs["log_config"] = log_config
        nano_cpus = _nano_cpus_from_env("SANDBOX_AGENT_CPU_LIMIT", default=2.0)
        if nano_cpus is not None:
            run_kwargs["nano_cpus"] = nano_cpus

        # Best-effort compatibility: some older Docker daemons may reject NanoCPUs
        # or per-container log config overrides.
        for _ in range(3):
            try:
                container = self.client.containers.run(**run_kwargs)
                break
            except Exception as e:
                msg = str(e)
                if "log" in msg.lower() and "log_config" in run_kwargs:
                    run_kwargs.pop("log_config", None)
                    continue
                if ("nano_cpus" in msg or "NanoCPUs" in msg) and "nano_cpus" in run_kwargs:
                    run_kwargs.pop("nano_cpus", None)
                    continue
                raise
        try:
            container.reload()
        except Exception:
            pass
        return AgentInstance(
            uid=uid,
            container=container,
            temp_dir=temp_dir,
            port=SANDBOX_AGENT_PORT,
            git_commit=git_commit,
        )

    def deploy_agent(self, uid: int, github_url: str) -> Optional[AgentInstance]:
        try:
            bt.logging.info(f"Deploying agent {uid} from {github_url}...")
            if not check_image(self.sandbox_image):
                bt.logging.info("Sandbox agent image not found; building...")
                build_image(self.sandbox_ctx, self.sandbox_image)

            repo_dir = self._clone_repo(github_url)
            bt.logging.info(f"Cloned repo for agent {uid} to {repo_dir}.")

            # Capture the exact commit that will be executed (pins the evaluated code).
            git_commit = None
            try:
                out = subprocess.check_output(
                    ["git", "-C", repo_dir, "rev-parse", "HEAD"],
                    text=True,
                    timeout=5,
                    stderr=subprocess.DEVNULL,
                ).strip()
                if out:
                    git_commit = out
            except Exception:
                git_commit = None

            agent = self._start_container(uid, repo_dir, git_commit=git_commit)
            bt.logging.success(f"Started container for agent {uid} at {agent.base_url}")

            self._agents[uid] = agent

            if self.health_check(agent):
                bt.logging.success(f"Agent {uid} passed health check.")
            else:
                bt.logging.error(f"Agent {uid} failed health check.")
                self.cleanup_agent(uid)
                return None

            return agent
        except Exception as exc:
            bt.logging.error(f"Failed to deploy agent {uid} from {github_url}: {exc}")
            return None

    def health_check(self, agent: AgentInstance, timeout: int = 20) -> bool:
        if not agent or not agent.base_url:
            return False
        url = f"{agent.base_url}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = httpx.get(url, timeout=5.0)
                if resp.status_code < 400:
                    return True
            except Exception:
                pass
            time.sleep(1.0)
        return False

    def cleanup_agent(self, uid: int):
        agent = self._agents.pop(uid, None)
        if not agent:
            return

        if self.keep_agent_containers:
            # Debug/testing: preserve the container + workdir so operators can inspect
            # stdout logs (`docker logs <name>`) and the cloned repo under temp_dir.
            try:
                agent.container.stop(timeout=10)
            except Exception:
                pass
            try:
                bt.logging.warning(f"[sandbox] Preserving agent container for uid={uid}: name={getattr(agent.container, 'name', '')} temp_dir={agent.temp_dir}")
            except Exception:
                pass
            return

        stop_and_remove(agent.container)
        try:
            shutil.rmtree(agent.temp_dir, ignore_errors=True)
        except Exception:
            pass
        # Best-effort container garbage collection so validators don't accumulate
        # stopped/created intermediates over time.
        try:
            garbage_collect_stale_containers()
        except Exception:
            pass

    def cleanup_all_agents(self):
        for uid in list(self._agents.keys()):
            self.cleanup_agent(uid)

    def _gateway_admin_headers(self) -> dict:
        return {"X-Admin-Token": str(self.gateway_admin_token)}

    def set_allowed_task_ids(self, task_ids: list[str]) -> bool:
        try:
            gateway_url = f"http://localhost:{SANDBOX_GATEWAY_PORT}"
            resp = httpx.post(
                f"{gateway_url}/set-allowed-task-ids",
                headers=self._gateway_admin_headers(),
                json={"task_ids": task_ids},
                timeout=5.0,
            )
            if resp.status_code == 200:
                return True
            bt.logging.error(f"Gateway set-allowed-task-ids failed: status={resp.status_code} body={resp.text[:300]}")
        except Exception as e:
            bt.logging.error(f"Gateway set-allowed-task-ids request failed: {e}")
            return False
        return False

    def get_usage_for_task(self, task_id: str) -> Optional[dict]:
        try:
            gateway_url = f"http://localhost:{SANDBOX_GATEWAY_PORT}"
            resp = httpx.get(
                f"{gateway_url}/usage/{task_id}",
                headers=self._gateway_admin_headers(),
                timeout=5.0,
            )
            if resp.status_code == 200:
                return resp.json()
            bt.logging.error(f"Gateway usage lookup failed for task_id={task_id}: status={resp.status_code} body={resp.text[:300]}")
        except Exception as e:
            bt.logging.error(f"Gateway usage lookup request failed for task_id={task_id}: {e}")
            return None
        return None
