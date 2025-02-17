from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class BackendEvent(BaseModel):
    """
    Represents a validated event payload with application-specific constraints.
    Enforces proper event-application relationships and provides rich metadata.
    """

    event_type: str
    description: str
    data: Optional[Dict[str, Any]] = None
    user_id: Optional[int] = None
    created_at: datetime = datetime.now()

    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:
        base_dump = super().model_dump(*args, **kwargs)
        base_dump['created_at'] = self.created_at.isoformat()
        return base_dump
