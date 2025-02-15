# file: autoppia_web_agents_subnet/protocol.py

from typing import List, Dict, Any
import bittensor as bt
from pydantic import Field
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.execution.actions.actions import ACTION_CLASS_MAP


class TaskSynapse(bt.Synapse):
    """
    A protocol representation which uses bt.Synapse as its base.
    This protocol helps in handling request and response communication
    between the miner and the validator.
    """

    version: str = ""
    prompt: str = ""
    url: str = ""

    # IMPORTANT: Use List[dict] (or List[Any]) so Pydantic won't parse them as BaseAction too early:
    actions: List[dict] = Field(
        default_factory=list,
        description="The raw actions that solve the task (as dicts before casting)."
    )

    def deserialize(self) -> "TaskSynapse":
        """
        Cast each item in self.actions (raw dict) into the correct child class 
        based on 'type' and store them back in self.actions as typed objects.
        """
        new_actions = []
        for act_dict in self.actions:
            # "type" should be something like "ClickAction", "NavigateAction", etc.
            act_type = act_dict.get("type", None)

            # Use your global map of type -> class
            # Fallback to BaseAction if not found
            action_cls = ACTION_CLASS_MAP.get(act_type, BaseAction)

            # Instantiate
            action_obj = action_cls(**act_dict)
            new_actions.append(action_obj)

        # Replace the original list of dicts with the typed objects
        self.actions = new_actions
        return self
