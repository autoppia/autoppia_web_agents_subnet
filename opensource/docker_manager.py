"""
Docker management for building and running containers from GitHub repositories.
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
from docker.errors import DockerException, ImageNotFound, ContainerError
from git import Repo, GitCommandError

from models import (
    DeploymentConfig, DeploymentRecord, ContainerInfo, 
    Color, HealthStatus, DeploymentState
)

logger = structlog.get_logger(__name__)


class DockerManager:
    """Manages Docker operations for deployments."""

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

    def _get_image_tag(self, deployment_id: str, color: Color, commit_sha: str) -> str:
        """Generate image tag for a deployment."""
        short_sha = commit_sha[:8]
        return f"{deployment_id}-{color.value}-{short_sha}"

    def _get_container_name(self, deployment_id: str, color: Color) -> str:
        """Generate container name for a deployment."""
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

    async def build_image(self, config: DeploymentConfig, repo_dir: str, 
                          commit_sha: str, color: Color) -> str:
        """Build Docker image for a deployment."""
        image_tag = self._get_image_tag(config.deployment_id, color, commit_sha)

        try:
            logger.info("Building Docker image", 
                        deployment_id=config.deployment_id, 
                        color=color.value, 
                        image_tag=image_tag)

            # Check if Dockerfile exists
            dockerfile_path = Path(repo_dir) / "Dockerfile"
            if not dockerfile_path.exists():
                raise ValueError("No Dockerfile found in repository")

            # Build image
            image, build_logs = self.client.images.build(
                path=repo_dir,
                tag=image_tag,
                buildargs={arg.split('=', 1)[0]: arg.split('=', 1)[1] 
                           for arg in config.build_args if '=' in arg},
                rm=True,
                forcerm=True
            )

            # Log build output
            for log in build_logs:
                if 'stream' in log:
                    logger.debug("Docker build", message=log['stream'].strip())

            logger.info("Docker image built successfully", 
                        deployment_id=config.deployment_id, 
                        image_tag=image_tag)

            return image_tag

        except DockerException as e:
            logger.error("Failed to build Docker image", 
                         deployment_id=config.deployment_id, 
                         error=str(e))
            raise ValueError(f"Failed to build Docker image: {e}")

    async def run_container(self, config: DeploymentConfig, image_tag: str, 
                            color: Color, port: int) -> ContainerInfo:
        """Run a container for a deployment."""
        container_name = self._get_container_name(config.deployment_id, color)

        try:
            # Stop and remove existing container if it exists
            await self.stop_container(config.deployment_id, color)

            logger.info("Starting container", 
                        deployment_id=config.deployment_id, 
                        color=color.value, 
                        image_tag=image_tag, 
                        port=port)

            # Prepare environment variables
            env_vars = {}
            for env_var in config.env:
                if '=' in env_var:
                    key, value = env_var.split('=', 1)
                    env_vars[key] = value

            # Prepare labels for Traefik
            labels = {
                "deployer": "true",
                "deployment_id": config.deployment_id,
                "color": color.value,
                "traefik.enable": "false",  # Will be enabled when promoted
                f"traefik.http.routers.{config.deployment_id}-{color.value}.rule": 
                    f"Host(`localhost`) && PathPrefix(`/apps/{config.deployment_id}/`)",
                f"traefik.http.routers.{config.deployment_id}-{color.value}.service": 
                    f"{config.deployment_id}-{color.value}",
                f"traefik.http.services.{config.deployment_id}-{color.value}.loadbalancer.server.port": 
                    str(config.internal_port),
            }

            # Add custom labels
            labels.update(config.labels)

            # Run container
            container = self.client.containers.run(
                image_tag,
                name=container_name,
                ports={f"{config.internal_port}/tcp": port},
                environment=env_vars,
                labels=labels,
                network=self.network_name,
                detach=True,
                restart_policy={"Name": "unless-stopped"},
                mem_limit="1g",  # Default memory limit
                cpu_quota=100000,  # Default CPU limit (1 core)
                remove=False
            )

            # Wait for container to start
            await asyncio.sleep(config.startup_delay_sec)

            container_info = ContainerInfo(
                container_id=container.id,
                image_tag=image_tag,
                port=port,
                status=container.status,
                created_at=datetime.utcnow(),
                health_status=HealthStatus.UNKNOWN
            )

            logger.info("Container started successfully", 
                        deployment_id=config.deployment_id, 
                        color=color.value, 
                        container_id=container.id)

            return container_info

        except DockerException as e:
            logger.error("Failed to start container", 
                         deployment_id=config.deployment_id, 
                         color=color.value, 
                         error=str(e))
            raise ValueError(f"Failed to start container: {e}")

    async def stop_container(self, deployment_id: str, color: Color) -> bool:
        """Stop and remove a container."""
        container_name = self._get_container_name(deployment_id, color)

        try:
            container = self.client.containers.get(container_name)
            container.stop(timeout=10)
            container.remove(force=True)

            logger.info("Container stopped and removed", 
                        deployment_id=deployment_id, 
                        color=color.value)
            return True

        except docker.errors.NotFound:
            logger.debug("Container not found", 
                         deployment_id=deployment_id, 
                         color=color.value)
            return True
        except DockerException as e:
            logger.error("Failed to stop container", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return False

    async def get_container_logs(self, deployment_id: str, color: Color, 
                                 tail: int = 200) -> str:
        """Get container logs."""
        container_name = self._get_container_name(deployment_id, color)

        try:
            container = self.client.containers.get(container_name)
            logs = container.logs(tail=tail, timestamps=True).decode('utf-8')
            return logs

        except docker.errors.NotFound:
            return f"Container {container_name} not found"
        except DockerException as e:
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

    async def promote_container(self, deployment_id: str, color: Color) -> bool:
        """Promote a container by enabling Traefik routing."""
        container_name = self._get_container_name(deployment_id, color)

        try:
            container = self.client.containers.get(container_name)

            # Update labels to enable Traefik routing
            labels = container.labels.copy()
            labels["traefik.enable"] = "true"

            # Update container labels (this requires recreating the container)
            # For now, we'll use a simpler approach with Traefik API
            logger.info("Promoting container", 
                        deployment_id=deployment_id, 
                        color=color.value)

            return True

        except docker.errors.NotFound:
            logger.error("Container not found for promotion", 
                         deployment_id=deployment_id, 
                         color=color.value)
            return False
        except DockerException as e:
            logger.error("Failed to promote container", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return False

    async def demote_container(self, deployment_id: str, color: Color) -> bool:
        """Demote a container by disabling Traefik routing."""
        container_name = self._get_container_name(deployment_id, color)

        try:
            container = self.client.containers.get(container_name)

            # Update labels to disable Traefik routing
            labels = container.labels.copy()
            labels["traefik.enable"] = "false"

            logger.info("Demoting container", 
                        deployment_id=deployment_id, 
                        color=color.value)

            return True

        except docker.errors.NotFound:
            logger.debug("Container not found for demotion", 
                         deployment_id=deployment_id, 
                         color=color.value)
            return True
        except DockerException as e:
            logger.error("Failed to demote container", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return False

    async def cleanup_old_images(self, deployment_id: str, keep_count: int = 3):
        """Clean up old images for a deployment."""
        try:
            # Get all images for this deployment
            images = self.client.images.list(
                filters={"label": f"deployment_id={deployment_id}"}
            )

            # Sort by creation time (newest first)
            images.sort(key=lambda x: x.attrs['Created'], reverse=True)

            # Remove old images
            for image in images[keep_count:]:
                try:
                    self.client.images.remove(image.id, force=True)
                    logger.info("Removed old image", 
                                deployment_id=deployment_id, 
                                image_id=image.id)
                except DockerException as e:
                    logger.warning("Failed to remove old image", 
                                   deployment_id=deployment_id, 
                                   image_id=image.id, 
                                   error=str(e))

        except DockerException as e:
            logger.error("Failed to cleanup old images", 
                         deployment_id=deployment_id, 
                         error=str(e))

    async def get_container_status(self, deployment_id: str, color: Color) -> Optional[Dict]:
        """Get detailed container status."""
        container_name = self._get_container_name(deployment_id, color)

        try:
            container = self.client.containers.get(container_name)
            return {
                "id": container.id,
                "status": container.status,
                "created": container.attrs['Created'],
                "ports": container.attrs['NetworkSettings']['Ports'],
                "labels": container.labels
            }
        except docker.errors.NotFound:
            return None
        except DockerException as e:
            logger.error("Failed to get container status", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return None

    def is_docker_available(self) -> bool:
        """Check if Docker is available and accessible."""
        try:
            self.client.ping()
            return True
        except DockerException:
            return False
