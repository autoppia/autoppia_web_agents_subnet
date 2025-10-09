"""
API endpoints for validator integration.
"""
import uuid
from typing import Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from models import APIResponse, ErrorResponse
from validator_integration import ValidatorIntegration

logger = structlog.get_logger(__name__)

# Create router for integration endpoints
router = APIRouter(prefix="/v1/integration", tags=["validator-integration"])


class MinerEvaluationRequest(BaseModel):
    """Request to evaluate a miner from GitHub."""
    github_url: str = Field(..., regex=r'^https://github\.com/[^/]+/[^/]+/?$')
    branch: str = Field("main", description="Git branch to evaluate")
    task_prompt: str = Field("", description="Task prompt for evaluation")
    task_url: str = Field("", description="Task URL for evaluation")


class BatchMinerEvaluationRequest(BaseModel):
    """Request to evaluate multiple miners from GitHub."""
    miners: List[Dict[str, str]] = Field(..., description="List of miner configurations")

    class Config:
        schema_extra = {
            "example": {
                "miners": [
                    {
                        "github_url": "https://github.com/user1/miner-agent",
                        "branch": "main",
                        "task_prompt": "Navigate to the homepage",
                        "task_url": "https://example.com"
                    },
                    {
                        "github_url": "https://github.com/user2/miner-agent",
                        "branch": "dev",
                        "task_prompt": "Click the login button",
                        "task_url": "https://example.com"
                    }
                ]
            }
        }


class EvaluationStatusResponse(BaseModel):
    """Response for evaluation status."""
    evaluation_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_at: Optional[str] = None
    error: Optional[str] = None
    results: Optional[Dict] = None


def get_validator_integration() -> ValidatorIntegration:
    """Get validator integration instance."""
    # This would be injected from the main app
    # For now, we'll create a placeholder
    from deployment_controller import DeploymentController

    # This is a simplified version - in practice, this would be injected
    controller = DeploymentController()
    return ValidatorIntegration(controller)


@router.post("/evaluate-miner", response_model=APIResponse)
async def evaluate_miner_from_github(
    request: MinerEvaluationRequest,
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Evaluate a miner agent using their GitHub code."""
    request_id = str(uuid.uuid4())

    try:
        integration = get_validator_integration()

        result = await integration.evaluate_miner_from_github(
            miner_github_url=request.github_url,
            miner_branch=request.branch,
            task_prompt=request.task_prompt,
            task_url=request.task_url
        )

        return APIResponse(
            request_id=request_id,
            status="success",
            data=result
        )

    except Exception as e:
        logger.error("Failed to evaluate miner", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to evaluate miner: {str(e)}"
        )


@router.post("/evaluate-miners-batch", response_model=APIResponse)
async def batch_evaluate_miners_from_github(
    request: BatchMinerEvaluationRequest,
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Evaluate multiple miners from their GitHub repositories."""
    request_id = str(uuid.uuid4())

    try:
        integration = get_validator_integration()

        # Convert request format
        miner_configs = []
        for miner in request.miners:
            miner_configs.append({
                "github_url": miner["github_url"],
                "branch": miner.get("branch", "main"),
                "task_prompt": miner.get("task_prompt", ""),
                "task_url": miner.get("task_url", "")
            })

        results = await integration.batch_evaluate_miners_from_github(miner_configs)

        return APIResponse(
            request_id=request_id,
            status="success",
            data={
                "total_evaluations": len(results),
                "successful": len([r for r in results if r.get("success")]),
                "failed": len([r for r in results if not r.get("success")]),
                "results": results
            }
        )

    except Exception as e:
        logger.error("Failed to batch evaluate miners", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to batch evaluate miners: {str(e)}"
        )


@router.get("/evaluation/{evaluation_id}", response_model=APIResponse)
async def get_evaluation_status(
    evaluation_id: str,
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Get status of an evaluation."""
    request_id = str(uuid.uuid4())

    try:
        integration = get_validator_integration()
        status = await integration.agent_evaluator.get_evaluation_status(evaluation_id)

        if not status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation {evaluation_id} not found"
            )

        return APIResponse(
            request_id=request_id,
            status="success",
            data=status
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get evaluation status", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get evaluation status: {str(e)}"
        )


@router.get("/evaluations", response_model=APIResponse)
async def list_active_evaluations(
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """List all active evaluations."""
    request_id = str(uuid.uuid4())

    try:
        integration = get_validator_integration()
        evaluations = await integration.agent_evaluator.list_active_evaluations()

        return APIResponse(
            request_id=request_id,
            status="success",
            data=evaluations
        )

    except Exception as e:
        logger.error("Failed to list evaluations", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list evaluations: {str(e)}"
        )


@router.post("/evaluation/{evaluation_id}/cancel", response_model=APIResponse)
async def cancel_evaluation(
    evaluation_id: str,
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Cancel an active evaluation."""
    request_id = str(uuid.uuid4())

    try:
        integration = get_validator_integration()
        success = await integration.agent_evaluator.cancel_evaluation(evaluation_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation {evaluation_id} not found or already completed"
            )

        return APIResponse(
            request_id=request_id,
            status="success",
            data={
                "evaluation_id": evaluation_id,
                "message": "Evaluation cancelled successfully"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to cancel evaluation", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel evaluation: {str(e)}"
        )


@router.get("/validator-health", response_model=APIResponse)
async def check_validator_health(
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Check if the validator integration is healthy."""
    request_id = str(uuid.uuid4())

    try:
        integration = get_validator_integration()

        # Check if we can connect to the validator
        health_status = {
            "integration_healthy": True,
            "deployment_controller_available": True,
            "active_evaluations": len(await integration.agent_evaluator.list_active_evaluations()),
            "timestamp": str(uuid.uuid4())  # Would use actual timestamp
        }

        return APIResponse(
            request_id=request_id,
            status="success",
            data=health_status
        )

    except Exception as e:
        logger.error("Validator health check failed", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Validator integration unhealthy: {str(e)}"
        )
