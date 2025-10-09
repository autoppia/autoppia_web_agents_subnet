"""
Miner deployment manager that uses docker-compose from miner repositories.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import docker
import structlog
from docker.errors import DockerException
from git import Repo, GitCommandError

from models import (
    DeploymentConfig, DeploymentRecord, ContainerInfo, 
    Color, HealthStatus, DeploymentState
)

logger = structlog.get_logger(__name__)


class MinerDeploymentManager:
    """Manages deployment of miner agents using their docker-compose files."""

    def __init__(self, work_dir: str = "/srv/deployer/work", network_name: str = "deployer_network"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.network_name = network_name
        self.client = docker.from_env()

        # Ensure network exists
        self._ensure_network()

    def _ensure_network(self):
        """Ensure the Docker network exists."""
        try:
            self.client.networks.get(self.network_name)
        except docker.errors.NotFound:
            logger.info("Creating Docker network", network=self.network_name)
            self.client.networks.create(
                self.network_name,
                driver="bridge",
                labels={"deployer": "true"}
            )

    def _get_repo_dir(self, deployment_id: str) -> Path:
        """Get the working directory for a deployment."""
        return self.work_dir / deployment_id

    def _get_compose_project_name(self, deployment_id: str, color: Color) -> str:
        """Generate docker-compose project name."""
        return f"{deployment_id}-{color.value}"

    async def clone_repository(self, config: DeploymentConfig) -> Tuple[str, str]:
        """Clone repository and return commit SHA and working directory."""
        repo_dir = self._get_repo_dir(config.deployment_id)

        # Clean up existing directory
        if repo_dir.exists():
            shutil.rmtree(repo_dir)

        try:
            logger.info("Cloning repository", 
                        deployment_id=config.deployment_id, 
                        repo_url=config.repo_url, 
                        branch=config.branch)

            # Clone repository
            repo = Repo.clone_from(config.repo_url, repo_dir, branch=config.branch)
            commit_sha = repo.head.commit.hexsha

            # Checkout specific subdirectory if specified
            if config.subdir:
                subdir_path = repo_dir / config.subdir
                if not subdir_path.exists():
                    raise ValueError(f"Subdirectory '{config.subdir}' not found in repository")

                # Move subdirectory contents to root
                temp_dir = repo_dir / "temp"
                shutil.move(str(subdir_path), str(temp_dir))
                shutil.rmtree(repo_dir)
                shutil.move(str(temp_dir), str(repo_dir))

            logger.info("Repository cloned successfully", 
                        deployment_id=config.deployment_id, 
                        commit_sha=commit_sha)

            return commit_sha, str(repo_dir)

        except GitCommandError as e:
            logger.error("Failed to clone repository", 
                         deployment_id=config.deployment_id, 
                         error=str(e))
            raise ValueError(f"Failed to clone repository: {e}")

    async def validate_miner_repository(self, repo_dir: str) -> Dict[str, bool]:
        """Validate that the repository follows the miner standard."""
        validation_results = {
            "docker_compose_exists": False,
            "agent_service_exists": False,
            "agent_dockerfile_exists": False,
            "agent_main_exists": False,
            "agent_requirements_exists": False,
            "readme_exists": False,
            "port_8000_exposed": False,
            "health_check_configured": False,
            "autoppia_labels_present": False,
            "deployer_network_used": False
        }

        try:
            repo_path = Path(repo_dir)

            # Check docker-compose.yml exists
            compose_file = repo_path / "docker-compose.yml"
            validation_results["docker_compose_exists"] = compose_file.exists()

            if not validation_results["docker_compose_exists"]:
                logger.warning("docker-compose.yml not found", repo_dir=repo_dir)
                return validation_results

            # Parse docker-compose.yml
            import yaml
            with open(compose_file, 'r') as f:
                compose_config = yaml.safe_load(f)

            services = compose_config.get('services', {})

            # Check agent service exists
            validation_results["agent_service_exists"] = 'agent' in services
            if not validation_results["agent_service_exists"]:
                logger.warning("Agent service not found in docker-compose.yml", repo_dir=repo_dir)
                return validation_results

            agent_service = services['agent']

            # Check port 8000 is exposed
            ports = agent_service.get('ports', [])
            for port_mapping in ports:
                if isinstance(port_mapping, str) and '8000:8000' in port_mapping:
                    validation_results["port_8000_exposed"] = True
                    break
                elif isinstance(port_mapping, dict) and port_mapping.get('target') == 8000:
                    validation_results["port_8000_exposed"] = True
                    break

            # Check health check is configured
            validation_results["health_check_configured"] = 'healthcheck' in agent_service

            # Check labels
            labels = agent_service.get('labels', [])
            autoppia_labels = [label for label in labels if 'autoppia.miner=true' in label]
            validation_results["autoppia_labels_present"] = len(autoppia_labels) > 0

            # Check network
            networks = agent_service.get('networks', [])
            if isinstance(networks, list):
                validation_results["deployer_network_used"] = self.network_name in networks
            elif isinstance(networks, dict):
                validation_results["deployer_network_used"] = self.network_name in networks.values()

            # Check agent directory structure
            agent_dir = repo_path / "agent"
            validation_results["agent_dockerfile_exists"] = (agent_dir / "Dockerfile").exists()
            validation_results["agent_main_exists"] = (agent_dir / "main.py").exists()
            validation_results["agent_requirements_exists"] = (agent_dir / "requirements.txt").exists()

            # Check README
            validation_results["readme_exists"] = (repo_path / "README.md").exists()

            logger.info("Repository validation completed", 
                        deployment_id=repo_path.name,
                        results=validation_results)

        except Exception as e:
            logger.error("Failed to validate repository", repo_dir=repo_dir, error=str(e))

        return validation_results

    async def deploy_with_docker_compose(self, config: DeploymentConfig, 
                                         repo_dir: str, color: Color, 
                                         port: int) -> ContainerInfo:
        """Deploy using docker-compose from the repository."""
        project_name = self._get_compose_project_name(config.deployment_id, color)

        try:
            # Stop existing deployment if it exists
            await self.stop_docker_compose_deployment(config.deployment_id, color)

            logger.info("Deploying with docker-compose", 
                        deployment_id=config.deployment_id, 
                        color=color.value, 
                        project_name=project_name,
                        port=port)

            # Create environment file for this deployment
            env_file = Path(repo_dir) / f".env.{color.value}"
            with open(env_file, 'w') as f:
                f.write(f"AGENT_NAME={config.deployment_id}\n")
                f.write(f"AGENT_VERSION=1.0.0\n")
                f.write(f"GITHUB_URL={config.repo_url}\n")
                f.write(f"HAS_RL=false\n")
                f.write(f"LOG_LEVEL=INFO\n")
                # Add custom environment variables
                for env_var in config.env:
                    f.write(f"{env_var}\n")

            # Modify docker-compose.yml to use the correct port
            compose_file = Path(repo_dir) / "docker-compose.yml"
            await self._modify_compose_for_deployment(compose_file, port, color)

            # Run docker-compose up
            cmd = [
                "docker-compose",
                "-p", project_name,
                "-f", str(compose_file),
                "--env-file", str(env_file),
                "up", "-d", "--build"
            ]

            result = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )

            if result.returncode != 0:
                logger.error("Docker-compose deployment failed", 
                             deployment_id=config.deployment_id,
                             error=result.stderr)
                raise RuntimeError(f"Docker-compose failed: {result.stderr}")

            # Wait for container to start
            await asyncio.sleep(config.startup_delay_sec)

            # Get container information
            container_info = await self._get_container_info_from_compose(project_name, port)

            logger.info("Docker-compose deployment successful", 
                        deployment_id=config.deployment_id, 
                        color=color.value, 
                        container_id=container_info.container_id)

            return container_info

        except subprocess.TimeoutExpired:
            logger.error("Docker-compose deployment timeout", 
                         deployment_id=config.deployment_id)
            raise RuntimeError("Docker-compose deployment timed out")
        except Exception as e:
            logger.error("Failed to deploy with docker-compose", 
                         deployment_id=config.deployment_id, 
                         color=color.value, 
                         error=str(e))
            raise ValueError(f"Failed to deploy with docker-compose: {e}")

    async def _modify_compose_for_deployment(self, compose_file: Path, port: int, color: Color):
        """Modify docker-compose.yml for deployment."""
        import yaml

        try:
            with open(compose_file, 'r') as f:
                compose_config = yaml.safe_load(f)

            # Update agent service
            if 'services' in compose_config and 'agent' in compose_config['services']:
                agent_service = compose_config['services']['agent']

                # Update port mapping
                agent_service['ports'] = [f"{port}:8000"]

                # Update container name
                agent_service['container_name'] = f"autoppia-miner-{color.value}"

                # Ensure correct network
                agent_service['networks'] = [self.network_name]

                # Add deployment-specific labels
                labels = agent_service.get('labels', [])
                labels.extend([
                    f"deployment.color={color.value}",
                    f"deployment.timestamp={datetime.utcnow().isoformat()}"
                ])
                agent_service['labels'] = labels

            # Update networks section
            compose_config['networks'] = {
                self.network_name: {
                    'external': True,
                    'name': self.network_name
                }
            }

            # Write back to file
            with open(compose_file, 'w') as f:
                yaml.dump(compose_config, f, default_flow_style=False)

        except Exception as e:
            logger.error("Failed to modify docker-compose.yml", 
                         compose_file=str(compose_file), 
                         error=str(e))
            raise e

    async def _get_container_info_from_compose(self, project_name: str, port: int) -> ContainerInfo:
        """Get container information from docker-compose project."""
        try:
            # Get containers for this project
            containers = self.client.containers.list(
                filters={"label": f"com.docker.compose.project={project_name}"}
            )

            if not containers:
                raise RuntimeError(f"No containers found for project {project_name}")

            # Find the agent container
            agent_container = None
            for container in containers:
                if 'agent' in container.name:
                    agent_container = container
                    break

            if not agent_container:
                raise RuntimeError(f"Agent container not found in project {project_name}")

            # Get image tag
            image_tag = agent_container.image.tags[0] if agent_container.image.tags else "unknown"

            container_info = ContainerInfo(
                container_id=agent_container.id,
                image_tag=image_tag,
                port=port,
                status=agent_container.status,
                created_at=datetime.utcnow(),
                health_status=HealthStatus.UNKNOWN
            )

            return container_info

        except Exception as e:
            logger.error("Failed to get container info from compose", 
                         project_name=project_name, 
                         error=str(e))
            raise e

    async def stop_docker_compose_deployment(self, deployment_id: str, color: Color) -> bool:
        """Stop docker-compose deployment."""
        project_name = self._get_compose_project_name(deployment_id, color)

        try:
            # Get repository directory
            repo_dir = self._get_repo_dir(deployment_id)
            if not repo_dir.exists():
                return True

            compose_file = repo_dir / "docker-compose.yml"
            if not compose_file.exists():
                return True

            logger.info("Stopping docker-compose deployment", 
                        deployment_id=deployment_id, 
                        color=color.value,
                        project_name=project_name)

            # Run docker-compose down
            cmd = [
                "docker-compose",
                "-p", project_name,
                "-f", str(compose_file),
                "down", "-v", "--remove-orphans"
            ]

            result = subprocess.run(
                cmd,
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=60  # 1 minute timeout
            )

            if result.returncode != 0:
                logger.warning("Docker-compose stop failed", 
                               deployment_id=deployment_id,
                               error=result.stderr)
                return False

            logger.info("Docker-compose deployment stopped", 
                        deployment_id=deployment_id, 
                        color=color.value)
            return True

        except subprocess.TimeoutExpired:
            logger.error("Docker-compose stop timeout", 
                         deployment_id=deployment_id)
            return False
        except Exception as e:
            logger.error("Failed to stop docker-compose deployment", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return False

    async def get_container_logs(self, deployment_id: str, color: Color, 
                                 tail: int = 200) -> str:
        """Get container logs from docker-compose deployment."""
        project_name = self._get_compose_project_name(deployment_id, color)

        try:
            # Get containers for this project
            containers = self.client.containers.list(
                filters={"label": f"com.docker.compose.project={project_name}"}
            )

            if not containers:
                return f"No containers found for project {project_name}"

            # Find the agent container
            agent_container = None
            for container in containers:
                if 'agent' in container.name:
                    agent_container = container
                    break

            if not agent_container:
                return f"Agent container not found in project {project_name}"

            logs = agent_container.logs(tail=tail, timestamps=True).decode('utf-8')
            return logs

        except Exception as e:
            logger.error("Failed to get container logs", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return f"Error getting logs: {e}"

    async def health_check(self, config: DeploymentConfig, port: int, 
                           timeout_sec: int = 30) -> Tuple[bool, str]:
        """Perform health check on a container."""
        import httpx

        health_url = f"http://localhost:{port}{config.health_path}"

        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                response = await client.get(health_url)

                if response.status_code == config.expected_status:
                    return True, f"Health check passed: {response.status_code}"
                else:
                    return False, f"Health check failed: expected {config.expected_status}, got {response.status_code}"

        except httpx.TimeoutException:
            return False, f"Health check timeout after {timeout_sec}s"
        except Exception as e:
            return False, f"Health check error: {e}"

    def is_docker_available(self) -> bool:
        """Check if Docker is available and accessible."""
        try:
            self.client.ping()
            return True
        except DockerException:
            return False

    def is_docker_compose_available(self) -> bool:
        """Check if docker-compose is available."""
        try:
            result = subprocess.run(
                ["docker-compose", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
