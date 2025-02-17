import json
import logging
import unittest
from collections import Counter
from pathlib import Path

logging.basicConfig(level=logging.INFO)


class StressTestDataGenerator(unittest.TestCase):
    OUTPUT_FILE_256 = "actions_data.json"
    OUTPUT_FILE_GROUPED = "grouped_actions.json"
    RESULT_FILE_256 = "hard_tasks.json"
    RESULT_FILE_GROUPED = "grouped_tasks.json"

    @classmethod
    def setUpClass(cls) -> None:
        cls.EVALUATION_DIR = Path(__file__).parent.resolve()
        cls.task_data_template = {
            "prompt": "Click on the \"Login\" link in the header. Then fill the form with email:employee@employee.com and password:employee and click on login",
            "domain": "localhost:8000",
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

        cls.actions_templates = {
            "accurate": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "href", "value": "/login"}, "action": {"type": "click"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_password"}, "action": {"type": "type", "value": "employee"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "class", "value": "btn-outline-white-primary"}, "action": {"type": "click"}},
            ],
            "half_accurate_1": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "href", "value": "/login"}, "action": {"type": "click"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_password"}, "action": {"type": "type", "value": "employee"}},
            ],
            "half_accurate_2": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "href", "value": "/login"}, "action": {"type": "click"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_password"}, "action": {"type": "type", "value": "employee"}},
            ],
            "half_accurate_3": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "href", "value": "/login"}, "action": {"type": "click"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "password"}, "action": {"type": "type", "value": "employee"}},
            ],
            "half_accurate_4": [
                {"selector": {"type": "attributeValueSelector", "attribute": "url", "value": "http://localhost:8000/"}, "action": {"type": "navigate", "url": "http://localhost:8000/"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "href", "value": "/login"}, "action": {"type": "click"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "id_email"}, "action": {"type": "type", "value": "employee@employee.com"}},
                {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "blah_blah_blah"}, "action": {"type": "type", "value": "employee"}},
            ],
        }

    def generate_tasks(self, task_count: int, action_template: list) -> list:
        """
        Generate a list of tasks based on the given action template.
        """
        return [{**self.task_data_template, "actions": action_template} for _ in range(task_count)]

    def load_tasks(self, file_name: str) -> dict:
        """
        Load tasks from a JSON file in the specified folder.
        """
        file_path = self.EVALUATION_DIR / "evaluation_results" / file_name
        if not file_path.exists():
            logging.info(f"File not found: {file_path}. Returning an empty task set.")
            return {"tasks": []}

        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                tasks = json.load(file)
            logging.info(f"Loaded {len(tasks.get('tasks', []))} tasks from {file_path}")
            return tasks
        except Exception as e:
            logging.error(f"Failed to load tasks from {file_path}: {e}")
            return {"tasks": []}

    def save_to_file(self, tasks: dict, output_file: str):
        """
        Save generated tasks to a JSON file.
        """
        output_path = self.EVALUATION_DIR / output_file
        try:
            with open(output_path, "w", encoding="utf-8") as file:
                json.dump(tasks, file, indent=4)
            logging.info(f"File '{output_path}' created successfully with {len(tasks['tasks'])} tasks.")
        except Exception as e:
            logging.error(f"Failed to write to {output_path}: {e}")
            raise

    def check_and_display_frequency_of_results(self, output_file: str):
        """
        Test the frequency distribution of final scores in tasks.
        """
        tasks_data = self.load_tasks(output_file)
        final_scores = [task["feedback"]["final_score"] for task in tasks_data.get("tasks", []) if "feedback" in task]
        score_frequencies = Counter(final_scores)

        # Print score frequencies (can be replaced with assertions in real test scenarios)
        for score, frequency in score_frequencies.items():
            logging.info(f"Final Score: {score}, Frequency: {frequency}")

        # Add assertions to verify the expected behavior
        self.assertGreater(len(final_scores), 0, "No final scores found in the tasks data.")
        self.assertTrue(all(isinstance(score, (int, float)) for score in final_scores), "Scores must be numeric.")

    def test_generate_256_actions_data(self):
        """
        Generate 240 accurate and 16 half-accurate tasks for stress testing.
        """
        accurate_tasks = self.generate_tasks(240, self.actions_templates["accurate"])
        half_accurate_tasks = self.generate_tasks(16, self.actions_templates["half_accurate_1"])

        combined_data = {"tasks": accurate_tasks + half_accurate_tasks}
        self.save_to_file(combined_data, self.OUTPUT_FILE_256)

    def test_generate_grouped_actions_data(self):
        """
        Generate grouped tasks with different levels of accuracy for testing.
        """
        accurate_tasks = self.generate_tasks(10, self.actions_templates["accurate"])
        half_accurate_tasks_1 = self.generate_tasks(10, self.actions_templates["half_accurate_1"])
        half_accurate_tasks_2 = self.generate_tasks(10, self.actions_templates["half_accurate_2"])
        half_accurate_tasks_3 = self.generate_tasks(10, self.actions_templates["half_accurate_3"])
        half_accurate_tasks_4 = self.generate_tasks(10, self.actions_templates["half_accurate_4"])

        combined_data = {"tasks": accurate_tasks + half_accurate_tasks_1 + half_accurate_tasks_2 + half_accurate_tasks_3 + half_accurate_tasks_4}
        self.save_to_file(combined_data, self.OUTPUT_FILE_GROUPED)

    def test_256_actions_frequency(self):
        self.check_and_display_frequency_of_results(self.RESULT_FILE_256)

    def test_grouped_actions_frequency(self):
        self.check_and_display_frequency_of_results(self.RESULT_FILE_GROUPED)


if __name__ == "__main__":
    unittest.main()
