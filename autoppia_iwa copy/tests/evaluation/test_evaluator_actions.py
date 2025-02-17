import asyncio
import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.evaluation.evaluator.evaluator import ConcurrentEvaluator, EvaluatorConfig
from autoppia_iwa.src.execution.actions.actions import ACTION_CLASS_MAP
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.shared.utils import generate_random_web_agent_id, instantiate_test
from autoppia_iwa.src.web_agents.classes import TaskSolution


class TestActionExecution(unittest.TestCase):
    """
    Unit test for evaluating task execution and action processing.
    """

    @classmethod
    def setUpClass(cls):
        """
        Class-level setup that initializes the application bootstrap and task/action data.
        """
        cls.app_bootstrap = AppBootstrap()
        task_data = {
            "prompt": "Click on the \"Login\" link in the header. Then fill the form with email:employee@employee.com and password:employee and click on login",
            "url": "http://localhost:8000/",
            "tests": [
                {"description": "Check if the backend emitted the specified event", "test_type": "backend", "event_name": "page_view"},
                {"description": "Find in the current HTML some of the words in the list", "test_type": "frontend", "keywords": ["login"]},
                {"description": "Check if the backend emitted the specified event", "test_type": "backend", "event_name": "login"},
                {"description": "Find in the current HTML some of the words in the list", "test_type": "frontend", "keywords": ["logout"]},
            ],
            "milestones": None,
            "web_analysis": None,
        }
        tests = [instantiate_test(test) for test in task_data["tests"]]
        cls.task = Task(
            prompt=task_data["prompt"],
            url=task_data["url"],
            tests=tests,
            milestones=task_data["milestones"],
            web_analysis=task_data["web_analysis"],
        )
        cls.accurate_actions_data = {
            "actions": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "href", "value": "/login"}, "action": {"type": "click"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_password"}, "action": {"type": "type", "value": "employee"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "class", "value": "btn-outline-white-primary"}, "action": {"type": "click"}},
            ]
        }
        cls.half_accurate_actions_data = {
            "actions": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "href", "value": "/login"}, "action": {"type": "click"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_password"}, "action": {"type": "type", "value": "employee"}},
            ]
        }
        cls.wrong_actions_data = {
            "actions": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_password"}, "action": {"type": "type", "value": "employee"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "class", "value": "btn-outline-white"}, "action": {"type": "click"}},
            ]
        }

    def evaluate(self, actions):
        # Prepare evaluation input
        evaluator_input = TaskSolution(task=self.task, actions=actions, web_agent_id=generate_random_web_agent_id())
        evaluator_config = EvaluatorConfig(current_url=self.task.url, save_results_in_db=False)

        evaluator = ConcurrentEvaluator(evaluator_config)
        evaluation_result = asyncio.run(evaluator.evaluate_single_task(evaluator_input))

        # Display results
        print("\n--- Evaluation Results ---")
        # print(evaluation_result)
        self.assertTrue(evaluation_result, "Task evaluation failed.")
        print(f"Final score: {evaluation_result.final_score}")

    def test_accurate_task_evaluation(self):
        actions = [BaseAction.model_validate(action) for action in self.accurate_actions_data["actions"]], 
        self.evaluate(actions)

    def test_half_accurate_task_evaluation(self):
        actions = [BaseAction.model_validate(action) for action in self.accurate_actions_data["actions"]]
        self.evaluate(actions)

    def test_wrong_task_evaluation(self):
        actions = [BaseAction.model_validate(action) for action in self.accurate_actions_data["actions"]]
        self.evaluate(actions)


if __name__ == "__main__":
    unittest.main()
