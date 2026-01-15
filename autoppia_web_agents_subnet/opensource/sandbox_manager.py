from __future__ import annotations

import os
import shutil
import time
from typing import Dict, Optional

import httpx

from autoppia_web_agents_subnet.opensource.utils_docker import (
    build_image,
    cleanup_containers,
    clone_repo,
    ensure_network,
    get_client,
    stop_and_remove,
    temp_workdir,
)
from autoppia_web_agents_subnet.utils.logging import ColoredLogger

SANDBOX_NETWORK_NAME = os.getenv("SANDBOX_NETWORK_NAME", "sandbox-network")
SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "autoppia-sandbox-image")
SANDBOX_PROXY_IMAGE = os.getenv("SANDBOX_PROXY_IMAGE", "autoppia-sandbox-proxy-image")
SANDBOX_PROXY_HOST = os.getenv("SANDBOX_PROXY_HOST", "sandbox_proxy")
SANDBOX_PROXY_PORT = int(os.getenv("SANDBOX_PROXY_PORT", "80"))
SANDBOX_AGENT_PORT = int(os.getenv("SANDBOX_AGENT_PORT", "8000"))
SANDBOX_AGENT_START_CMD = os.getenv(
    "SANDBOX_AGENT_START_CMD",
    # Default start command assumes the sandbox image already contains all
    # allowed dependencies; we do NOT install miner-provided requirements.txt
    # at runtime for security reasons.
    "cd /sandbox/repo && uvicorn api:app --host 0.0.0.0 --port {port}",
)
SANDBOX_CLONE_TIMEOUT = int(os.getenv("SANDBOX_CLONE_TIMEOUT", "90"))
SANDBOX_PROXY_TARGET = os.getenv("SANDBOX_PROXY_TARGET", "http://127.0.0.1:9")


class AgentInstance:
    def __init__(self, uid: int, container, temp_dir: str, port: int):
        self.uid = uid
        self.container = container
        self.temp_dir = temp_dir
        self.port = port

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
    Lightweight runtime to clone miner repos and serve them in isolated containers.
    """

    def __init__(self):
        self.client = get_client()
        ensure_network(SANDBOX_NETWORK_NAME, internal=True)
        self._ensure_proxy()
        self._agents: Dict[int, AgentInstance] = {}

    def _ensure_proxy(self):
        try:
            self.client.images.get(SANDBOX_PROXY_IMAGE)
        except Exception:
            proxy_ctx = os.path.join(os.path.dirname(__file__), "proxy")
            build_image(proxy_ctx, SANDBOX_PROXY_IMAGE)

        cleanup_containers([SANDBOX_PROXY_HOST])
        env = {
            "GATEWAY_URL": SANDBOX_PROXY_TARGET,
            "GATEWAY_HOST": SANDBOX_PROXY_TARGET.split("://")[-1].split("/")[0],
        }
        self.proxy_container = self.client.containers.run(
            name=SANDBOX_PROXY_HOST,
            image=SANDBOX_PROXY_IMAGE,
            network=SANDBOX_NETWORK_NAME,
            environment=env,
            detach=True,
        )
        # Attach to default bridge for egress
        try:
            bridge = self.client.networks.get("bridge")
            bridge.connect(self.proxy_container)
        except Exception:
            pass

    def _ensure_base_image(self):
        try:
            self.client.images.get(SANDBOX_IMAGE)
        except Exception:
            ctx = os.path.dirname(__file__)
            build_image(ctx, SANDBOX_IMAGE)

    def _clone_repo(self, github_url: str) -> str:
        temp_dir = temp_workdir()
        repo_dir = os.path.join(temp_dir, "repo")
        clone_repo(github_url, repo_dir, timeout=SANDBOX_CLONE_TIMEOUT)
        return temp_dir

    def _start_container(self, uid: int, temp_dir: str) -> AgentInstance:
        cmd = SANDBOX_AGENT_START_CMD.format(port=SANDBOX_AGENT_PORT)
        proxy_url = f"http://{SANDBOX_PROXY_HOST}:{SANDBOX_PROXY_PORT}"
        env = {
            "SANDBOX_PROXY_URL": proxy_url,
            "SANDBOX_AGENT_PORT": str(SANDBOX_AGENT_PORT),
            # Standard proxy envs so HTTP clients (including the OpenAI SDK)
            # automatically route through the sandbox proxy when needed.
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
        }
        # Propagate OpenAI configuration into the sandbox so agents can
        # optionally use the IWA OpenAI LLM helpers without baking secrets
        # into the image.
        for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_TEMPERATURE", "OPENAI_MAX_TOKENS"):
            val = os.getenv(key)
            if val:
                env[key] = val
        container = self.client.containers.run(
            image=SANDBOX_IMAGE,
            name=f"sandbox-agent-{uid}",
            volumes={temp_dir: {"bind": "/sandbox", "mode": "rw"}},
            network=SANDBOX_NETWORK_NAME,
            environment=env,
            # Expose the agent port on the host so tests/validator can reach
            # it, while keeping the container itself on the internal sandbox
            # network (no direct internet access; all outbound traffic must
            # go through SANDBOX_PROXY_URL).
            ports={f"{SANDBOX_AGENT_PORT}/tcp": None},
            command=["/bin/sh", "-c", cmd],
            detach=True,
        )
        # Refresh attrs so base_url sees the host port mapping.
        try:
            container.reload()
        except Exception:
            pass
        return AgentInstance(uid=uid, container=container, temp_dir=temp_dir, port=SANDBOX_AGENT_PORT)

    def deploy_agent(self, uid: int, github_url: str) -> Optional[AgentInstance]:
        self._ensure_base_image()
        try:
            temp_dir = self._clone_repo(github_url)
            agent = self._start_container(uid, temp_dir)
            self._agents[uid] = agent
            return agent
        except Exception as exc:
            ColoredLogger.error(f"Failed to deploy agent {uid} from {github_url}: {exc}", ColoredLogger.RED)
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
        stop_and_remove(agent.container)
        try:
            shutil.rmtree(agent.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def cleanup_all_agents(self):
        for uid in list(self._agents.keys()):
            self.cleanup_agent(uid)
