from typing import List
import bittensor as bt
from pydantic import Field
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.execution.actions.actions import ACTION_CLASS_MAP


class TaskSynapse(bt.Synapse):
    """
    A protocol representation which uses bt.Synapse as its base.
    This protocol helps in handling request and response communication between
    the miner and the validator.
    """

    version: str = ""
    prompt: str = ""
    url: str = ""
    actions: List[BaseAction] = Field(
        ...,
        title="actions",
        description="The actions that solve the task",
    )

    def deserialize(self) -> "TaskSynapse":
        """
        Deserialize output, ensuring actions are properly reconstructed using the ACTION_CLASS_MAP
        """
        if hasattr(self, "actions") and self.actions:
            deserialized_actions = []
            for action in self.actions:
                if isinstance(action, dict):
                    # Si es un diccionario, necesitamos reconstruir la acción
                    action_type = action.get("type")
                    action_class = ACTION_CLASS_MAP.get(action_type, BaseAction)
                    deserialized_actions.append(action_class(**action))
                else:
                    # Si ya es un objeto action, verificamos su tipo
                    action_data = action.model_dump()
                    action_type = action_data.get("type")
                    action_class = ACTION_CLASS_MAP.get(action_type, BaseAction)
                    deserialized_actions.append(action_class(**action_data))

            self.actions = deserialized_actions

        return self


class Dummy:
    pass
