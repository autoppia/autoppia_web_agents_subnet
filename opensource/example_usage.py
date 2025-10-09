"""
Example usage of the Autoppia Deployment Controller for evaluating miner agents.
"""
import asyncio
import httpx
from typing import Dict, List, Any


class DeploymentControllerClient:
    """Client for interacting with the deployment controller API."""

    def __init__(self, base_url: str = "http://localhost:8000", auth_token: str = "your-secret-token-here"):
        self.base_url = base_url.rstrip('/')
        self.auth_token = auth_token
        self.headers = {"Authorization": f"Bearer {auth_token}"}

    async def create_deployment(self, deployment_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new deployment."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/repos",
                json=deployment_config,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def get_deployment_status(self, deployment_id: str) -> Dict[str, Any]:
        """Get deployment status."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v1/repos/{deployment_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def redeploy(self, deployment_id: str, redeploy_config: Dict[str, Any]) -> Dict[str, Any]:
        """Redeploy an existing deployment."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/repos/{deployment_id}/redeploy",
                json=redeploy_config,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def switch_deployment(self, deployment_id: str, color: str) -> Dict[str, Any]:
        """Switch deployment between blue/green."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/repos/{deployment_id}/switch",
                json={"color": color},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def delete_deployment(self, deployment_id: str, keep_images: bool = False) -> Dict[str, Any]:
        """Delete a deployment."""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.base_url}/v1/repos/{deployment_id}?keep_images={keep_images}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def get_deployment_logs(self, deployment_id: str, color: str = None, tail: int = 200) -> Dict[str, Any]:
        """Get deployment logs."""
        params = {"tail": tail}
        if color:
            params["color"] = color

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v1/repos/{deployment_id}/logs",
                params=params,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def evaluate_miner_from_github(self, miner_config: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate a miner agent from GitHub."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/integration/evaluate-miner",
                json=miner_config,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def batch_evaluate_miners(self, miner_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluate multiple miners from GitHub."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/integration/evaluate-miners-batch",
                json={"miners": miner_configs},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()


async def example_basic_deployment():
    """Example: Basic deployment workflow."""
    print("=== Basic Deployment Example ===")

    client = DeploymentControllerClient()

    # 1. Create a deployment
    deployment_config = {
        "deployment_id": "example-app",
        "repo_url": "https://github.com/example/web-app",
        "branch": "main",
        "health_path": "/health",
        "internal_port": 8000,
        "env": ["NODE_ENV=production"],
        "build_args": ["BUILD_ENV=prod"]
    }

    print("Creating deployment...")
    result = await client.create_deployment(deployment_config)
    print(f"Deployment created: {result}")

    deployment_id = result["data"]["deployment_id"]

    # 2. Check deployment status
    print("Checking deployment status...")
    status = await client.get_deployment_status(deployment_id)
    print(f"Deployment status: {status}")

    # 3. Get deployment logs
    print("Getting deployment logs...")
    logs = await client.get_deployment_logs(deployment_id)
    print(f"Deployment logs: {logs['data']['logs'][:500]}...")

    # 4. Switch to green (if available)
    print("Switching to green...")
    try:
        switch_result = await client.switch_deployment(deployment_id, "green")
        print(f"Switched to green: {switch_result}")
    except Exception as e:
        print(f"Switch failed (expected if no green container): {e}")

    # 5. Clean up
    print("Deleting deployment...")
    delete_result = await client.delete_deployment(deployment_id)
    print(f"Deployment deleted: {delete_result}")


async def example_miner_evaluation():
    """Example: Evaluating miner agents from GitHub."""
    print("\n=== Miner Evaluation Example ===")

    client = DeploymentControllerClient()

    # 1. Evaluate a single miner
    miner_config = {
        "github_url": "https://github.com/example/miner-agent",
        "branch": "main",
        "task_prompt": "Navigate to the homepage and click the login button",
        "task_url": "https://example.com"
    }

    print("Evaluating single miner...")
    result = await client.evaluate_miner_from_github(miner_config)
    print(f"Evaluation result: {result}")

    # 2. Batch evaluate multiple miners
    miner_configs = [
        {
            "github_url": "https://github.com/miner1/agent",
            "branch": "main",
            "task_prompt": "Click the search button",
            "task_url": "https://example.com"
        },
        {
            "github_url": "https://github.com/miner2/agent",
            "branch": "dev",
            "task_prompt": "Fill out the contact form",
            "task_url": "https://example.com"
        }
    ]

    print("Batch evaluating miners...")
    batch_result = await client.batch_evaluate_miners(miner_configs)
    print(f"Batch evaluation result: {batch_result}")


async def example_blue_green_workflow():
    """Example: Blue/Green deployment workflow."""
    print("\n=== Blue/Green Workflow Example ===")

    client = DeploymentControllerClient()

    deployment_id = "blue-green-example"

    try:
        # 1. Create initial deployment (blue)
        print("Creating initial deployment (blue)...")
        deployment_config = {
            "deployment_id": deployment_id,
            "repo_url": "https://github.com/example/web-app",
            "branch": "main",
            "health_path": "/health",
            "internal_port": 8000
        }

        result = await client.create_deployment(deployment_config)
        print(f"Initial deployment: {result}")

        # 2. Redeploy with new branch (green)
        print("Redeploying with new branch (green)...")
        redeploy_config = {
            "branch": "feature/new-feature",
            "env": ["FEATURE_FLAG=new-feature"]
        }

        redeploy_result = await client.redeploy(deployment_id, redeploy_config)
        print(f"Redeploy result: {redeploy_result}")

        # 3. Check status of both colors
        print("Checking deployment status...")
        status = await client.get_deployment_status(deployment_id)
        print(f"Deployment status: {status}")

        # 4. Switch to green
        print("Switching to green...")
        switch_result = await client.switch_deployment(deployment_id, "green")
        print(f"Switch result: {switch_result}")

        # 5. Rollback to blue if needed
        print("Rolling back to blue...")
        rollback_result = await client.switch_deployment(deployment_id, "blue")
        print(f"Rollback result: {rollback_result}")

    finally:
        # Clean up
        print("Cleaning up...")
        try:
            await client.delete_deployment(deployment_id)
            print("Cleanup completed")
        except Exception as e:
            print(f"Cleanup failed: {e}")


async def example_validator_integration():
    """Example: Integration with validator system."""
    print("\n=== Validator Integration Example ===")

    client = DeploymentControllerClient()

    # This simulates how the validator would use the deployment controller
    # to evaluate miners using their GitHub code instead of deployed endpoints

    # 1. Get list of miners to evaluate (this would come from the validator)
    miners_to_evaluate = [
        {
            "uid": 1,
            "github_url": "https://github.com/miner1/autoppia-agent",
            "branch": "main"
        },
        {
            "uid": 2,
            "github_url": "https://github.com/miner2/autoppia-agent",
            "branch": "dev"
        }
    ]

    # 2. Prepare evaluation tasks (this would come from the validator's task generation)
    task_prompt = "Navigate to the homepage and find the search functionality"
    task_url = "https://example-ecommerce-site.com"

    # 3. Evaluate each miner using their GitHub code
    evaluation_results = []

    for miner in miners_to_evaluate:
        print(f"Evaluating miner {miner['uid']} from {miner['github_url']}...")

        miner_config = {
            "github_url": miner["github_url"],
            "branch": miner["branch"],
            "task_prompt": task_prompt,
            "task_url": task_url
        }

        try:
            result = await client.evaluate_miner_from_github(miner_config)
            evaluation_results.append({
                "miner_uid": miner["uid"],
                "success": result["data"]["success"],
                "execution_time": result["data"]["execution_time"],
                "actions_count": result["data"]["actions_count"],
                "error": result["data"].get("error")
            })
            print(f"Miner {miner['uid']} evaluation: {result['data']['success']}")

        except Exception as e:
            evaluation_results.append({
                "miner_uid": miner["uid"],
                "success": False,
                "execution_time": 0,
                "actions_count": 0,
                "error": str(e)
            })
            print(f"Miner {miner['uid']} evaluation failed: {e}")

    # 4. Process results (this would be used by the validator for scoring)
    print("\nEvaluation Results Summary:")
    for result in evaluation_results:
        print(f"Miner {result['miner_uid']}: "
              f"Success={result['success']}, "
              f"Time={result['execution_time']}s, "
              f"Actions={result['actions_count']}")
        if result['error']:
            print(f"  Error: {result['error']}")


async def main():
    """Run all examples."""
    print("Autoppia Deployment Controller Examples")
    print("=====================================")

    try:
        await example_basic_deployment()
        await example_miner_evaluation()
        await example_blue_green_workflow()
        await example_validator_integration()

    except Exception as e:
        print(f"Example failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
