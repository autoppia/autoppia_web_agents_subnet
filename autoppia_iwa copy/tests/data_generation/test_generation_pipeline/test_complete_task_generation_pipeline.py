import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.application.tasks_generation_pipeline import TaskGenerationPipeline
from autoppia_iwa.src.data_generation.domain.classes import TaskGenerationConfig, WebProject
from modules.webs_demo.web_1_demo_django_jobs.events.events import EVENTS_ALLOWED


class TestTaskGenerationPipeline(unittest.TestCase):
    """
    Unit tests for the TaskGenerationPipeline.

    Ensures the pipeline generates structured tasks based on the provided input.
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        Set up the environment and dependencies once for all tests.
        """
        cls.app_bootstrap = AppBootstrap()
        cls.llm_service = cls.app_bootstrap.container.llm_service()
        cls.task_repo = cls.app_bootstrap.container.synthetic_task_repository()
        cls.analysis_repo = cls.app_bootstrap.container.analysis_repository()

        cls.page_url = "http://localhost:8000/"
        cls.enable_crawl = False
        cls.save_task_in_db = True

    def test_task_generation_pipeline(self) -> None:
        """
        Test that the TaskGenerationPipeline produces valid structured tasks.

        This includes:
        - Verifying the task generation process does not fail.
        - Ensuring the output contains tasks.
        """
        # Create task generation input
        web_project = WebProject(backend_url=self.page_url, frontend_url=self.page_url, name="jobs", events_to_check=EVENTS_ALLOWED)

        task_input = TaskGenerationConfig(web_project=web_project, save_web_analysis_in_db=True, save_task_in_db=True)

        # Run the task generation pipeline
        task_output = TaskGenerationPipeline(config=task_input, llm_service=self.llm_service, synthetic_task_repository=self.task_repo, web_analysis_repository=self.analysis_repo).generate()

        # Validate the output
        self.assertIsNotNone(task_output, "Task generation pipeline returned None.")
        self.assertIsNotNone(task_output.tasks, "Task generation output has no tasks.")
        self.assertIsInstance(task_output.tasks, list, "Generated tasks should be a list.")
        self.assertGreater(len(task_output.tasks), 0, "Expected at least one task to be generated.")

        print("Generated Tasks:", task_output.tasks)


if __name__ == "__main__":
    unittest.main()
