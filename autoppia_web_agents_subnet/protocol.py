from typing import List
import bittensor as bt
from pydantic import Field
from autoppia_iwa.src.data_generation.domain.classes import Task
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
    message:str = "Hello"
    # task:Task = Field(
    #     ...,
    #     title="task",
    #     description="The task to be solved",
    # )
    actions: List[BaseAction] = Field(
        ...,
        title="actions",
        description="The actions that solve the task",
    )

    def deserialize(self) -> float:
        """
        Deserialize output. This method retrieves the response from
        the miner in the form of self.text, deserializes it and returns it
        as the output of the dendrite.query() call.

        """
        return self


class Dummy:
    pass
