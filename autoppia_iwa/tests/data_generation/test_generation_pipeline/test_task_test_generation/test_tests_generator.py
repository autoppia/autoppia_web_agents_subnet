import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.application.task_tests_generator import TaskTestGenerator
from autoppia_iwa.src.data_generation.domain.classes import WebProject
from autoppia_iwa.src.web_analysis.application.web_analysis_pipeline import WebAnalysisPipeline
from modules.webs_demo.web_1_demo_django_jobs.events.events import EVENTS_ALLOWED


class TestTaskTestGenerationWithWebAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """
        Set up class-level test environment.
        """
        cls.app_bootstrap = AppBootstrap()
        cls.analysis_repo = cls.app_bootstrap.container.analysis_repository()
        cls.llm_service = cls.app_bootstrap.container.llm_service()

        # Local testing setup
        cls.local_page_url = "http://localhost:8000/"
        cls.local_enable_crawl = False
        cls.local_task_description = "Click on the Login button and then introduce your username and password."

        # Real web testing setup
        cls.example_url = "https://example.com/"
        cls.example_enable_crawl = False
        cls.example_task_description = "Navigate to the homepage and verify the page title."

    def _generate_tests_for_web_project(self, url: str, task_description: str, enable_crawl: bool, is_real_web: bool = False) -> list:
        """
        Helper method to perform web analysis and generate task-based tests.

        Args:
            url (str): The target web page URL.
            task_description (str): Description of the task to be tested.
            enable_crawl (bool): Whether to enable crawling.
            is_real_web (bool): Whether the project is a real web test.

        Returns:
            list: Generated task tests.
        """
        # Perform web analysis
        web_analysis_pipeline = WebAnalysisPipeline(start_url=url, analysis_repository=self.analysis_repo, llm_service=self.llm_service)
        web_analysis = web_analysis_pipeline.analyze(enable_crawl=enable_crawl, save_results_in_db=True)

        self.assertIsNotNone(web_analysis, f"Web analysis should not return None for {url}.")
        self.assertTrue(
            hasattr(web_analysis, "analyzed_urls"),
            f"Web analysis result should contain 'analyzed_urls' for {url}.",
        )

        # Initialize Web Project
        web_project = WebProject(backend_url=url, frontend_url=url, name="example" if is_real_web else "Local Web App", events_to_check=EVENTS_ALLOWED, is_real_web=is_real_web)

        # Generate task-based tests
        task_test_generator = TaskTestGenerator(web_project=web_project, web_analysis=web_analysis, llm_service=self.llm_service)
        tests = task_test_generator.generate_task_tests(task_description, url)

        self.assertIsInstance(tests, list, "Generated tests should be a list.")
        self.assertGreater(len(tests), 0, f"At least one test should be generated for {url}.")

        return tests

    def test_task_test_generation_for_local_web(self) -> None:
        """
        Test generating task-based tests for a local web application.
        """
        tests = self._generate_tests_for_web_project(url=self.local_page_url, task_description=self.local_task_description, enable_crawl=self.local_enable_crawl, is_real_web=False)
        print("Generated Tests (Local Web):", tests)

    def test_task_test_generation_for_real_web_example(self) -> None:
        """
        Test generating task-based tests for real web.
        """
        tests = self._generate_tests_for_web_project(url=self.example_url, task_description=self.example_task_description, enable_crawl=self.example_enable_crawl, is_real_web=True)
        print("Generated Tests (Real Web):", tests)


if __name__ == "__main__":
    unittest.main()
