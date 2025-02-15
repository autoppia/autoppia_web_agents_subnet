from typing import List
import bittensor as bt
from pydantic import Field
from autoppia_iwa.src.execution.actions.base import BaseAction


class TaskSynapse(bt.Synapse):
    """ 
    A protocol representation which uses bt.Synapse as its base.
    This protocol helps in handling request and response communication between
    the miner and the validator.

    Attributes:
    - texts: List of texts that needs to be evaluated for AI generation
    - predictions: List of probabilities in response to texts

    """

    version: str = ""
    prompt:str = ""
    url:str = ""
    actions: List[BaseAction] = Field(
        ...,
        title="actions",
        description="The actions that solve the task",
    )

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

    Attributes:
        version: version of the task
        prompt: prompt for the task
        url: URL to operate on
        actions: The actions that solve the task
    """
    version: str = ""
    prompt: str = ""
    url: str = ""
    actions: List[BaseAction] = Field(
        ...,
        title="actions",
        description="The actions that solve the task",
    )

    def deserialize(self):
        """
        Casts each item in self.actions to the correct action subclass
        based on 'type', if it's a dict. Otherwise, leaves it as is.
        """
        new_actions = []
        for act in self.actions:
            if isinstance(act, dict):
                act_type = act.get("type")
                cls = ACTION_CLASS_MAP.get(act_type, BaseAction)
                new_actions.append(cls(**act))
            else:
                new_actions.append(act)

        self.actions = new_actions
        return self



class Dummy:
    pass
