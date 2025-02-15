import bittensor as bt
from pydantic import Field
from typing import List

from autoppia_iwa.src.execution.actions.base import AllActionsUnion
from bittensor import Synapse 


class TaskSynapse(Synapse):
    version: str = ""
    prompt: str = ""
    url: str = ""

    actions: List[AllActionsUnion] = Field(
        default_factory=list,
        description="The actions that solve the task"
    )

    class Config:
        extra = "allow"

    def deserialize(self) -> "TaskSynapse":
        return self
