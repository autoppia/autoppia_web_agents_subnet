import asyncio
import json
import logging
import time
import unittest
from pathlib import Path

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.classes import Task, TaskDifficultyLevel
from autoppia_iwa.src.evaluation.evaluator.evaluator import ConcurrentEvaluator, EvaluatorConfig
from autoppia_iwa.src.execution.actions.actions import ACTION_CLASS_MAP
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.shared.utils import generate_random_web_agent_id, instantiate_test
from autoppia_iwa.src.web_agents.classes import TaskSolution

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class ConcurrentTaskEvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Initialize dependencies and prepare output directory.
        """
        cls.app_bootstrap = AppBootstrap()
        cls.domain = "localhost:8000"
        cls.start_url = "http://localhost:8000/"
        cls.difficulty_level = TaskDifficultyLevel.EASY
        cls.output_dir = Path(__file__).resolve().parent
        cls.output_dir.mkdir(parents=True, exist_ok=True)
        cls.save_results_in_db = True
        cls.num_of_tasks_to_evaluate = 100

    @staticmethod
    def save_tasks_to_file(tasks: dict, folder_name: str, output_dir: Path, file_name: str):
        """
        Save tasks to a JSON file in the specified folder.
        """
        file_path = output_dir / folder_name / file_name
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with file_path.open("w", encoding="utf-8") as file:
                json.dump(tasks, file, ensure_ascii=False, indent=4)
            logging.info(f"Tasks successfully saved to {file_path}")
        except Exception as e:
            logging.error(f"Failed to save tasks to {file_path}: {e}")
            raise

    @staticmethod
    def load_tasks(file_name: str, output_dir: Path) -> dict:
        """
        Load tasks from a JSON file in the specified folder.
        """
        file_path = output_dir / file_name
        if not file_path.exists():
            logging.warning(f"File not found: {file_path}. Tasks will be generated.")
            return {"tasks": []}
        try:
            with file_path.open("r", encoding="utf-8") as file:
                tasks = json.load(file)
            logging.info(f"Loaded {len(tasks.get('tasks', []))} tasks from {file_path}")
            return tasks
        except Exception as e:
            logging.error(f"Failed to load tasks from {file_path}: {e}")
            return {"tasks": []}

    def generate_and_evaluate_tasks(self, input_file: str, output_file: str):
        """
        Generate and evaluate tasks asynchronously.
        """
        start_time = time.time()

        # Load tasks
        tasks_data = self.load_tasks(input_file, self.output_dir)
        tasks = tasks_data.get("tasks", [])

        # Randomly pick 100 tasks from the list
        import random

        if len(tasks) > self.num_of_tasks_to_evaluate:
            tasks = random.sample(tasks, self.num_of_tasks_to_evaluate)

        # Prepare evaluation input
        evaluator_input = [
            TaskSolution(
                task=Task(
                    prompt=task["prompt"],
                    url=task["url"],
                    tests=[instantiate_test(test) for test in task["tests"]],
                ),
                actions=[BaseAction.model_validate(action)for action in task.get("actions", [])],
                web_agent_id=task.get("web_agent_id", generate_random_web_agent_id()),
            )
            for task in tasks_data["tasks"]
        ]
        evaluator_config = EvaluatorConfig(current_url=self.start_url, save_results_in_db=self.save_results_in_db)

        evaluator = ConcurrentEvaluator(evaluator_config)
        evaluated_tasks = asyncio.run(evaluator.evaluate_all_tasks(evaluator_input))

        # Save evaluated tasks
        tasks_data["tasks"] = [_.model_dump() for _ in evaluated_tasks]
        if self.save_results_in_db:
            self.save_tasks_to_file(tasks_data, "evaluation_results", self.output_dir, output_file)

        elapsed_time = time.time() - start_time
        logging.info(f"Evaluation completed in {elapsed_time:.2f} seconds.")
        return tasks_data

    def test_task_evaluation_stress_test(self):
        """
        Test evaluation of tasks with stress testing scenarios.
        """
        result = self.generate_and_evaluate_tasks("actions_data.json", "hard_tasks.json")
        self.assertIn("tasks", result, "Result should contain tasks.")
        logging.info("Stress test task evaluation completed successfully.")

    def test_tasks_evaluation_grouped_actions(self):
        """
        Test evaluation of grouped tasks with shared actions.
        """
        result = self.generate_and_evaluate_tasks("grouped_actions.json", "grouped_tasks.json")
        self.assertIn("tasks", result, "Result should contain tasks.")
        logging.info("Grouped actions task evaluation completed successfully.")


if __name__ == "__main__":
    unittest.main()
