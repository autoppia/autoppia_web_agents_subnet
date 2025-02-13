from typing import List
import bittensor as bt
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
    task: Task
    actions: List[BaseAction]

    def deserialize(self) -> float:
        """
        Deserialize output. This method retrieves the response from
        the miner in the form of self.text, deserializes it and returns it
        as the output of the dendrite.query() call.

        Returns:
        - List[float]: The deserialized response, which in this case is the list of preidictions.
        """
        return self


class Dummy:
    pass
