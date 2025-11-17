from __future__ import annotations

import asyncio
from pathlib import Path

from autoppia_web_agents_subnet.utils.logging import ColoredLogger

agents_deployment_dir = Path("/tmp/autoppia_web_agents")
agents_deployment_dir.mkdir(parents=True, exist_ok=True)

async def run_cmd(cmd, env=None, cwd=None):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env={**(env or {})},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        print(f"❌ {' '.join(cmd)} failed:\n{stderr.decode()}")
    else:
        print(stdout.decode())

async def _deploy_single_agent(uid: int, github_url: str) -> str:
    """
    Deploys a single agent from a GitHub URL.
    """
    agent_dir = agents_deployment_dir / f"web_agent_{uid}"

    ColoredLogger.info(f"📦 Deploying agent {uid} from {github_url} to {agent_dir}")
    await run_cmd(["git", "clone", github_url, agent_dir])
    
    compose_file = agent_dir / "docker-compose.yml"
    if not compose_file.exists():
        ColoredLogger.error(f"❌ Compose file not found: {compose_file}")
        return ""

    env = {
        "PORT": f"{9000 + uid}",
    }
    await run_cmd(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "--build"], 
        env=env, 
        cwd=agent_dir
    )
    ColoredLogger.info(f"✅ Agent {uid} deployed successfully at http://localhost:{9000 + uid}")
    return uid, f"http://localhost:{9000 + uid}"

async def deploy_all_agents(github_urls: dict[int, str]) -> dict[int, str]:
    """
    Deploys all agents from a dictionary of GitHub URLs.
    """
    await _clean_up_all_agents()
    endpoints = await asyncio.gather(
        *[_deploy_single_agent(uid, github_url) for uid, github_url in github_urls.items()]
    )
    return {uid: endpoint for uid, endpoint in endpoints}

async def _clean_up_all_agents() -> None:
    """
    Cleans up all agents from the deployment directory.
    """
    ColoredLogger.info(f"📦 Cleaning up all agents from {agents_deployment_dir}")
    compose_files = [
        agent_dir / "docker-compose.yml" 
        for agent_dir in agents_deployment_dir.iterdir() 
        if agent_dir.is_dir()
        and (agent_dir / "docker-compose.yml").exists()
    ]
    await asyncio.gather(
        *[run_cmd(["docker", "compose", "-f", str(compose_file), "down", "-v"]) for compose_file in compose_files]
    )
    await run_cmd(["rm", "-rf", "*"], cwd=agents_deployment_dir)
    ColoredLogger.info(f"✅ All agents cleaned up successfully")