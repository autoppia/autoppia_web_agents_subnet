"""
Integration layer for connecting the deployment controller with the validator for agent evaluation.
"""
import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import httpx
import structlog

from models import DeploymentRecord, Color, HealthStatus
from deployment_controller import DeploymentController

logger = structlog.get_logger(__name__)


class AgentEvaluator:
    """Evaluates miner agents using their GitHub code instead of deployed endpoints."""

    def __init__(self, 
                 deployment_controller: DeploymentController,
                 validator_base_url: str = "http://localhost:8001",
                 evaluation_timeout: int = 300):

        self.deployment_controller = deployment_controller
        self.validator_base_url = validator_base_url.rstrip('/')
        self.evaluation_timeout = evaluation_timeout

        # Track active evaluations
        self.active_evaluations: Dict[str, Dict] = {}

    async def evaluate_miner_agent(self, 
                                   miner_github_url: str,
                                   miner_branch: str = "main",
                                   task_prompt: str = "",
                                   task_url: str = "",
                                   evaluation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Evaluate a miner agent using their GitHub code.

        This method:
        1. Deploys the miner's GitHub repository
        2. Sends evaluation tasks to the deployed agent
        3. Collects and returns evaluation results
        """
        if not evaluation_id:
            evaluation_id = f"eval_{int(time.time())}"

        try:
            logger.info("Starting agent evaluation", 
                        evaluation_id=evaluation_id,
                        github_url=miner_github_url,
                        branch=miner_branch)

            # Track evaluation
            self.active_evaluations[evaluation_id] = {
                "started_at": datetime.utcnow(),
                "github_url": miner_github_url,
                "branch": miner_branch,
                "status": "deploying"
            }

            # Step 1: Deploy the miner's repository
            deployment_id = f"miner_{evaluation_id}"
            deployment = await self._deploy_miner_repository(
                deployment_id, miner_github_url, miner_branch
            )

            if not deployment:
                raise RuntimeError("Failed to deploy miner repository")

            # Step 2: Wait for deployment to be healthy
            await self._wait_for_deployment_healthy(deployment_id)

            # Step 3: Send evaluation tasks
            evaluation_results = await self._send_evaluation_tasks(
                deployment_id, task_prompt, task_url
            )

            # Step 4: Clean up deployment
            await self._cleanup_evaluation_deployment(deployment_id)

            # Update evaluation status
            self.active_evaluations[evaluation_id].update({
                "status": "completed",
                "completed_at": datetime.utcnow(),
                "results": evaluation_results
            })

            logger.info("Agent evaluation completed", 
                        evaluation_id=evaluation_id,
                        results=evaluation_results)

            return {
                "evaluation_id": evaluation_id,
                "status": "completed",
                "deployment_id": deployment_id,
                "results": evaluation_results,
                "started_at": self.active_evaluations[evaluation_id]["started_at"].isoformat(),
                "completed_at": self.active_evaluations[evaluation_id]["completed_at"].isoformat()
            }

        except Exception as e:
            logger.error("Agent evaluation failed", 
                         evaluation_id=evaluation_id, 
                         error=str(e))

            # Update evaluation status
            if evaluation_id in self.active_evaluations:
                self.active_evaluations[evaluation_id].update({
                    "status": "failed",
                    "error": str(e),
                    "failed_at": datetime.utcnow()
                })

            # Clean up on failure
            try:
                await self._cleanup_evaluation_deployment(f"miner_{evaluation_id}")
            except Exception:
                pass

            raise e

    async def _deploy_miner_repository(self, 
                                       deployment_id: str, 
                                       github_url: str, 
                                       branch: str) -> Optional[DeploymentRecord]:
        """Deploy a miner's GitHub repository."""
        try:
            from models import CreateDeploymentRequest

            # Create deployment request
            request = CreateDeploymentRequest(
                deployment_id=deployment_id,
                repo_url=github_url,
                branch=branch,
                health_path="/health",  # Common health check path
                internal_port=8000,     # Common port for web services
                env=[],                 # No additional environment variables
                build_args=[],          # No additional build arguments
                probe_timeout_sec=120,  # 2 minutes for health check
                grace_sec=30,           # 30 seconds grace period
                startup_delay_sec=5,    # 5 seconds startup delay
                force_redeploy=True     # Force redeploy if exists
            )

            # Deploy using the deployment controller
            deployment = await self.deployment_controller.create_deployment(request)

            logger.info("Miner repository deployed", 
                        deployment_id=deployment_id,
                        state=deployment.state)

            return deployment

        except Exception as e:
            logger.error("Failed to deploy miner repository", 
                         deployment_id=deployment_id, 
                         error=str(e))
            return None

    async def _wait_for_deployment_healthy(self, deployment_id: str, timeout: int = 300):
        """Wait for deployment to become healthy."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                status = await self.deployment_controller.get_deployment_status(deployment_id)

                if status and status.get("overall_health") == "healthy":
                    logger.info("Deployment is healthy", deployment_id=deployment_id)
                    return

                await asyncio.sleep(5)  # Check every 5 seconds

            except Exception as e:
                logger.warning("Error checking deployment health", 
                               deployment_id=deployment_id, 
                               error=str(e))
                await asyncio.sleep(5)

        raise TimeoutError(f"Deployment {deployment_id} did not become healthy within {timeout}s")

    async def _send_evaluation_tasks(self, 
                                     deployment_id: str, 
                                     task_prompt: str, 
                                     task_url: str) -> Dict[str, Any]:
        """Send evaluation tasks to the deployed agent."""
        try:
            # Get deployment status to find the public URL
            status = await self.deployment_controller.get_deployment_status(deployment_id)
            if not status:
                raise RuntimeError(f"Deployment {deployment_id} not found")

            public_url = f"http://localhost:80/apps/{deployment_id}/"

            # Prepare evaluation task
            evaluation_task = {
                "prompt": task_prompt or "Please perform a simple web interaction task",
                "url": task_url or "https://example.com",
                "html": "",
                "screenshot": "",
                "actions": [],
                "version": "1.0.0"
            }

            # Send task to the deployed agent
            async with httpx.AsyncClient(timeout=self.evaluation_timeout) as client:
                response = await client.post(
                    f"{public_url}/api/task",
                    json=evaluation_task
                )

                if response.status_code == 200:
                    result = response.json()

                    # Extract evaluation metrics
                    evaluation_results = {
                        "task_completed": True,
                        "response_time": result.get("execution_time", 0),
                        "actions_generated": len(result.get("actions", [])),
                        "success": result.get("success", False),
                        "error": result.get("error"),
                        "raw_response": result
                    }

                    logger.info("Evaluation task completed", 
                                deployment_id=deployment_id,
                                results=evaluation_results)

                    return evaluation_results
                else:
                    raise RuntimeError(f"Agent returned status {response.status_code}: {response.text}")

        except httpx.TimeoutException:
            raise TimeoutError(f"Evaluation task timed out after {self.evaluation_timeout}s")
        except Exception as e:
            logger.error("Failed to send evaluation task", 
                         deployment_id=deployment_id, 
                         error=str(e))
            raise e

    async def _cleanup_evaluation_deployment(self, deployment_id: str):
        """Clean up evaluation deployment."""
        try:
            success = await self.deployment_controller.delete_deployment(
                deployment_id, 
                keep_images=False  # Don't keep images for evaluations
            )

            if success:
                logger.info("Evaluation deployment cleaned up", deployment_id=deployment_id)
            else:
                logger.warning("Failed to clean up evaluation deployment", 
                               deployment_id=deployment_id)

        except Exception as e:
            logger.error("Error cleaning up evaluation deployment", 
                         deployment_id=deployment_id, 
                         error=str(e))

    async def batch_evaluate_miners(self, 
                                    miner_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluate multiple miners in parallel."""
        tasks = []

        for i, config in enumerate(miner_configs):
            evaluation_id = f"batch_{int(time.time())}_{i}"
            task = asyncio.create_task(
                self.evaluate_miner_agent(
                    miner_github_url=config["github_url"],
                    miner_branch=config.get("branch", "main"),
                    task_prompt=config.get("task_prompt", ""),
                    task_url=config.get("task_url", ""),
                    evaluation_id=evaluation_id
                )
            )
            tasks.append((evaluation_id, task))

        # Wait for all evaluations to complete
        results = {}
        for evaluation_id, task in tasks:
            try:
                result = await task
                results[evaluation_id] = result
            except Exception as e:
                results[evaluation_id] = {
                    "evaluation_id": evaluation_id,
                    "status": "failed",
                    "error": str(e)
                }

        return {
            "batch_id": f"batch_{int(time.time())}",
            "total_evaluations": len(miner_configs),
            "completed": len([r for r in results.values() if r.get("status") == "completed"]),
            "failed": len([r for r in results.values() if r.get("status") == "failed"]),
            "results": results
        }

    async def get_evaluation_status(self, evaluation_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an evaluation."""
        return self.active_evaluations.get(evaluation_id)

    async def list_active_evaluations(self) -> List[Dict[str, Any]]:
        """List all active evaluations."""
        return list(self.active_evaluations.values())

    async def cancel_evaluation(self, evaluation_id: str) -> bool:
        """Cancel an active evaluation."""
        if evaluation_id not in self.active_evaluations:
            return False

        try:
            # Update status
            self.active_evaluations[evaluation_id].update({
                "status": "cancelled",
                "cancelled_at": datetime.utcnow()
            })

            # Clean up deployment
            deployment_id = f"miner_{evaluation_id}"
            await self._cleanup_evaluation_deployment(deployment_id)

            logger.info("Evaluation cancelled", evaluation_id=evaluation_id)
            return True

        except Exception as e:
            logger.error("Failed to cancel evaluation", 
                         evaluation_id=evaluation_id, 
                         error=str(e))
            return False


class ValidatorIntegration:
    """Integration with the Autoppia validator system."""

    def __init__(self, 
                 deployment_controller: DeploymentController,
                 validator_base_url: str = "http://localhost:8001"):

        self.deployment_controller = deployment_controller
        self.validator_base_url = validator_base_url
        self.agent_evaluator = AgentEvaluator(deployment_controller, validator_base_url)

    async def evaluate_miner_from_github(self, 
                                         miner_github_url: str,
                                         miner_branch: str = "main",
                                         task_prompt: str = "",
                                         task_url: str = "") -> Dict[str, Any]:
        """
        Evaluate a miner agent using their GitHub code.

        This is the main integration point with the validator system.
        Instead of calling deployed endpoints, this method:
        1. Deploys the miner's GitHub repository
        2. Evaluates the deployed agent
        3. Returns evaluation results in the same format as the validator expects
        """
        try:
            # Use the agent evaluator to deploy and test the miner
            evaluation_result = await self.agent_evaluator.evaluate_miner_agent(
                miner_github_url=miner_github_url,
                miner_branch=miner_branch,
                task_prompt=task_prompt,
                task_url=task_url
            )

            # Convert to validator-compatible format
            validator_result = {
                "miner_github_url": miner_github_url,
                "miner_branch": miner_branch,
                "evaluation_id": evaluation_result["evaluation_id"],
                "success": evaluation_result["results"]["task_completed"],
                "execution_time": evaluation_result["results"]["response_time"],
                "actions_count": evaluation_result["results"]["actions_generated"],
                "error": evaluation_result["results"].get("error"),
                "raw_evaluation": evaluation_result
            }

            return validator_result

        except Exception as e:
            logger.error("Failed to evaluate miner from GitHub", 
                         github_url=miner_github_url, 
                         error=str(e))

            return {
                "miner_github_url": miner_github_url,
                "miner_branch": miner_branch,
                "success": False,
                "execution_time": 0,
                "actions_count": 0,
                "error": str(e),
                "raw_evaluation": None
            }

    async def batch_evaluate_miners_from_github(self, 
                                                miner_configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Evaluate multiple miners from their GitHub repositories."""
        try:
            batch_result = await self.agent_evaluator.batch_evaluate_miners(miner_configs)

            # Convert to validator-compatible format
            validator_results = []
            for evaluation_id, result in batch_result["results"].items():
                if result.get("status") == "completed":
                    validator_results.append({
                        "miner_github_url": result["results"].get("github_url", ""),
                        "miner_branch": result["results"].get("branch", "main"),
                        "evaluation_id": evaluation_id,
                        "success": result["results"]["task_completed"],
                        "execution_time": result["results"]["response_time"],
                        "actions_count": result["results"]["actions_generated"],
                        "error": result["results"].get("error"),
                        "raw_evaluation": result
                    })
                else:
                    validator_results.append({
                        "miner_github_url": "",
                        "miner_branch": "main",
                        "evaluation_id": evaluation_id,
                        "success": False,
                        "execution_time": 0,
                        "actions_count": 0,
                        "error": result.get("error", "Evaluation failed"),
                        "raw_evaluation": result
                    })

            return validator_results

        except Exception as e:
            logger.error("Failed to batch evaluate miners", error=str(e))
            return []
