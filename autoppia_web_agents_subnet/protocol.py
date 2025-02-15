# file: autoppia_web_agents_subnet/protocol.py

from typing import List
import bittensor as bt
from pydantic import Field
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.execution.actions.actions import ACTION_CLASS_MAP


class TaskSynapse(bt.Synapse):
    version: str = ""
    prompt: str = ""
    url: str = ""

    # Keep as a list of BaseAction
    actions: List[BaseAction] = Field(
        default_factory=list,
        description="The actions that solve the task",
    )

    class Config:
        # Make sure you allow extra fields at this level as well,
        # in case the top-level TaskSynapse receives unrecognized fields
        extra = "allow"

    def deserialize(self) -> "TaskSynapse":
        """
        After normal Pydantic parsing (which produces 'BaseAction' objects
        with any extra fields stored internally), re-instantiate each item
        as the correct subclass based on 'type'.
        """
        new_actions = []
        for base_act in self.actions:
            # base_act is a BaseAction with .type. Possibly extra fields in its __dict__.
            act_class = ACTION_CLASS_MAP.get(base_act.type, BaseAction)

            if not isinstance(base_act, act_class):
                # Build the correct subclass instance from base_act's data
                typed_obj = act_class.parse_obj(base_act.dict())
                new_actions.append(typed_obj)
            else:
                new_actions.append(base_act)

        self.actions = new_actions
        return self
