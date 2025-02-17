import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.web_analysis.application.web_analysis_pipeline import WebAnalysisPipeline


class TestWebAnalysisPipelineWithNoCrawling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_boostrap = AppBootstrap()
        cls.analysis_repository = cls.app_boostrap.container.analysis_repository()
        cls.llm_service = cls.app_boostrap.container.llm_service()
        cls.url = "http://localhost:8000/"
        cls.enable_crawl = False
        cls.get_analysis_from_cache = False
        cls.save_results_in_db = True

    def test_pipeline_without_crawling_and_save_db(self):
        """
        Test the pipeline with a real website to verify the complete flow.
        """
        # Configure the pipeline with the real dependencies
        pipeline = WebAnalysisPipeline(start_url=self.url, llm_service=self.llm_service, analysis_repository=self.analysis_repository)

        # Run the analysis
        result = pipeline.analyze(enable_crawl=self.enable_crawl, get_analysis_from_cache=self.get_analysis_from_cache, save_results_in_db=self.save_results_in_db)

        # Basic checks
        self.assertIsNotNone(result)
        self.assertEqual(result.get("domain"), "localhost:8000")
        self.assertGreater(len(result.get("analyzed_urls")), 0)  # At least one URL must be parsed

        # Print the results
        print("Analysis results:")
        print(result)


if __name__ == "__main__":
    unittest.main()
