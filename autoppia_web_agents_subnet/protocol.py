# file: autoppia_iwa/src/execution/protocol.py
"""
Pure protocol layer:
 - Defines Synapse payloads exchanged between validator and miners.
 - No side-effects (no printing, visualization, or persistence).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import bittensor as bt
from bittensor import Synapse
from pydantic import Field

from autoppia_iwa.src.data_generation.domain.classes import TestUnion
from autoppia_iwa.src.execution.actions.actions import AllActionsUnion


class TaskSynapse(Synapse):
    """
    Synapse carrying the Task prompt & data from validator to miners.
    """
    version: str = ""
    prompt: str
    url: str
    html: Optional[str] = None
    screenshot: Optional[str] = None
    actions: List[AllActionsUnion] = Field(
        default_factory=list,
        description="The actions that solve the task",
    )

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskSynapse":
        return self


class TaskFeedbackSynapse(Synapse):
    """
    Feedback from validator back to miner: tests, scores, eval data.
    (Data-only; keep IO/printing elsewhere.)
    """
    version: str = ""
    validator_id: str
    miner_id: str
    task_id: str
    task_url: str
    prompt: str
    score: Optional[float] = 0.0
    execution_time: Optional[float] = 0.0
    tests: Optional[List["TestUnion"]] = None
    actions: Optional[List[AllActionsUnion]] = Field(default_factory=list)
    test_results_matrix: Optional[List[List[Any]]] = None
    evaluation_result: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskFeedbackSynapse":
        return self


class StartRoundSynapse(Synapse):
    """
    Round handshake:
      - Validator -> Miner: announce a new round (metadata).
      - Miner -> Validator: respond with agent metadata for this round.

    Validator-populated (request):
      - round_id: unique identifier for the round.
      - validator_id: optional human-readable or wallet ID.
      - total_prompts / prompts_per_use_case: optional planning hints.
      - note: free-form context.

    Miner-populated (response):
      - agent_name: display name of the agent.
      - agent_image: URL (or data URI) to agent logo/avatar.
      - github_url: repository with miner/agent code.
      - agent_version / capabilities: optional details.
    """
    # Request (validator -> miner)
    version: str = ""
    round_id: str
    validator_id: Optional[str] = None
    total_prompts: Optional[int] = None
    prompts_per_use_case: Optional[int] = None
    note: Optional[str] = None

    # Response (miner -> validator)
    agent_name: Optional[str] = None
    agent_image: Optional[str] = None  # URL or data URI
    github_url: Optional[str] = None
    agent_version: Optional[str] = None
    has_rl:bool = False

    class Config:
        extra = "allow"
        arbitrary_types_allowed = True

    def deserialize(self) -> "StartRoundSynapse":
        return self
