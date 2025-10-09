"""
FastAPI application for the deployment controller.
"""
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

import structlog
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import ValidationError

from models import (
    CreateDeploymentRequest, RedeployRequest, SwitchRequest, 
    DeploymentStatus, APIResponse, ErrorResponse, HealthResponse,
    LogsRequest, Color
)
from deployment_controller import DeploymentController
from integration_api import router as integration_router
from validation_api import router as validation_router

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Global deployment controller
controller: Optional[DeploymentController] = None
security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global controller

    # Startup
    logger.info("Starting deployment controller API")

    try:
        controller = DeploymentController(
            state_dir=os.getenv("STATE_DIR", "/srv/deployer/state"),
            work_dir=os.getenv("WORK_DIR", "/srv/deployer/work"),
            network_name=os.getenv("DOCKER_NETWORK", "deployer_network"),
            traefik_api_url=os.getenv("TRAEFIK_API_URL", "http://traefik:8080")
        )

        await controller.initialize()
        logger.info("Deployment controller initialized successfully")

    except Exception as e:
        logger.error("Failed to initialize deployment controller", error=str(e))
        raise

    yield

    # Shutdown
    logger.info("Shutting down deployment controller API")
    if controller:
        await controller.shutdown()
    logger.info("Deployment controller API shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Autoppia Deployment Controller",
    description="A deployment controller API for blue/green deployments with GitHub integration",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include integration and validation routers
app.include_router(integration_router)
app.include_router(validation_router)


def verify_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify authentication token."""
    expected_token = os.getenv("AUTH_TOKEN", "your-secret-token-here")

    if not credentials or credentials.credentials != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


def get_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors."""
    request_id = get_request_id()

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            request_id=request_id,
            error="Validation error",
            error_code="VALIDATION_ERROR"
        ).dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    request_id = get_request_id()
    logger.error("Unhandled exception", request_id=request_id, error=str(exc))

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            request_id=request_id,
            error="Internal server error",
            error_code="INTERNAL_ERROR"
        ).dict()
    )


@app.get("/v1/healthz", response_model=HealthResponse)
async def health_check():
    """Controller health check endpoint."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    health_data = await controller.get_controller_health()
    return HealthResponse(**health_data)


@app.get("/v1/status", response_model=APIResponse)
async def get_status(token: str = Depends(verify_auth)):
    """Get status of all deployments."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    request_id = get_request_id()

    try:
        deployments_status = await controller.get_all_deployments_status()

        # Convert to DeploymentStatus objects
        status_list = []
        for deployment_id, status_data in deployments_status.items():
            if "error" not in status_data:
                status_list.append(DeploymentStatus(
                    deployment_id=deployment_id,
                    repo_url=status_data.get("repo_url", ""),
                    branch=status_data.get("branch", ""),
                    active_color=Color(status_data.get("active_color", "blue")),
                    state=status_data.get("state", "idle"),
                    health_status=status_data.get("overall_health", "unknown"),
                    last_commit=status_data.get("last_commit"),
                    image_tag=status_data.get("image_tag"),
                    last_deploy_at=status_data.get("last_deploy_at"),
                    public_url=f"/apps/{deployment_id}/",
                    blue_port=status_data.get("containers", {}).get("blue", {}).get("port"),
                    green_port=status_data.get("containers", {}).get("green", {}).get("port"),
                    build_in_progress=status_data.get("state") == "building",
                    operation=status_data.get("operation")
                ))

        return APIResponse(
            request_id=request_id,
            status="success",
            data=status_list
        )

    except Exception as e:
        logger.error("Failed to get deployment status", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get deployment status: {str(e)}"
        )


@app.post("/v1/repos", response_model=APIResponse)
async def create_deployment(
    request: CreateDeploymentRequest,
    token: str = Depends(verify_auth)
):
    """Create or deploy a new repository."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    request_id = get_request_id()

    try:
        deployment = await controller.create_deployment(request)

        return APIResponse(
            request_id=request_id,
            status="success",
            data={
                "deployment_id": deployment.config.deployment_id,
                "state": deployment.state,
                "active_color": deployment.active_color,
                "public_url": f"/apps/{deployment.config.deployment_id}/",
                "message": "Deployment created successfully"
            }
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Failed to create deployment", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create deployment: {str(e)}"
        )


@app.post("/v1/repos/{deployment_id}/redeploy", response_model=APIResponse)
async def redeploy_deployment(
    deployment_id: str,
    request: RedeployRequest,
    token: str = Depends(verify_auth)
):
    """Redeploy an existing deployment."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    request_id = get_request_id()

    try:
        deployment = await controller.redeploy(deployment_id, request)

        return APIResponse(
            request_id=request_id,
            status="success",
            data={
                "deployment_id": deployment.config.deployment_id,
                "state": deployment.state,
                "active_color": deployment.active_color,
                "message": "Deployment redeployed successfully"
            }
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RuntimeError as e:
        if "busy" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e)
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(e)
            )
    except Exception as e:
        logger.error("Failed to redeploy", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to redeploy: {str(e)}"
        )


@app.post("/v1/repos/{deployment_id}/switch", response_model=APIResponse)
async def switch_deployment(
    deployment_id: str,
    request: SwitchRequest,
    token: str = Depends(verify_auth)
):
    """Switch deployment between blue/green."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    request_id = get_request_id()

    try:
        deployment = await controller.switch_deployment(deployment_id, request)

        return APIResponse(
            request_id=request_id,
            status="success",
            data={
                "deployment_id": deployment.config.deployment_id,
                "active_color": deployment.active_color,
                "message": f"Switched to {deployment.active_color.value}"
            }
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        logger.error("Failed to switch deployment", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to switch deployment: {str(e)}"
        )


@app.delete("/v1/repos/{deployment_id}", response_model=APIResponse)
async def delete_deployment(
    deployment_id: str,
    keep_images: bool = False,
    token: str = Depends(verify_auth)
):
    """Delete a deployment."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    request_id = get_request_id()

    try:
        success = await controller.delete_deployment(deployment_id, keep_images)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deployment {deployment_id} not found"
            )

        return APIResponse(
            request_id=request_id,
            status="success",
            data={
                "deployment_id": deployment_id,
                "message": "Deployment deleted successfully"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete deployment", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete deployment: {str(e)}"
        )


@app.get("/v1/repos/{deployment_id}", response_model=APIResponse)
async def get_deployment(
    deployment_id: str,
    token: str = Depends(verify_auth)
):
    """Get detailed information about a deployment."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    request_id = get_request_id()

    try:
        status_data = await controller.get_deployment_status(deployment_id)

        if not status_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deployment {deployment_id} not found"
            )

        return APIResponse(
            request_id=request_id,
            status="success",
            data=status_data
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get deployment", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get deployment: {str(e)}"
        )


@app.get("/v1/repos/{deployment_id}/logs", response_model=APIResponse)
async def get_deployment_logs(
    deployment_id: str,
    color: Optional[str] = None,
    tail: int = 200,
    token: str = Depends(verify_auth)
):
    """Get deployment logs."""
    if not controller:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Controller not initialized"
        )

    request_id = get_request_id()

    try:
        color_enum = None
        if color:
            try:
                color_enum = Color(color.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid color. Must be 'blue' or 'green'"
                )

        logs = await controller.get_deployment_logs(deployment_id, color_enum, tail)

        return APIResponse(
            request_id=request_id,
            status="success",
            data={
                "deployment_id": deployment_id,
                "color": color or "active",
                "logs": logs
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get deployment logs", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get deployment logs: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # Run the application
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
