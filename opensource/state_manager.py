"""
State management for deployment records.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import structlog

from models import DeploymentRecord, DeploymentState, Color, PortAllocation

logger = structlog.get_logger(__name__)


class StateManager:
    """Manages deployment state persistence and concurrency."""

    def __init__(self, state_dir: str = "/srv/deployer/state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # In-memory state
        self._deployments: Dict[str, DeploymentRecord] = {}
        self._port_allocations: Set[int] = set()
        self._locks: Dict[str, threading.Lock] = {}

        # Global lock for state operations
        self._global_lock = threading.Lock()

        # Load existing state
        self._load_state()

    def _load_state(self):
        """Load deployment state from disk."""
        try:
            for state_file in self.state_dir.glob("*.json"):
                deployment_id = state_file.stem
                try:
                    with open(state_file, 'r') as f:
                        data = json.load(f)

                    # Convert datetime strings back to datetime objects
                    if 'created_at' in data:
                        data['created_at'] = datetime.fromisoformat(data['created_at'])
                    if 'updated_at' in data:
                        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
                    if 'last_deploy_at' in data and data['last_deploy_at']:
                        data['last_deploy_at'] = datetime.fromisoformat(data['last_deploy_at'])
                    if 'operation_started_at' in data and data['operation_started_at']:
                        data['operation_started_at'] = datetime.fromisoformat(data['operation_started_at'])

                    # Convert container info datetime fields
                    for color in ['blue_container', 'green_container']:
                        if data.get(color) and data[color].get('created_at'):
                            data[color]['created_at'] = datetime.fromisoformat(data[color]['created_at'])
                        if data.get(color) and data[color].get('last_health_check'):
                            data[color]['last_health_check'] = datetime.fromisoformat(data[color]['last_health_check'])

                    deployment = DeploymentRecord(**data)
                    self._deployments[deployment_id] = deployment

                    # Track allocated ports
                    if deployment.ports:
                        self._port_allocations.add(deployment.ports.blue_port)
                        self._port_allocations.add(deployment.ports.green_port)

                    # Create deployment-specific lock
                    self._locks[deployment_id] = threading.Lock()

                    logger.info("Loaded deployment state", deployment_id=deployment_id)

                except Exception as e:
                    logger.error("Failed to load deployment state", 
                                 deployment_id=deployment_id, error=str(e))

        except Exception as e:
            logger.error("Failed to load state directory", error=str(e))

    def _save_deployment(self, deployment_id: str):
        """Save a single deployment to disk."""
        try:
            deployment = self._deployments[deployment_id]
            state_file = self.state_dir / f"{deployment_id}.json"

            # Convert to dict and handle datetime serialization
            data = deployment.dict()
            data['created_at'] = deployment.created_at.isoformat()
            data['updated_at'] = deployment.updated_at.isoformat()

            if deployment.last_deploy_at:
                data['last_deploy_at'] = deployment.last_deploy_at.isoformat()
            if deployment.operation_started_at:
                data['operation_started_at'] = deployment.operation_started_at.isoformat()

            # Handle container datetime fields
            for color in ['blue_container', 'green_container']:
                if data.get(color) and data[color].get('created_at'):
                    data[color]['created_at'] = data[color]['created_at'].isoformat()
                if data.get(color) and data[color].get('last_health_check'):
                    data[color]['last_health_check'] = data[color]['last_health_check'].isoformat()

            with open(state_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error("Failed to save deployment state", 
                         deployment_id=deployment_id, error=str(e))

    def _delete_deployment_file(self, deployment_id: str):
        """Delete deployment state file."""
        try:
            state_file = self.state_dir / f"{deployment_id}.json"
            if state_file.exists():
                state_file.unlink()
        except Exception as e:
            logger.error("Failed to delete deployment file", 
                         deployment_id=deployment_id, error=str(e))

    def get_deployment(self, deployment_id: str) -> Optional[DeploymentRecord]:
        """Get a deployment by ID."""
        with self._global_lock:
            return self._deployments.get(deployment_id)

    def list_deployments(self) -> List[DeploymentRecord]:
        """List all deployments."""
        with self._global_lock:
            return list(self._deployments.values())

    def create_deployment(self, deployment: DeploymentRecord) -> bool:
        """Create a new deployment."""
        deployment_id = deployment.config.deployment_id

        with self._global_lock:
            if deployment_id in self._deployments:
                return False

            self._deployments[deployment_id] = deployment
            self._locks[deployment_id] = threading.Lock()

            # Track ports
            if deployment.ports:
                self._port_allocations.add(deployment.ports.blue_port)
                self._port_allocations.add(deployment.ports.green_port)

        self._save_deployment(deployment_id)
        logger.info("Created deployment", deployment_id=deployment_id)
        return True

    def update_deployment(self, deployment_id: str, **updates) -> bool:
        """Update a deployment with the provided fields."""
        with self._global_lock:
            if deployment_id not in self._deployments:
                return False

            deployment = self._deployments[deployment_id]

            # Update fields
            for key, value in updates.items():
                if hasattr(deployment, key):
                    setattr(deployment, key, value)

            deployment.updated_at = datetime.utcnow()

        self._save_deployment(deployment_id)
        return True

    def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a deployment."""
        with self._global_lock:
            if deployment_id not in self._deployments:
                return False

            deployment = self._deployments[deployment_id]

            # Free ports
            if deployment.ports:
                self._port_allocations.discard(deployment.ports.blue_port)
                self._port_allocations.discard(deployment.ports.green_port)

            # Remove from memory
            del self._deployments[deployment_id]
            if deployment_id in self._locks:
                del self._locks[deployment_id]

        self._delete_deployment_file(deployment_id)
        logger.info("Deleted deployment", deployment_id=deployment_id)
        return True

    def get_deployment_lock(self, deployment_id: str) -> Optional[threading.Lock]:
        """Get the lock for a specific deployment."""
        with self._global_lock:
            return self._locks.get(deployment_id)

    def allocate_ports(self, start_port: int = 40000, end_port: int = 41000) -> Optional[PortAllocation]:
        """Allocate two consecutive ports for blue/green deployment."""
        with self._global_lock:
            for port in range(start_port, end_port - 1):
                if port not in self._port_allocations and (port + 1) not in self._port_allocations:
                    self._port_allocations.add(port)
                    self._port_allocations.add(port + 1)
                    return PortAllocation(blue_port=port, green_port=port + 1)
        return None

    def free_ports(self, ports: PortAllocation):
        """Free allocated ports."""
        with self._global_lock:
            self._port_allocations.discard(ports.blue_port)
            self._port_allocations.discard(ports.green_port)

    def get_allocated_ports(self) -> Set[int]:
        """Get all currently allocated ports."""
        with self._global_lock:
            return self._port_allocations.copy()

    def is_deployment_locked(self, deployment_id: str) -> bool:
        """Check if a deployment is currently locked (operation in progress)."""
        deployment = self.get_deployment(deployment_id)
        return deployment and deployment.operation_in_progress

    def lock_deployment(self, deployment_id: str, operation: str) -> bool:
        """Lock a deployment for an operation."""
        if not self.update_deployment(
            deployment_id,
            operation_in_progress=True,
            current_operation=operation,
            operation_started_at=datetime.utcnow()
        ):
            return False

        deployment = self.get_deployment(deployment_id)
        if deployment:
            deployment.add_event("operation_started", f"Started {operation}")

        logger.info("Locked deployment for operation", 
                    deployment_id=deployment_id, operation=operation)
        return True

    def unlock_deployment(self, deployment_id: str, success: bool = True):
        """Unlock a deployment after operation completion."""
        deployment = self.get_deployment(deployment_id)
        if not deployment:
            return

        operation = deployment.current_operation or "unknown"

        self.update_deployment(
            deployment_id,
            operation_in_progress=False,
            current_operation=None,
            operation_started_at=None
        )

        if deployment:
            event_type = "operation_completed" if success else "operation_failed"
            deployment.add_event(event_type, f"Completed {operation}")

        logger.info("Unlocked deployment", 
                    deployment_id=deployment_id, operation=operation, success=success)

    def get_deployment_stats(self) -> Dict[str, int]:
        """Get deployment statistics."""
        with self._global_lock:
            stats = {
                "total": len(self._deployments),
                "active": 0,
                "building": 0,
                "failed": 0,
                "locked": 0
            }

            for deployment in self._deployments.values():
                if deployment.state in [DeploymentState.HEALTHY, DeploymentState.PROMOTED]:
                    stats["active"] += 1
                elif deployment.state == DeploymentState.BUILDING:
                    stats["building"] += 1
                elif deployment.state == DeploymentState.FAILED:
                    stats["failed"] += 1

                if deployment.operation_in_progress:
                    stats["locked"] += 1

            return stats
