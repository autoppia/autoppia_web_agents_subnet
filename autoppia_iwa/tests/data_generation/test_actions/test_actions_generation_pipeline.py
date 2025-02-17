import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.shared.utils import instantiate_test
from autoppia_iwa.src.web_agents.apified_agent import ApifiedWebAgent
from tests import test_container


class TestNewActionsGeneration(unittest.TestCase):
    """
    Unit tests for generating new actions based on task configurations.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up shared resources for all tests in the class.
        """
        # Initialize the application bootstrap and LLM service
        cls.app_bootstrap = AppBootstrap()
        cls.llm_service = cls.app_bootstrap.container.llm_service()
        cls.web_agent: ApifiedWebAgent = test_container.web_agent()
        # Create the task configuration
        cls.task = cls._create_task()

    @staticmethod
    def _create_task():
        """
        Create a Task configuration from predefined task data.

        Returns:
            Task: A Task instance with configured prompt, domain, URL, and tests.
        """

        # Sample task data
        task_data = {
            "prompt": "Click on the \"Login\" link in the header. Then fill the form with email:test@gmail.com adn password:test1234 and click on login",
            "url": "http://localhost:8000/",
            "tests": [
                {"description": "Check if the backend emitted the specified event", "test_type": "backend", "event_name": "page_view", "app_type": "jobs"},
                {"description": "Find in the current HTML some of the words in the list", "test_type": "frontend", "keywords": ["email"]},
                {"description": "Check if the backend emitted the specified event", "test_type": "backend", "event_name": "login", "app_type": "jobs"},
                {"description": "Find in the current HTML some of the words in the list", "test_type": "frontend", "keywords": ["logout"]},
            ],
            "milestones": None,
            "web_analysis": None,
        }

        # Generate test instances from the test data
        tests = [instantiate_test(test) for test in task_data["tests"]]

        # Create and return a Task instance with the generated tests
        return Task(
            prompt=task_data["prompt"],
            url=task_data["url"],
            tests=tests,
            milestones=task_data["milestones"],
            web_analysis=task_data["web_analysis"],
        )

    def test_new_actions_generation(self):
        """Test that actions are generated correctly from a goal and URL."""
        # Generate actions using the configured task
        task_solution = self.web_agent.solve_task_sync(task=self.task)

        # Assertions
        self.assertTrue(task_solution, "No task solution were generated.")
        self.assertTrue(task_solution.actions, "No actions were generated. The action list is empty.")

        # Debugging output (optional)
        print(f"Generated {len(task_solution.actions)} actions:")
        for idx, action in enumerate(task_solution.actions, start=1):
            print(f"{idx}: {repr(action)}")


if __name__ == "__main__":
    unittest.main()
