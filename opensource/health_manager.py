"""
Health check management for blue/green deployments.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx
import structlog

from models import (
    DeploymentRecord, Color, HealthStatus, DeploymentState
)

logger = structlog.get_logger(__name__)


class HealthManager:
    """Manages health checks for deployments."""

    def __init__(self):
        self._health_checks: Dict[str, asyncio.Task] = {}
        self._stop_event = asyncio.Event()

    async def start_health_monitoring(self, deployment: DeploymentRecord):
        """Start continuous health monitoring for a deployment."""
        deployment_id = deployment.config.deployment_id

        # Stop existing health check if running
        await self.stop_health_monitoring(deployment_id)

        # Start new health check task
        task = asyncio.create_task(
            self._health_check_loop(deployment_id)
        )
        self._health_checks[deployment_id] = task

        logger.info("Started health monitoring", deployment_id=deployment_id)

    async def stop_health_monitoring(self, deployment_id: str):
        """Stop health monitoring for a deployment."""
        if deployment_id in self._health_checks:
            task = self._health_checks[deployment_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._health_checks[deployment_id]

            logger.info("Stopped health monitoring", deployment_id=deployment_id)

    async def _health_check_loop(self, deployment_id: str):
        """Continuous health check loop for a deployment."""
        while not self._stop_event.is_set():
            try:
                # This would need access to the state manager
                # For now, we'll implement the health check logic
                await asyncio.sleep(10)  # Check every 10 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check loop error", 
                             deployment_id=deployment_id, 
                             error=str(e))
                await asyncio.sleep(30)  # Wait longer on error

    async def perform_health_check(self, deployment: DeploymentRecord, 
                                   color: Optional[Color] = None,
                                   timeout_sec: Optional[int] = None) -> Tuple[bool, str]:
        """Perform a single health check on a deployment."""
        if color is None:
            color = deployment.active_color

        # Get container info for the specified color
        container_info = None
        if color == Color.BLUE and deployment.blue_container:
            container_info = deployment.blue_container
        elif color == Color.GREEN and deployment.green_container:
            container_info = deployment.green_container

        if not container_info:
            return False, f"No {color.value} container found"

        if not deployment.ports:
            return False, "No port allocation found"

        port = deployment.ports.blue_port if color == Color.BLUE else deployment.ports.green_port
        timeout = timeout_sec or deployment.config.probe_timeout_sec

        return await self._check_container_health(
            deployment.config, port, timeout
        )

    async def _check_container_health(self, config, port: int, 
                                      timeout_sec: int) -> Tuple[bool, str]:
        """Check health of a specific container."""
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
        except httpx.ConnectError:
            return False, "Connection refused - container may not be running"
        except Exception as e:
            return False, f"Health check error: {e}"

    async def wait_for_healthy(self, deployment: DeploymentRecord, 
                               color: Color, max_wait_sec: int = 120) -> Tuple[bool, str]:
        """Wait for a container to become healthy."""
        start_time = datetime.utcnow()
        check_interval = 1  # Check every second

        while (datetime.utcnow() - start_time).total_seconds() < max_wait_sec:
            healthy, message = await self.perform_health_check(deployment, color)

            if healthy:
                return True, message

            await asyncio.sleep(check_interval)

        return False, f"Container did not become healthy within {max_wait_sec}s"

    async def validate_deployment_health(self, deployment: DeploymentRecord) -> bool:
        """Validate that the active deployment is healthy."""
        if deployment.state not in [DeploymentState.HEALTHY, DeploymentState.PROMOTED]:
            return False

        healthy, _ = await self.perform_health_check(deployment, deployment.active_color)
        return healthy

    async def get_health_summary(self, deployment: DeploymentRecord) -> Dict:
        """Get comprehensive health summary for a deployment."""
        summary = {
            "deployment_id": deployment.config.deployment_id,
            "overall_health": deployment.health_status.value,
            "active_color": deployment.active_color.value,
            "containers": {}
        }

        # Check blue container
        if deployment.blue_container:
            healthy, message = await self.perform_health_check(deployment, Color.BLUE)
            summary["containers"]["blue"] = {
                "status": "healthy" if healthy else "unhealthy",
                "message": message,
                "container_id": deployment.blue_container.container_id,
                "port": deployment.ports.blue_port if deployment.ports else None,
                "last_check": deployment.blue_container.last_health_check.isoformat() 
                if deployment.blue_container.last_health_check else None
            }

        # Check green container
        if deployment.green_container:
            healthy, message = await self.perform_health_check(deployment, Color.GREEN)
            summary["containers"]["green"] = {
                "status": "healthy" if healthy else "unhealthy",
                "message": message,
                "container_id": deployment.green_container.container_id,
                "port": deployment.ports.green_port if deployment.ports else None,
                "last_check": deployment.green_container.last_health_check.isoformat() 
                if deployment.green_container.last_health_check else None
            }

        return summary

    async def batch_health_check(self, deployments: List[DeploymentRecord]) -> Dict[str, Dict]:
        """Perform health checks on multiple deployments in parallel."""
        tasks = []
        deployment_ids = []

        for deployment in deployments:
            if deployment.state in [DeploymentState.HEALTHY, DeploymentState.PROMOTED]:
                tasks.append(self.get_health_summary(deployment))
                deployment_ids.append(deployment.config.deployment_id)

        if not tasks:
            return {}

        results = await asyncio.gather(*tasks, return_exceptions=True)

        summary = {}
        for deployment_id, result in zip(deployment_ids, results):
            if isinstance(result, Exception):
                summary[deployment_id] = {
                    "error": str(result),
                    "status": "error"
                }
            else:
                summary[deployment_id] = result

        return summary

    async def shutdown(self):
        """Shutdown health manager and stop all monitoring."""
        self._stop_event.set()

        # Cancel all health check tasks
        for task in self._health_checks.values():
            task.cancel()

        # Wait for all tasks to complete
        if self._health_checks:
            await asyncio.gather(*self._health_checks.values(), return_exceptions=True)

        self._health_checks.clear()
        logger.info("Health manager shutdown complete")
