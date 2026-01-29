from __future__ import annotations

import os
import shutil
import time
from typing import Dict, Optional

import httpx
import bittensor as bt

from autoppia_web_agents_subnet.opensource.sandbox.utils_docker import (
    check_image,
    build_image,
    cleanup_containers,
    clone_repo,
    ensure_network,
    get_client,
    stop_and_remove,
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
)


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
    Lightweight runtime to clone miner repos and serve them in isolated containers
    with LLM usage tracking and cost management via FastAPI gateway.
    """

    def __init__(self):
        self.client = get_client()
        ensure_network(SANDBOX_NETWORK_NAME, internal=True)
        self._ensure_gateway()
        self._agents: Dict[int, AgentInstance] = {}

    def _ensure_gateway(self):
        if not check_image(SANDBOX_GATEWAY_IMAGE):
            bt.logging.info("Sandbox gateway image not found; building...")
            gateway_ctx = os.path.join(os.path.dirname(__file__), "..", "gateway")
            build_image(gateway_ctx, SANDBOX_GATEWAY_IMAGE)

        cleanup_containers([SANDBOX_GATEWAY_HOST])
        env = {
            "COST_LIMIT_ENABLED": os.getenv("COST_LIMIT_ENABLED", "true"),
            "COST_LIMIT_VALUE": os.getenv("COST_LIMIT_VALUE", "10.0"),
            "SANDBOX_GATEWAY_PORT": str(SANDBOX_GATEWAY_PORT),
        }
        # Propagate API keys to the gateway
        for key in ("OPENAI_API_KEY", "CHUTES_API_KEY"):
            val = os.getenv(key)
            if val:
                env[key] = val
                
        self.gateway_container = self.client.containers.run(
            name=SANDBOX_GATEWAY_HOST,
            image=SANDBOX_GATEWAY_IMAGE,
            network=SANDBOX_NETWORK_NAME,
            environment=env,
            ports = {
                f"{SANDBOX_GATEWAY_PORT}/tcp": ("127.0.0.1", SANDBOX_GATEWAY_PORT)
            },
            detach=True,
        )
        # Attach to default bridge for egress
        try:
            bridge = self.client.networks.get("bridge")
            bridge.connect(self.gateway_container)
        except Exception:
            pass

    def _clone_repo(self, github_url: str) -> str:
        temp_dir = temp_workdir()
        repo_dir = os.path.join(temp_dir, "repo")
        clone_repo(github_url, repo_dir, timeout=SANDBOX_CLONE_TIMEOUT)
        return repo_dir

    def _start_container(self, uid: int, temp_dir: str) -> AgentInstance:
        cleanup_containers([f"sandbox-agent-{uid}"])

        gateway_url = f"http://{SANDBOX_GATEWAY_HOST}:{SANDBOX_GATEWAY_PORT}"
        env = {
            "SANDBOX_GATEWAY_URL": gateway_url,
            "SANDBOX_AGENT_PORT": str(SANDBOX_AGENT_PORT),
            "HTTP_PROXY": gateway_url,
            "HTTPS_PROXY": gateway_url,
            "SANDBOX_AGENT_UID": str(uid),
        }
        container = self.client.containers.run(
            image=SANDBOX_AGENT_IMAGE,
            name=f"sandbox-agent-{uid}",
            volumes={temp_dir: {"bind": "/sandbox", "mode": "rw"}},
            network=SANDBOX_NETWORK_NAME,
            environment=env,
            ports={f"{SANDBOX_AGENT_PORT}/tcp": None},
            detach=True,
        )
        try:
            container.reload()
        except Exception:
            pass
        return AgentInstance(uid=uid, container=container, temp_dir=temp_dir, port=SANDBOX_AGENT_PORT)

    def deploy_agent(self, uid: int, github_url: str) -> Optional[AgentInstance]:
        try:
            bt.logging.info(f"Deploying agent {uid} from {github_url}...")

            repo_dir = self._clone_repo(github_url)
            bt.logging.info(f"Cloned repo for agent {uid} to {repo_dir}. Now building image...")

            build_image(repo_dir, SANDBOX_AGENT_IMAGE)
            bt.logging.info(f"Built image for agent {uid}. Now starting container...")

            agent = self._start_container(uid, repo_dir)
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
        stop_and_remove(agent.container)
        try:
            shutil.rmtree(agent.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def cleanup_all_agents(self):
        for uid in list(self._agents.keys()):
            self.cleanup_agent(uid)

    def reset_usage(self) -> bool:
        try:
            gateway_url = f"http://localhost:{SANDBOX_GATEWAY_PORT}"
            resp = httpx.post(f"{gateway_url}/reset", timeout=5.0)
            if resp.status_code == 200:
                return True
        except Exception as e:
            return False
        return False
