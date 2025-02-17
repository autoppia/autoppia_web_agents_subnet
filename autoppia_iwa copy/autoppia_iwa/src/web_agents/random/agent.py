import random

from ...data_generation.domain.classes import Task
from ...execution.actions.actions import ClickAction, NavigateAction
from ..base import BaseAgent
from ..classes import TaskSolution


class RandomClickerWebAgent(BaseAgent):
    """
    Web Agent that executes random actions within the screen dimensions.
    """

    def __init__(self):
        super().__init__()

    async def solve_task(self, task: Task) -> TaskSolution:
        """
        Generates a list of random click actions within the screen dimensions.
        :param task: The task for which actions are being generated.
        :return: A TaskSolution containing the generated actions.
        """
        actions = [NavigateAction(url=task.url)]
        for _ in range(1):  # Generate 10 random click actions
            x = random.randint(0, task.specifications.screen_width - 1)  # Random x coordinate
            y = random.randint(0, task.specifications.screen_height - 1)  # Random y coordinate
            actions.append(ClickAction(x=x, y=y))

        return TaskSolution(task=task, actions=actions)
