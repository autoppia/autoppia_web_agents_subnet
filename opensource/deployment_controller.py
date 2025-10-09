"""
Main deployment controller with blue/green deployment logic.
"""
import asyncio
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from models import (
    DeploymentRecord, DeploymentConfig, DeploymentState, Color, 
    HealthStatus, CreateDeploymentRequest, RedeployRequest, SwitchRequest
)
from state_manager import StateManager
from docker_manager import DockerManager
from miner_deployment_manager import MinerDeploymentManager
from health_manager import HealthManager
from traefik_manager import TraefikManager

logger = structlog.get_logger(__name__)


class DeploymentController:
    """Main controller for managing deployments."""

    def __init__(self, 
                 state_dir: str = "/srv/deployer/state",
                 work_dir: str = "/srv/deployer/work",
                 network_name: str = "deployer_network",
                 traefik_api_url: str = "http://traefik:8080"):

        self.state_manager = StateManager(state_dir)
        self.docker_manager = DockerManager(work_dir, network_name)
        self.miner_deployment_manager = MinerDeploymentManager(work_dir, network_name)
        self.health_manager = HealthManager()
        self.traefik_manager = TraefikManager(traefik_api_url)

        self.start_time = time.time()
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize the deployment controller."""
        logger.info("Initializing deployment controller")

        # Check Docker availability
        if not self.docker_manager.is_docker_available():
            raise RuntimeError("Docker is not available")

        # Check docker-compose availability
        if not self.miner_deployment_manager.is_docker_compose_available():
            raise RuntimeError("Docker Compose is not available")

        # Check Traefik availability
        if not await self.traefik_manager.is_traefik_available():
            logger.warning("Traefik is not available - deployments will not be routable")

        # Start health monitoring for existing deployments
        deployments = self.state_manager.list_deployments()
        for deployment in deployments:
            if deployment.state in [DeploymentState.HEALTHY, DeploymentState.PROMOTED]:
                await self.health_manager.start_health_monitoring(deployment)

        logger.info("Deployment controller initialized", 
                    active_deployments=len(deployments))

    async def create_deployment(self, request: CreateDeploymentRequest) -> DeploymentRecord:
        """Create a new deployment."""
        deployment_id = request.deployment_id

        # Check if deployment already exists
        existing = self.state_manager.get_deployment(deployment_id)
        if existing and not request.force_redeploy:
            raise ValueError(f"Deployment {deployment_id} already exists")

        # Allocate ports
        ports = self.state_manager.allocate_ports()
        if not ports:
            raise RuntimeError("No available ports for deployment")

        try:
            # Create deployment configuration
            config = DeploymentConfig(
                deployment_id=deployment_id,
                repo_url=request.repo_url,
                branch=request.branch,
                subdir=request.subdir,
                health_path=request.health_path,
                expected_status=request.expected_status,
                internal_port=request.internal_port,
                env=request.env,
                build_args=request.build_args,
                probe_timeout_sec=request.probe_timeout_sec,
                grace_sec=request.grace_sec,
                startup_delay_sec=request.startup_delay_sec,
                labels=request.labels
            )

            # Create deployment record
            deployment = DeploymentRecord(
                config=config,
                state=DeploymentState.IDLE,
                active_color=Color.BLUE,
                ports=ports
            )

            # Save deployment
            if not self.state_manager.create_deployment(deployment):
                raise RuntimeError("Failed to create deployment record")

            # Start deployment process
            await self._deploy_to_color(deployment, Color.BLUE)

            return deployment

        except Exception as e:
            # Clean up on failure
            if ports:
                self.state_manager.free_ports(ports)
            self.state_manager.delete_deployment(deployment_id)
            raise e

    async def redeploy(self, deployment_id: str, request: RedeployRequest) -> DeploymentRecord:
        """Redeploy an existing deployment."""
        deployment = self.state_manager.get_deployment(deployment_id)
        if not deployment:
            raise ValueError(f"Deployment {deployment_id} not found")

        # Check if deployment is locked
        if deployment.operation_in_progress:
            raise RuntimeError(f"Deployment {deployment_id} is currently busy")

        # Lock deployment
        if not self.state_manager.lock_deployment(deployment_id, "redeploy"):
            raise RuntimeError("Failed to lock deployment")

        try:
            # Update configuration if provided
            if request.branch:
                deployment.config.branch = request.branch
            if request.env:
                deployment.config.env = request.env
            if request.build_args:
                deployment.config.build_args = request.build_args

            # Determine inactive color
            inactive_color = Color.GREEN if deployment.active_color == Color.BLUE else Color.BLUE

            # Deploy to inactive color
            await self._deploy_to_color(deployment, inactive_color)

            # Promote if successful
            if deployment.state == DeploymentState.HEALTHY:
                await self._promote_deployment(deployment, inactive_color)

            return deployment

        finally:
            self.state_manager.unlock_deployment(deployment_id, deployment.state == DeploymentState.PROMOTED)

    async def switch_deployment(self, deployment_id: str, request: SwitchRequest) -> DeploymentRecord:
        """Switch deployment between blue/green."""
        deployment = self.state_manager.get_deployment(deployment_id)
        if not deployment:
            raise ValueError(f"Deployment {deployment_id} not found")

        if deployment.active_color == request.color:
            logger.info("Deployment already on requested color", 
                        deployment_id=deployment_id, 
                        color=request.color.value)
            return deployment

        # Check if target color container exists and is healthy
        target_container = None
        if request.color == Color.BLUE and deployment.blue_container:
            target_container = deployment.blue_container
        elif request.color == Color.GREEN and deployment.green_container:
            target_container = deployment.green_container

        if not target_container:
            raise ValueError(f"No {request.color.value} container found")

        # Perform health check unless forced
        if not request.force:
            healthy, message = await self.health_manager.perform_health_check(deployment, request.color)
            if not healthy:
                raise RuntimeError(f"Target container is not healthy: {message}")

        # Switch deployment
        await self._switch_deployment(deployment, request.color)

        return deployment

    async def delete_deployment(self, deployment_id: str, keep_images: bool = False) -> bool:
        """Delete a deployment."""
        deployment = self.state_manager.get_deployment(deployment_id)
        if not deployment:
            return False

        # Lock deployment
        if not self.state_manager.lock_deployment(deployment_id, "delete"):
            return False

        try:
            # Stop health monitoring
            await self.health_manager.stop_health_monitoring(deployment_id)

            # Stop containers
            await self.miner_deployment_manager.stop_docker_compose_deployment(deployment_id, Color.BLUE)
            await self.miner_deployment_manager.stop_docker_compose_deployment(deployment_id, Color.GREEN)

            # Clean up Traefik routing
            await self.traefik_manager.cleanup_deployment_routing(deployment_id)

            # Clean up old images unless keeping them
            if not keep_images:
                await self.docker_manager.cleanup_old_images(deployment_id)

            # Free ports
            if deployment.ports:
                self.state_manager.free_ports(deployment.ports)

            # Delete deployment record
            success = self.state_manager.delete_deployment(deployment_id)

            if success:
                logger.info("Deleted deployment", deployment_id=deployment_id)

            return success

        finally:
            self.state_manager.unlock_deployment(deployment_id, True)

    async def _deploy_to_color(self, deployment: DeploymentRecord, color: Color):
        """Deploy to a specific color (blue or green)."""
        deployment_id = deployment.config.deployment_id

        try:
            # Update state
            self.state_manager.update_deployment(
                deployment_id, 
                state=DeploymentState.BUILDING
            )
            deployment.add_event("build_started", f"Building {color.value} container")

            # Clone repository
            commit_sha, repo_dir = await self.miner_deployment_manager.clone_repository(deployment.config)

            # Validate miner repository structure
            validation_results = await self.miner_deployment_manager.validate_miner_repository(repo_dir)
            deployment.add_event("validation_completed", f"Repository validation: {validation_results}")

            # Check if validation passed
            required_checks = [
                "docker_compose_exists", "agent_service_exists", "port_8000_exposed",
                "health_check_configured", "autoppia_labels_present", "deployer_network_used"
            ]

            failed_checks = [check for check in required_checks if not validation_results.get(check, False)]
            if failed_checks:
                raise ValueError(f"Repository validation failed: {failed_checks}")

            # Get port for this color
            port = deployment.ports.blue_port if color == Color.BLUE else deployment.ports.green_port

            # Deploy using docker-compose
            container_info = await self.miner_deployment_manager.deploy_with_docker_compose(
                deployment.config, repo_dir, color, port
            )

            # Update deployment with container info
            if color == Color.BLUE:
                self.state_manager.update_deployment(
                    deployment_id,
                    blue_container=container_info,
                    last_commit=commit_sha,
                    image_tag=image_tag,
                    last_deploy_at=datetime.utcnow(),
                    state=DeploymentState.STAGING
                )
            else:
                self.state_manager.update_deployment(
                    deployment_id,
                    green_container=container_info,
                    last_commit=commit_sha,
                    image_tag=image_tag,
                    last_deploy_at=datetime.utcnow(),
                    state=DeploymentState.STAGING
                )

            deployment.add_event("container_started", f"{color.value} container started")

            # Wait for health check
            healthy, message = await self.miner_deployment_manager.health_check(
                deployment.config, port, deployment.config.probe_timeout_sec
            )

            if healthy:
                self.state_manager.update_deployment(
                    deployment_id,
                    state=DeploymentState.HEALTHY,
                    health_status=HealthStatus.HEALTHY
                )
                deployment.add_event("health_check_passed", f"{color.value} container is healthy")
            else:
                self.state_manager.update_deployment(
                    deployment_id,
                    state=DeploymentState.FAILED,
                    health_status=HealthStatus.UNHEALTHY
                )
                deployment.add_event("health_check_failed", f"{color.value} container failed: {message}")
                raise RuntimeError(f"Health check failed: {message}")

        except Exception as e:
            self.state_manager.update_deployment(
                deployment_id,
                state=DeploymentState.FAILED,
                health_status=HealthStatus.UNHEALTHY
            )
            deployment.add_event("deployment_failed", f"{color.value} deployment failed: {str(e)}")
            raise e

    async def _promote_deployment(self, deployment: DeploymentRecord, new_color: Color):
        """Promote a deployment to active."""
        deployment_id = deployment.config.deployment_id
        old_color = deployment.active_color

        try:
            # Create Traefik routing for new color
            port = deployment.ports.blue_port if new_color == Color.BLUE else deployment.ports.green_port
            await self.traefik_manager.create_router(deployment_id, new_color, port)

            # Promote in Traefik
            await self.traefik_manager.promote_deployment(deployment)

            # Update deployment state
            self.state_manager.update_deployment(
                deployment_id,
                active_color=new_color,
                state=DeploymentState.PROMOTED
            )

            deployment.add_event("promoted", f"Promoted to {new_color.value}")

            # Start health monitoring
            await self.health_manager.start_health_monitoring(deployment)

            # Schedule retirement of old container
            asyncio.create_task(self._retire_old_container(deployment, old_color))

        except Exception as e:
            deployment.add_event("promotion_failed", f"Failed to promote: {str(e)}")
            raise e

    async def _switch_deployment(self, deployment: DeploymentRecord, new_color: Color):
        """Switch deployment to a different color."""
        deployment_id = deployment.config.deployment_id
        old_color = deployment.active_color

        try:
            # Switch in Traefik
            await self.traefik_manager.switch_deployment(deployment, new_color)

            # Update deployment state
            self.state_manager.update_deployment(
                deployment_id,
                active_color=new_color
            )

            deployment.add_event("switched", f"Switched from {old_color.value} to {new_color.value}")

        except Exception as e:
            deployment.add_event("switch_failed", f"Failed to switch: {str(e)}")
            raise e

    async def _retire_old_container(self, deployment: DeploymentRecord, old_color: Color):
        """Retire old container after grace period."""
        deployment_id = deployment.config.deployment_id

        # Wait for grace period
        await asyncio.sleep(deployment.config.grace_sec)

        try:
            # Stop old container
            await self.docker_manager.stop_container(deployment_id, old_color)

            # Clean up Traefik routing for old color
            await self.traefik_manager.delete_router(deployment_id, old_color)

            # Update deployment state
            if old_color == Color.BLUE:
                self.state_manager.update_deployment(
                    deployment_id,
                    blue_container=None,
                    state=DeploymentState.RETIRED_OLD
                )
            else:
                self.state_manager.update_deployment(
                    deployment_id,
                    green_container=None,
                    state=DeploymentState.RETIRED_OLD
                )

            deployment.add_event("retired", f"Retired {old_color.value} container")

        except Exception as e:
            logger.error("Failed to retire old container", 
                         deployment_id=deployment_id, 
                         color=old_color.value, 
                         error=str(e))

    async def get_deployment_status(self, deployment_id: str) -> Optional[Dict]:
        """Get deployment status."""
        deployment = self.state_manager.get_deployment(deployment_id)
        if not deployment:
            return None

        return await self.health_manager.get_health_summary(deployment)

    async def get_all_deployments_status(self) -> List[Dict]:
        """Get status of all deployments."""
        deployments = self.state_manager.list_deployments()
        return await self.health_manager.batch_health_check(deployments)

    async def get_deployment_logs(self, deployment_id: str, color: Optional[Color] = None, 
                                  tail: int = 200) -> str:
        """Get deployment logs."""
        deployment = self.state_manager.get_deployment(deployment_id)
        if not deployment:
            return f"Deployment {deployment_id} not found"

        if color is None:
            color = deployment.active_color

        return await self.miner_deployment_manager.get_container_logs(deployment_id, color, tail)

    async def get_controller_health(self) -> Dict:
        """Get controller health status."""
        stats = self.state_manager.get_deployment_stats()

        return {
            "status": "healthy",
            "version": "1.0.0",
            "docker_connected": self.docker_manager.is_docker_available(),
            "traefik_connected": await self.traefik_manager.is_traefik_available(),
            "active_deployments": stats["active"],
            "total_deployments": stats["total"],
            "building_deployments": stats["building"],
            "failed_deployments": stats["failed"],
            "locked_deployments": stats["locked"],
            "uptime_seconds": time.time() - self.start_time,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def shutdown(self):
        """Shutdown the deployment controller."""
        logger.info("Shutting down deployment controller")

        # Signal shutdown
        self._shutdown_event.set()

        # Stop health monitoring
        await self.health_manager.shutdown()

        # Stop all deployments
        deployments = self.state_manager.list_deployments()
        for deployment in deployments:
            try:
                await self.delete_deployment(deployment.config.deployment_id)
            except Exception as e:
                logger.error("Failed to cleanup deployment during shutdown", 
                             deployment_id=deployment.config.deployment_id, 
                             error=str(e))

        logger.info("Deployment controller shutdown complete")
