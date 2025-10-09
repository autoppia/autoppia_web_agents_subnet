"""
Data models for the deployment controller.
"""
from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, validator


class DeploymentState(str, Enum):
    """Deployment state machine states."""
    IDLE = "idle"
    BUILDING = "building"
    STAGING = "staging"
    HEALTHY = "healthy"
    FAILED = "failed"
    PROMOTED = "promoted"
    RETIRED_OLD = "retired_old"
    ROLLED_BACK = "rolled_back"
    DELETED = "deleted"


class Color(str, Enum):
    """Blue/Green deployment colors."""
    BLUE = "blue"
    GREEN = "green"


class HealthStatus(str, Enum):
    """Health check status."""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CHECKING = "checking"


class PortAllocation(BaseModel):
    """Port allocation for a deployment."""
    blue_port: int
    green_port: int

    @validator('blue_port', 'green_port')
    def validate_ports(cls, v):
        if not 1024 <= v <= 65535:
            raise ValueError('Port must be between 1024 and 65535')
        return v


class ContainerInfo(BaseModel):
    """Information about a running container."""
    container_id: str
    image_tag: str
    port: int
    status: str
    created_at: datetime
    health_status: HealthStatus = HealthStatus.UNKNOWN
    last_health_check: Optional[datetime] = None
    health_check_count: int = 0
    logs_tail: Optional[str] = None


class DeploymentConfig(BaseModel):
    """Configuration for a deployment."""
    deployment_id: str = Field(..., min_length=1, max_length=50, regex=r'^[a-zA-Z0-9_-]+$')
    repo_url: str = Field(..., regex=r'^https://github\.com/[^/]+/[^/]+/?$')
    branch: str = "main"
    subdir: Optional[str] = None
    health_path: str = "/healthz"
    expected_status: int = 200
    internal_port: int = Field(8000, ge=1, le=65535)
    env: List[str] = Field(default_factory=list)
    build_args: List[str] = Field(default_factory=list)
    probe_timeout_sec: int = Field(120, ge=1, le=600)
    grace_sec: int = Field(60, ge=0, le=3600)
    startup_delay_sec: int = Field(3, ge=0, le=60)
    labels: Dict[str, str] = Field(default_factory=dict)

    @validator('env', 'build_args')
    def validate_key_value_pairs(cls, v):
        for item in v:
            if '=' not in item:
                raise ValueError('Environment variables and build args must be in KEY=VALUE format')
        return v


class DeploymentRecord(BaseModel):
    """Complete deployment record."""
    config: DeploymentConfig
    state: DeploymentState = DeploymentState.IDLE
    active_color: Color = Color.BLUE
    ports: Optional[PortAllocation] = None

    # Build and deployment info
    last_commit: Optional[str] = None
    image_tag: Optional[str] = None
    last_deploy_at: Optional[datetime] = None

    # Container information
    blue_container: Optional[ContainerInfo] = None
    green_container: Optional[ContainerInfo] = None

    # Health and status
    health_status: HealthStatus = HealthStatus.UNKNOWN
    last_health_check: Optional[datetime] = None

    # Operation tracking
    operation_in_progress: bool = False
    current_operation: Optional[str] = None
    operation_started_at: Optional[datetime] = None

    # History and events
    events: List[Dict[str, Any]] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def add_event(self, event_type: str, message: str, data: Optional[Dict[str, Any]] = None):
        """Add an event to the deployment history."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": event_type,
            "message": message,
            "data": data or {}
        }
        self.events.append(event)
        self.updated_at = datetime.utcnow()

        # Keep only last 50 events
        if len(self.events) > 50:
            self.events = self.events[-50:]


class DeploymentStatus(BaseModel):
    """Public deployment status for API responses."""
    deployment_id: str
    repo_url: str
    branch: str
    active_color: Color
    state: DeploymentState
    health_status: HealthStatus
    last_commit: Optional[str] = None
    image_tag: Optional[str] = None
    last_deploy_at: Optional[datetime] = None
    public_url: str
    blue_port: Optional[int] = None
    green_port: Optional[int] = None
    build_in_progress: bool = False
    operation: Optional[str] = None


class CreateDeploymentRequest(BaseModel):
    """Request to create a new deployment."""
    deployment_id: str = Field(..., min_length=1, max_length=50, regex=r'^[a-zA-Z0-9_-]+$')
    repo_url: str = Field(..., regex=r'^https://github\.com/[^/]+/[^/]+/?$')
    branch: str = "main"
    subdir: Optional[str] = None
    health_path: str = "/healthz"
    expected_status: int = 200
    internal_port: int = Field(8000, ge=1, le=65535)
    env: List[str] = Field(default_factory=list)
    build_args: List[str] = Field(default_factory=list)
    probe_timeout_sec: int = Field(120, ge=1, le=600)
    grace_sec: int = Field(60, ge=0, le=3600)
    startup_delay_sec: int = Field(3, ge=0, le=60)
    labels: Dict[str, str] = Field(default_factory=dict)
    force_redeploy: bool = False


class RedeployRequest(BaseModel):
    """Request to redeploy an existing deployment."""
    branch: Optional[str] = None
    build_args: List[str] = Field(default_factory=list)
    env: List[str] = Field(default_factory=list)
    force: bool = False


class SwitchRequest(BaseModel):
    """Request to switch between blue/green."""
    color: Color
    force: bool = False


class HealthCheckRequest(BaseModel):
    """Request to perform health check."""
    color: Optional[Color] = None
    timeout_sec: Optional[int] = None


class LogsRequest(BaseModel):
    """Request for container logs."""
    color: Optional[Color] = None
    tail: int = Field(200, ge=1, le=10000)


class APIResponse(BaseModel):
    """Standard API response format."""
    request_id: str
    status: str
    data: Optional[Any] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorResponse(BaseModel):
    """Error response format."""
    request_id: str
    status: str = "error"
    error: str
    error_code: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    docker_connected: bool
    active_deployments: int
    total_deployments: int
    uptime_seconds: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
