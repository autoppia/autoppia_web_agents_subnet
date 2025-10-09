"""
Example showing how to evaluate miners using their GitHub repositories.
"""
import asyncio
import httpx
from typing import Dict, List, Any


class MinerEvaluationExample:
    """Example of evaluating miners using the deployment controller."""

    def __init__(self, base_url: str = "http://localhost:8000", auth_token: str = "your-secret-token-here"):
        self.base_url = base_url.rstrip('/')
        self.auth_token = auth_token
        self.headers = {"Authorization": f"Bearer {auth_token}"}

    async def validate_miner_repository(self, github_url: str, branch: str = "main") -> Dict[str, Any]:
        """Validate a miner repository against the standard."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/validation/repository",
                json={"github_url": github_url, "branch": branch},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def evaluate_miner_from_github(self, github_url: str, branch: str = "main", 
                                         task_prompt: str = "", task_url: str = "") -> Dict[str, Any]:
        """Evaluate a miner agent using their GitHub repository."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/integration/evaluate-miner",
                json={
                    "github_url": github_url,
                    "branch": branch,
                    "task_prompt": task_prompt,
                    "task_url": task_url
                },
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def batch_evaluate_miners(self, miner_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluate multiple miners from their GitHub repositories."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/integration/evaluate-miners-batch",
                json={"miners": miner_configs},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()


async def example_validate_miner_repository():
    """Example: Validate a miner repository."""
    print("=== Validating Miner Repository ===")

    evaluator = MinerEvaluationExample()

    # Example miner repository
    github_url = "https://github.com/example/miner-agent"
    branch = "main"

    print(f"Validating repository: {github_url}")

    try:
        result = await evaluator.validate_miner_repository(github_url, branch)
        validation_data = result["data"]

        print(f"Repository valid: {validation_data['valid']}")
        print(f"Errors: {len(validation_data['errors'])}")
        print(f"Warnings: {len(validation_data['warnings'])}")

        if validation_data['errors']:
            print("\nErrors:")
            for error in validation_data['errors']:
                print(f"  ❌ {error}")

        if validation_data['warnings']:
            print("\nWarnings:")
            for warning in validation_data['warnings']:
                print(f"  ⚠️  {warning}")

        # Print the full validation report
        if 'report' in validation_data:
            print(f"\nValidation Report:\n{validation_data['report']}")

    except Exception as e:
        print(f"Validation failed: {e}")


async def example_evaluate_single_miner():
    """Example: Evaluate a single miner from GitHub."""
    print("\n=== Evaluating Single Miner ===")

    evaluator = MinerEvaluationExample()

    # Example miner configuration
    github_url = "https://github.com/example/miner-agent"
    branch = "main"
    task_prompt = "Navigate to the homepage and click the login button"
    task_url = "https://example.com"

    print(f"Evaluating miner: {github_url}")
    print(f"Task: {task_prompt}")

    try:
        result = await evaluator.evaluate_miner_from_github(
            github_url=github_url,
            branch=branch,
            task_prompt=task_prompt,
            task_url=task_url
        )

        evaluation_data = result["data"]

        print(f"Evaluation ID: {evaluation_data['evaluation_id']}")
        print(f"Status: {evaluation_data['status']}")
        print(f"Success: {evaluation_data['success']}")
        print(f"Execution Time: {evaluation_data['execution_time']}s")
        print(f"Actions Generated: {evaluation_data['actions_count']}")

        if evaluation_data.get('error'):
            print(f"Error: {evaluation_data['error']}")

        print(f"Started: {evaluation_data['started_at']}")
        print(f"Completed: {evaluation_data['completed_at']}")

    except Exception as e:
        print(f"Evaluation failed: {e}")


async def example_batch_evaluate_miners():
    """Example: Batch evaluate multiple miners."""
    print("\n=== Batch Evaluating Miners ===")

    evaluator = MinerEvaluationExample()

    # Example miner configurations
    miner_configs = [
        {
            "github_url": "https://github.com/miner1/autoppia-agent",
            "branch": "main",
            "task_prompt": "Navigate to the homepage and find the search box",
            "task_url": "https://example.com"
        },
        {
            "github_url": "https://github.com/miner2/autoppia-agent", 
            "branch": "dev",
            "task_prompt": "Click the login button and fill in credentials",
            "task_url": "https://example.com"
        },
        {
            "github_url": "https://github.com/miner3/autoppia-agent",
            "branch": "main", 
            "task_prompt": "Scroll down and take a screenshot",
            "task_url": "https://example.com"
        }
    ]

    print(f"Evaluating {len(miner_configs)} miners...")

    try:
        result = await evaluator.batch_evaluate_miners(miner_configs)

        batch_data = result["data"]

        print(f"Total Evaluations: {batch_data['total_evaluations']}")
        print(f"Successful: {batch_data['successful']}")
        print(f"Failed: {batch_data['failed']}")

        print("\nIndividual Results:")
        for i, miner_result in enumerate(batch_data['results'], 1):
            print(f"\nMiner {i}:")
            print(f"  Success: {miner_result['success']}")
            print(f"  Execution Time: {miner_result['execution_time']}s")
            print(f"  Actions: {miner_result['actions_count']}")
            if miner_result.get('error'):
                print(f"  Error: {miner_result['error']}")

    except Exception as e:
        print(f"Batch evaluation failed: {e}")


async def example_validator_integration():
    """Example: How the validator would integrate with this system."""
    print("\n=== Validator Integration Example ===")

    evaluator = MinerEvaluationExample()

    # This simulates how the validator would use the system
    # instead of calling deployed endpoints

    # 1. Get list of miners to evaluate (from validator's miner list)
    miners_to_evaluate = [
        {
            "uid": 1,
            "github_url": "https://github.com/miner1/autoppia-agent",
            "branch": "main"
        },
        {
            "uid": 2, 
            "github_url": "https://github.com/miner2/autoppia-agent",
            "branch": "main"
        }
    ]

    # 2. Get task from validator's task generation system
    task_prompt = "Navigate to the homepage and click the search button"
    task_url = "https://example-ecommerce-site.com"

    print("Validator Integration Workflow:")
    print("1. Validator generates tasks using IWA")
    print("2. Instead of calling deployed endpoints, validator uses deployment controller")
    print("3. Deployment controller deploys each miner's GitHub repository")
    print("4. Sends tasks to deployed agents")
    print("5. Collects results and returns to validator")
    print("6. Validator processes results as usual")

    # 3. Evaluate each miner using their GitHub code
    evaluation_results = []

    for miner in miners_to_evaluate:
        print(f"\nEvaluating miner {miner['uid']} from {miner['github_url']}...")

        try:
            result = await evaluator.evaluate_miner_from_github(
                github_url=miner["github_url"],
                branch=miner["branch"],
                task_prompt=task_prompt,
                task_url=task_url
            )

            evaluation_data = result["data"]

            # Convert to validator-compatible format
            validator_result = {
                "miner_uid": miner["uid"],
                "success": evaluation_data["success"],
                "execution_time": evaluation_data["execution_time"],
                "actions_count": evaluation_data["actions_count"],
                "error": evaluation_data.get("error"),
                "evaluation_id": evaluation_data["evaluation_id"]
            }

            evaluation_results.append(validator_result)

            print(f"  ✅ Success: {validator_result['success']}")
            print(f"  ⏱️  Time: {validator_result['execution_time']}s")
            print(f"  🎯 Actions: {validator_result['actions_count']}")

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            evaluation_results.append({
                "miner_uid": miner["uid"],
                "success": False,
                "execution_time": 0,
                "actions_count": 0,
                "error": str(e)
            })

    # 4. Process results (validator would use these for scoring)
    print(f"\nEvaluation Summary:")
    print(f"Total miners: {len(evaluation_results)}")
    print(f"Successful: {len([r for r in evaluation_results if r['success']])}")
    print(f"Failed: {len([r for r in evaluation_results if not r['success']])}")

    # Calculate average execution time for successful evaluations
    successful_times = [r['execution_time'] for r in evaluation_results if r['success']]
    if successful_times:
        avg_time = sum(successful_times) / len(successful_times)
        print(f"Average execution time: {avg_time:.2f}s")

    print("\nBenefits of this approach:")
    print("✅ Test any GitHub repository, branch, or commit")
    print("✅ Consistent evaluation environment")
    print("✅ No dependency on miner infrastructure")
    print("✅ Real-time testing of code changes")
    print("✅ Parallel evaluation of multiple miners")
    print("✅ Isolated and secure containers")


async def main():
    """Run all examples."""
    print("Autoppia Miner Evaluation Examples")
    print("==================================")

    try:
        await example_validate_miner_repository()
        await example_evaluate_single_miner()
        await example_batch_evaluate_miners()
        await example_validator_integration()

    except Exception as e:
        print(f"Example failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
