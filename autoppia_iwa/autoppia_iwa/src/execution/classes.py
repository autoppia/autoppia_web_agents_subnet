from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from ..backend_demo_web.classes import BackendEvent
from .actions.base import BaseAction


class BrowserSnapshot(BaseModel):
    """
    Represents a snapshot of the browser state before and after executing an action.
    Captures HTML content, screenshots, backend events, and metadata.
    """

    iteration: int = Field(..., description="The current iteration of the evaluation process")
    action: BaseAction = Field(..., description="The action that was executed")
    prev_html: str = Field(..., description="HTML content before actions were executed")
    current_html: str = Field(..., description="HTML content after actions were executed")
    screenshot_before: str = Field(..., description="Base64-encoded screenshot before actions")
    screenshot_after: str = Field(..., description="Base64-encoded screenshot after actions")
    backend_events: List[BackendEvent] = Field(..., description="List of backend events after execution")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the snapshot")
    current_url: str = Field(..., description="Current URL of the browser")

    def model_dump(self, *args, **kwargs):
        base_dump = super().model_dump(*args, **kwargs)
        base_dump["timestamp"] = self.timestamp.isoformat() if self.timestamp else None
        base_dump["backend_events"] = [event.model_dump() for event in self.backend_events]
        base_dump.pop("prev_html", None)
        base_dump.pop("current_html", None)
        base_dump.pop("action", None)
        return base_dump


class ActionExecutionResult(BaseModel):
    """Log of the execution result of an action."""

    action: BaseAction = Field(..., description="The action that was executed")
    action_event: str = Field(..., description="Type of the action event (e.g., 'click', 'navigate', 'type')")
    is_successfully_executed: bool = Field(..., description="Indicates whether the action was executed successfully")
    error: Optional[str] = Field(None, description="Details of the error if the action failed")
    execution_time: Optional[float] = Field(None, description="Time taken to execute the action, in seconds")
    browser_snapshot: BrowserSnapshot = Field(..., description="Snapshot of the browser state after execution")

    def model_dump(self, *args, **kwargs):
        base_dump = super().model_dump(*args, **kwargs)
        base_dump["browser_snapshot"] = self.browser_snapshot.model_dump()
        return base_dump
