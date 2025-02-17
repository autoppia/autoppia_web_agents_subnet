from abc import ABC, abstractmethod
from typing import List

from autoppia_iwa.src.web_agents.classes import TaskSolution

from .classes import EvaluationResult


class IEvaluator(ABC):
    """

    The design allows for multiple web agents to implement this interface, ensuring standardized inputs and behaviors across different agents.

    Every web agent that implements this interface must define the required methods and properties, ensuring consistency and compatibility.

    Example:
    - An 'Autopilot Web Agent' would implement this interface, adhering to the standardized inputs and outputs specified here.

    The goal is to provide a common structure that all web agents will follow, facilitating integration and interoperability among them.
    """

    @abstractmethod
    def evaluate_single_task(self, task_solution: TaskSolution) -> EvaluationResult:
        """
        Evaluates a single task and returns the evaluation result.

        Args:
            task_solution (TaskSolution): The task solution to evaluate.

        Returns:
            EvaluationResult: The result of the evaluation.
        """

    @abstractmethod
    def evaluate_all_tasks(self, task_solutions: List[TaskSolution]) -> List[EvaluationResult]:
        """
        Evaluates a list of tasks and returns a list of evaluation results.

        Args:
            task_solutions (List[TaskSolution]): The list of task solutions to evaluate.

        Returns:
            List[EvaluationResult]: A list of evaluation results.
        """
