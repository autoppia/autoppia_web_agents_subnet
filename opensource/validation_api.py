"""
API endpoints for miner repository validation.
"""
import uuid
from typing import Dict, Optional

import structlog
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from models import APIResponse
from miner_validator import MinerRepositoryValidator

logger = structlog.get_logger(__name__)

# Create router for validation endpoints
router = APIRouter(prefix="/v1/validation", tags=["miner-validation"])


class ValidationRequest(BaseModel):
    """Request to validate a miner repository."""
    github_url: str = Field(..., regex=r'^https://github\.com/[^/]+/[^/]+/?$')
    branch: str = Field("main", description="Git branch to validate")


class ValidationResponse(BaseModel):
    """Response for repository validation."""
    valid: bool
    github_url: str
    branch: str
    commit_sha: Optional[str] = None
    errors: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)
    suggestions: list = Field(default_factory=list)
    checks: Dict = Field(default_factory=dict)
    report: str = ""


def get_validator() -> MinerRepositoryValidator:
    """Get miner repository validator instance."""
    return MinerRepositoryValidator()


@router.post("/repository", response_model=APIResponse)
async def validate_repository(
    request: ValidationRequest,
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Validate a miner repository against the Autoppia standard."""
    request_id = str(uuid.uuid4())

    try:
        validator = get_validator()

        logger.info("Starting repository validation", 
                    request_id=request_id,
                    github_url=request.github_url,
                    branch=request.branch)

        # Validate the repository
        validation_result = await validator.validate_repository(
            github_url=request.github_url,
            branch=request.branch
        )

        # Generate human-readable report
        report = validator.generate_validation_report(validation_result)
        validation_result["report"] = report

        logger.info("Repository validation completed", 
                    request_id=request_id,
                    valid=validation_result["valid"],
                    errors=len(validation_result["errors"]))

        return APIResponse(
            request_id=request_id,
            status="success",
            data=validation_result
        )

    except Exception as e:
        logger.error("Repository validation failed", 
                     request_id=request_id, 
                     error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: {str(e)}"
        )


@router.get("/standard", response_model=APIResponse)
async def get_validation_standard(
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Get the Autoppia miner repository validation standard."""
    request_id = str(uuid.uuid4())

    standard = {
        "name": "Autoppia Miner Repository Standard",
        "version": "1.0.0",
        "description": "Standard structure for miner repositories to be compatible with the Autoppia Deployment Controller",
        "required_files": [
            "docker-compose.yml",
            "agent/Dockerfile", 
            "agent/main.py",
            "agent/requirements.txt",
            "README.md"
        ],
        "required_directories": [
            "agent"
        ],
        "docker_compose_requirements": {
            "services": ["agent"],
            "agent_service": {
                "ports": ["8000:8000"],
                "healthcheck": True,
                "labels": ["autoppia.miner=true"],
                "networks": ["deployer_network"]
            }
        },
        "api_endpoints": [
            "/health",
            "/api/task", 
            "/api/info"
        ],
        "action_types": {
            "navigate": {"url": "string"},
            "click": {"selector": "string", "coordinates": [int, int]},
            "type": {"selector": "string", "text": "string"},
            "scroll": {"direction": "string", "amount": int},
            "wait": {"duration": float},
            "screenshot": {},
            "extract": {"selector": "string", "attribute": "string"}
        },
        "environment_variables": {
            "AGENT_NAME": "Display name for the agent",
            "AGENT_VERSION": "Version of the agent", 
            "GITHUB_URL": "URL to the repository",
            "HAS_RL": "Whether agent uses reinforcement learning (true/false)",
            "LOG_LEVEL": "Logging level (DEBUG, INFO, WARNING, ERROR)"
        },
        "validation_checks": {
            "required_files": "All required files must exist",
            "required_directories": "All required directories must exist",
            "docker_compose": "docker-compose.yml must be valid and properly configured",
            "agent_structure": "Agent directory must have proper structure and files",
            "readme": "README.md must exist and contain basic documentation"
        }
    }

    return APIResponse(
        request_id=request_id,
        status="success",
        data=standard
    )


@router.get("/template", response_model=APIResponse)
async def get_repository_template(
    token: str = Depends(lambda: "placeholder")  # Would use actual auth
):
    """Get a template repository structure for miners."""
    request_id = str(uuid.uuid4())

    template = {
        "name": "Autoppia Miner Repository Template",
        "description": "Template structure for creating compliant miner repositories",
        "structure": {
            "docker-compose.yml": {
                "description": "Main deployment configuration",
                "required": True,
                "example": """version: '3.8'

services:
  agent:
    build:
      context: ./agent
      dockerfile: Dockerfile
    container_name: autoppia-miner-agent
    ports:
      - "8000:8000"
    environment:
      - AGENT_NAME=${AGENT_NAME:-Autoppia Miner}
      - AGENT_VERSION=${AGENT_VERSION:-1.0.0}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      - "autoppia.miner=true"
    networks:
      - deployer_network

networks:
  deployer_network:
    external: true
    name: deployer_network"""
            },
            "agent/Dockerfile": {
                "description": "Agent container definition",
                "required": True,
                "example": """FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]"""
            },
            "agent/main.py": {
                "description": "Main agent entry point with FastAPI",
                "required": True,
                "example": """from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Autoppia Miner Agent")

class TaskRequest(BaseModel):
    prompt: str
    url: str
    html: str = ""
    screenshot: str = ""
    actions: list = []
    version: str = "1.0.0"

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/api/task")
async def process_task(request: TaskRequest):
    # Implement your agent logic here
    return {
        "success": True,
        "actions": [],
        "execution_time": 0.0,
        "agent_id": "My Agent"
    }

@app.get("/api/info")
async def get_agent_info():
    return {
        "agent_name": "My Agent",
        "version": "1.0.0",
        "capabilities": ["web_navigation", "element_interaction"]
    }"""
            },
            "agent/requirements.txt": {
                "description": "Python dependencies",
                "required": True,
                "example": """fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
httpx==0.25.2"""
            },
            "README.md": {
                "description": "Repository documentation",
                "required": True,
                "example": """# My Autoppia Miner Agent

## Description
Brief description of your miner agent and its capabilities.

## Quick Start
```bash
docker-compose up -d
curl http://localhost:8000/health
```

## API Endpoints
- `GET /health` - Health check
- `POST /api/task` - Process task from validator
- `GET /api/info` - Agent information"""
            }
        },
        "quick_start": {
            "1": "Clone this template or create a new repository",
            "2": "Copy the template files to your repository",
            "3": "Implement your agent logic in agent/main.py",
            "4": "Update agent/requirements.txt with your dependencies",
            "5": "Test locally with: docker-compose up",
            "6": "Validate with: POST /v1/validation/repository",
            "7": "Submit your repository for evaluation"
        }
    }

    return APIResponse(
        request_id=request_id,
        status="success",
        data=template
    )
