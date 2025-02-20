from pydantic import Field
from typing import List
from bittensor import Synapse
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion
from autoppia_web_agents_subnet.validator.stats import MinerStats


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


class FeedbackSynapse(Synapse):
    version: str = ""
    stats: MinerStats
    # Add aggregated_stats if needed
    # aggregated_stats: MinerStats

    class Config:
        extra = "allow"

    def deserialize(self) -> "FeedbackSynapse":
        return self
