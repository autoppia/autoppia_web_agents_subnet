import asyncio
import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.evaluation.evaluator.evaluator import ConcurrentEvaluator, EvaluatorConfig
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.shared.utils import instantiate_test
from autoppia_iwa.src.web_agents.apified_agent import ApifiedWebAgent
from autoppia_iwa.src.web_agents.classes import TaskSolution
from tests import test_container


class TestActionsGenerationAndEvaluation(unittest.TestCase):
    """
    Unit tests for action generation and evaluation.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up shared resources for the test class.
        """
        cls.app_bootstrap = AppBootstrap()
        cls.llm_service = cls.app_bootstrap.container.llm_service()
        cls.web_agent: ApifiedWebAgent = test_container.web_agent()

        cls.task = cls._create_task()

        cls.web_agent_id = "miner_123"

    @staticmethod
    def _create_task():
        """
        Create a Task configuration from sample task data.

        Returns:
            Task: A Task instance with pre-configured data.
        """

        # Sample task data
        task_data = {
            "prompt": "Click on the \"Login\" link in the header. Then fill the form with email:admin@jobsapp.com and password:admin123 and click on login",
            "url": "http://localhost:8000/",
            "tests": [
                {"description": "Check if the backend emitted the specified event", "test_type": "backend", "event_name": "page_view", "page_view_url": "/login"},
                {"description": "Find in the current HTML some of the words in the list", "test_type": "frontend", "keywords": ["email"]},
                {"description": "Check if the backend emitted the specified event", "test_type": "backend", "event_name": "login"},
            ],
            "milestones": None,
            "web_analysis": None,
        }

        # Create tests from test data
        tests = [instantiate_test(test) for test in task_data["tests"]]

        # Create and return a Task instance
        return Task(
            prompt=task_data["prompt"],
            url=task_data["url"],
            tests=tests,
            milestones=task_data["milestones"],
            web_analysis=task_data["web_analysis"],
        )

    def test_actions_generation_and_evaluation(self):
        """
        Test that actions are correctly generated and evaluated.
        """
        task_solution = self.web_agent.solve_task_sync(task=self.task)

        # Assertions to validate generated actions
        self.assertTrue(task_solution, "No actions were generated. The action list is empty.")
        self.assertIsInstance(task_solution.actions, list, "Generated actions should be a list.")
        self.assertTrue(all(isinstance(action, BaseAction) for action in task_solution.actions), "All items in actions should be instances of Action.")

        # Optional debugging output
        print(f"Generated {len(task_solution.actions)} actions:")
        for idx, action in enumerate(task_solution.actions, start=1):
            print(f"{idx}: {action}")

        # Evaluate the actions
        task_solution = TaskSolution(task=self.task, actions=task_solution.actions, web_agent_id=self.web_agent_id)
        evaluator = ConcurrentEvaluator(EvaluatorConfig(current_url=self.task.url))
        evaluated_task = asyncio.run(evaluator.evaluate_single_task(task_solution))

        # Assert the evaluation result
        self.assertTrue(evaluated_task, "Task evaluation failed.")

        # Optional debugging output for evaluation
        print("\n--- Evaluation Results ---")
        print(f"Final score: {evaluated_task.feedback.final_score}")


if __name__ == "__main__":
    unittest.main()
