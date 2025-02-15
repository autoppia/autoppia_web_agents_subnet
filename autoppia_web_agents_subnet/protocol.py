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
        Deserialize output, reconstructing actions from raw data while preserving their specific types and parameters
        """
        if hasattr(self, "actions") and self.actions:
            bt.logging.debug(f"Starting deserialization of actions: {self.actions}")
            deserialized_actions = []

            for action in self.actions:
                try:
                    # Convert action to dict if it isn't already
                    action_data = (
                        action if isinstance(action, dict) else action.model_dump()
                    )
                    bt.logging.debug(f"Processing action data: {action_data}")

                    # Get action type and its parameters
                    action_type = action_data.get("type")
                    action_params = {
                        k: v for k, v in action_data.items() if k != "type"
                    }

                    # Look up the appropriate action class
                    action_class = ACTION_CLASS_MAP.get(action_type, BaseAction)
                    bt.logging.debug(
                        f"Found action class {action_class.__name__} for type {action_type}"
                    )

                    # Create new instance with all original parameters
                    deserialized_action = action_class(**action_params)
                    deserialized_actions.append(deserialized_action)
                    bt.logging.debug(
                        f"Successfully deserialized action: {deserialized_action}"
                    )

                except Exception as e:
                    bt.logging.error(f"Failed to deserialize action {action}: {str(e)}")
                    deserialized_actions.append(BaseAction())

            bt.logging.debug(
                f"Completed deserialization. Final actions: {deserialized_actions}"
            )
            self.actions = deserialized_actions

        return self


class Dummy:
    pass
