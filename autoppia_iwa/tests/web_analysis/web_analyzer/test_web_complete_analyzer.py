import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.web_analysis.application.web_analysis_pipeline import WebAnalysisPipeline


class TestWebAnalysisPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_boostrap = AppBootstrap()
        cls.analysis_repository = cls.app_boostrap.container.analysis_repository()
        cls.llm_service = cls.app_boostrap.container.llm_service()
        cls.start_url = "http://localhost:8000/"

    def test_pipeline(self):
        """
        Test the pipeline with a real website to verify the complete flow.
        """
        # Configure the pipeline with the real dependencies
        pipeline = WebAnalysisPipeline(start_url=self.start_url, llm_service=self.llm_service, analysis_repository=self.analysis_repository)

        # Run the analysis
        result = pipeline.analyze()

        # Basic checks
        self.assertIsNotNone(result)
        self.assertEqual(result.domain, "localhost:8000")
        self.assertGreater(len(result.analyzed_urls), 0)  # At least one URL must be parsed

        # Print the results
        print("Analysis results:")
        print(result)


if __name__ == "__main__":
    unittest.main()
