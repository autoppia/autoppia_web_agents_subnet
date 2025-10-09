"""
Traefik proxy management for dynamic routing.
"""
import asyncio
from typing import Dict, List, Optional

import httpx
import structlog

from models import DeploymentRecord, Color

logger = structlog.get_logger(__name__)


class TraefikManager:
    """Manages Traefik proxy configuration for deployments."""

    def __init__(self, traefik_api_url: str = "http://traefik:8080"):
        self.traefik_api_url = traefik_api_url.rstrip('/')
        self.providers_url = f"{self.traefik_api_url}/api/http/routers"
        self.services_url = f"{self.traefik_api_url}/api/http/services"
        self.middlewares_url = f"{self.traefik_api_url}/api/http/middlewares"

    async def is_traefik_available(self) -> bool:
        """Check if Traefik API is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.traefik_api_url}/api/rawdata")
                return response.status_code == 200
        except Exception as e:
            logger.warning("Traefik API not available", error=str(e))
            return False

    async def get_routers(self) -> List[Dict]:
        """Get all Traefik routers."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.providers_url)
                if response.status_code == 200:
                    return response.json()
                return []
        except Exception as e:
            logger.error("Failed to get Traefik routers", error=str(e))
            return []

    async def get_services(self) -> List[Dict]:
        """Get all Traefik services."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.services_url)
                if response.status_code == 200:
                    return response.json()
                return []
        except Exception as e:
            logger.error("Failed to get Traefik services", error=str(e))
            return []

    async def create_router(self, deployment_id: str, color: Color, 
                            port: int, host: str = "localhost") -> bool:
        """Create a Traefik router for a deployment."""
        router_name = f"{deployment_id}-{color.value}"
        service_name = f"{deployment_id}-{color.value}"

        router_config = {
            "name": router_name,
            "rule": f"Host(`{host}`) && PathPrefix(`/apps/{deployment_id}/`)",
            "service": service_name,
            "middlewares": [f"{deployment_id}-strip-prefix"],
            "priority": 100
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Create strip prefix middleware
                middleware_config = {
                    "name": f"{deployment_id}-strip-prefix",
                    "stripPrefix": {
                        "prefixes": [f"/apps/{deployment_id}"]
                    }
                }

                response = await client.post(
                    self.middlewares_url,
                    json=middleware_config
                )

                if response.status_code not in [200, 201]:
                    logger.warning("Failed to create middleware", 
                                   deployment_id=deployment_id, 
                                   status_code=response.status_code)

                # Create service
                service_config = {
                    "name": service_name,
                    "loadBalancer": {
                        "servers": [
                            {
                                "url": f"http://{deployment_id}-{color.value}:{port}"
                            }
                        ]
                    }
                }

                response = await client.post(
                    self.services_url,
                    json=service_config
                )

                if response.status_code not in [200, 201]:
                    logger.error("Failed to create service", 
                                 deployment_id=deployment_id, 
                                 color=color.value, 
                                 status_code=response.status_code)
                    return False

                # Create router
                response = await client.post(
                    self.providers_url,
                    json=router_config
                )

                if response.status_code in [200, 201]:
                    logger.info("Created Traefik router", 
                                deployment_id=deployment_id, 
                                color=color.value)
                    return True
                else:
                    logger.error("Failed to create router", 
                                 deployment_id=deployment_id, 
                                 color=color.value, 
                                 status_code=response.status_code)
                    return False

        except Exception as e:
            logger.error("Failed to create Traefik configuration", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return False

    async def delete_router(self, deployment_id: str, color: Color) -> bool:
        """Delete a Traefik router for a deployment."""
        router_name = f"{deployment_id}-{color.value}"
        service_name = f"{deployment_id}-{color.value}"
        middleware_name = f"{deployment_id}-strip-prefix"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Delete router
                response = await client.delete(f"{self.providers_url}/{router_name}")
                if response.status_code not in [200, 204, 404]:
                    logger.warning("Failed to delete router", 
                                   deployment_id=deployment_id, 
                                   color=color.value, 
                                   status_code=response.status_code)

                # Delete service
                response = await client.delete(f"{self.services_url}/{service_name}")
                if response.status_code not in [200, 204, 404]:
                    logger.warning("Failed to delete service", 
                                   deployment_id=deployment_id, 
                                   color=color.value, 
                                   status_code=response.status_code)

                # Delete middleware
                response = await client.delete(f"{self.middlewares_url}/{middleware_name}")
                if response.status_code not in [200, 204, 404]:
                    logger.warning("Failed to delete middleware", 
                                   deployment_id=deployment_id, 
                                   status_code=response.status_code)

                logger.info("Deleted Traefik configuration", 
                            deployment_id=deployment_id, 
                            color=color.value)
                return True

        except Exception as e:
            logger.error("Failed to delete Traefik configuration", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return False

    async def update_router_priority(self, deployment_id: str, color: Color, 
                                     priority: int) -> bool:
        """Update router priority to control traffic routing."""
        router_name = f"{deployment_id}-{color.value}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get current router config
                response = await client.get(f"{self.providers_url}/{router_name}")
                if response.status_code != 200:
                    logger.error("Router not found", 
                                 deployment_id=deployment_id, 
                                 color=color.value)
                    return False

                router_config = response.json()
                router_config["priority"] = priority

                # Update router
                response = await client.put(
                    f"{self.providers_url}/{router_name}",
                    json=router_config
                )

                if response.status_code in [200, 201]:
                    logger.info("Updated router priority", 
                                deployment_id=deployment_id, 
                                color=color.value, 
                                priority=priority)
                    return True
                else:
                    logger.error("Failed to update router priority", 
                                 deployment_id=deployment_id, 
                                 color=color.value, 
                                 status_code=response.status_code)
                    return False

        except Exception as e:
            logger.error("Failed to update router priority", 
                         deployment_id=deployment_id, 
                         color=color.value, 
                         error=str(e))
            return False

    async def promote_deployment(self, deployment: DeploymentRecord) -> bool:
        """Promote a deployment by updating Traefik routing."""
        deployment_id = deployment.config.deployment_id
        active_color = deployment.active_color
        inactive_color = Color.GREEN if active_color == Color.BLUE else Color.BLUE

        try:
            # Set high priority for active color (traffic goes here)
            active_success = await self.update_router_priority(
                deployment_id, active_color, 100
            )

            # Set low priority for inactive color (no traffic)
            inactive_success = await self.update_router_priority(
                deployment_id, inactive_color, 1
            )

            if active_success and inactive_success:
                logger.info("Promoted deployment", 
                            deployment_id=deployment_id, 
                            active_color=active_color.value)
                return True
            else:
                logger.error("Failed to promote deployment", 
                             deployment_id=deployment_id)
                return False

        except Exception as e:
            logger.error("Failed to promote deployment", 
                         deployment_id=deployment_id, 
                         error=str(e))
            return False

    async def switch_deployment(self, deployment: DeploymentRecord, 
                                new_color: Color) -> bool:
        """Switch deployment to a different color."""
        deployment_id = deployment.config.deployment_id
        old_color = deployment.active_color

        try:
            # Set low priority for old color
            old_success = await self.update_router_priority(
                deployment_id, old_color, 1
            )

            # Set high priority for new color
            new_success = await self.update_router_priority(
                deployment_id, new_color, 100
            )

            if old_success and new_success:
                logger.info("Switched deployment", 
                            deployment_id=deployment_id, 
                            from_color=old_color.value, 
                            to_color=new_color.value)
                return True
            else:
                logger.error("Failed to switch deployment", 
                             deployment_id=deployment_id)
                return False

        except Exception as e:
            logger.error("Failed to switch deployment", 
                         deployment_id=deployment_id, 
                         error=str(e))
            return False

    async def get_deployment_routing_status(self, deployment_id: str) -> Dict:
        """Get routing status for a deployment."""
        try:
            routers = await self.get_routers()
            services = await self.get_services()

            status = {
                "deployment_id": deployment_id,
                "routers": {},
                "services": {}
            }

            # Find routers and services for this deployment
            for router in routers:
                if router.get("name", "").startswith(f"{deployment_id}-"):
                    color = router["name"].split("-")[-1]
                    status["routers"][color] = {
                        "name": router["name"],
                        "rule": router.get("rule", ""),
                        "priority": router.get("priority", 0),
                        "service": router.get("service", "")
                    }

            for service in services:
                if service.get("name", "").startswith(f"{deployment_id}-"):
                    color = service["name"].split("-")[-1]
                    status["services"][color] = {
                        "name": service["name"],
                        "servers": service.get("loadBalancer", {}).get("servers", [])
                    }

            return status

        except Exception as e:
            logger.error("Failed to get routing status", 
                         deployment_id=deployment_id, 
                         error=str(e))
            return {"deployment_id": deployment_id, "error": str(e)}

    async def cleanup_deployment_routing(self, deployment_id: str) -> bool:
        """Clean up all routing configuration for a deployment."""
        try:
            success = True

            # Delete both blue and green configurations
            for color in [Color.BLUE, Color.GREEN]:
                if not await self.delete_router(deployment_id, color):
                    success = False

            if success:
                logger.info("Cleaned up deployment routing", 
                            deployment_id=deployment_id)
            else:
                logger.warning("Partial cleanup of deployment routing", 
                               deployment_id=deployment_id)

            return success

        except Exception as e:
            logger.error("Failed to cleanup deployment routing", 
                         deployment_id=deployment_id, 
                         error=str(e))
            return False
