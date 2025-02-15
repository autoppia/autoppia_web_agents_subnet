# file: autoppia_web_agents_subnet/protocol.py

from typing import List
import bittensor as bt
from pydantic import Field
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.execution.actions.actions import ACTION_CLASS_MAP

class TaskSynapse(bt.Synapse):
    """
    A protocol representation which uses bt.Synapse as its base.
    This protocol helps in handling request/response between
    the miner and validator.
    """

    version: str = ""
    prompt: str = ""
    url: str = ""

    # Keep as List[BaseAction], exactly as you wanted:
    actions: List[BaseAction] = Field(
        default_factory=list,
        description="The actions that solve the task",
    )

    class Config:
        # (1) Allow unknown fields so the base action won't choke
        extra = "allow"
        # (2) Let Pydantic store them in the model's __dict__ 
        #     so we can re-instantiate the correct subclass later.
        arbitrary_types_allowed = True

    def deserialize(self) -> "TaskSynapse":
        """
        Re-instantiate each BaseAction item in self.actions as its proper subclass,
        using 'type' to choose from ACTION_CLASS_MAP.
        """
        new_actions = []
        for base_action in self.actions:
            # 'base_action' is a BaseAction with extra fields in base_action.__dict__.
            # e.g. base_action.type might be "ClickAction" or "NavigateAction".
            action_type = getattr(base_action, "type", None)
            correct_cls = ACTION_CLASS_MAP.get(action_type, BaseAction)

            # If it's already the right type or no match found, keep it;
            # Otherwise, re-instantiate with the correct subclass.
            if not isinstance(base_action, correct_cls):
                # Convert the base_action object's fields to a dict 
                # and pass them into the correct subclass
                new_obj = correct_cls(**base_action.__dict__)
                new_actions.append(new_obj)
            else:
                new_actions.append(base_action)

        self.actions = new_actions
        return self
