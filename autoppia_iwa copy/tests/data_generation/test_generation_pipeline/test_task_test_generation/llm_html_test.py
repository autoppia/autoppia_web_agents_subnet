import unittest
from datetime import datetime

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.domain.tests_classes import OpinionBaseOnHTML
from autoppia_iwa.src.execution.actions.actions import ClickAction
from autoppia_iwa.src.execution.actions.base import Selector
from autoppia_iwa.src.execution.classes import BrowserSnapshot


class TestOpinionBaseOnHTML(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize OpinionBaseOnHTML with the real LLM service."""
        cls.llm_service = AppBootstrap().container.llm_service()
        cls.test_instance = OpinionBaseOnHTML(llm_service=cls.llm_service)

    def test_html_change_detected(self):
        """Test when LLM determines the task is completed based on HTML changes."""
        test_snapshot = BrowserSnapshot(
            iteration=1,
            action=ClickAction(selector=Selector(type="xpathSelector", value="//button[text()='Click Me']")),
            prev_html="<div><button>Click Me</button></div>",
            current_html="<div><button>Click Me</button><p>Success</p></div>",
            screenshot_before="",
            screenshot_after="",
            backend_events=[],
            timestamp=datetime.fromisoformat("2025-02-10T12:00:00Z"),
            current_url="https://example.com",
        )

        # Execute the test with real LLM service
        result = self.test_instance.execute_test(test_snapshot)
        print("LLM Output:", result)  # See actual response from LLM
        self.assertIsInstance(result, bool, "LLM should return True or False")

    def test_no_html_change_detected(self):
        """Test when LLM determines the task is NOT completed due to no significant change."""
        test_snapshot = BrowserSnapshot(
            iteration=1,
            action=ClickAction(selector=Selector(type="xpathSelector", value="//button[text()='Click Me']")),
            prev_html="<div><button>Click Me</button></div>",
            current_html="<div><button>Click Me</button></div>",  # No change
            screenshot_before="",
            screenshot_after="",
            backend_events=[],
            timestamp=datetime.fromisoformat("2025-02-10T12:00:00Z"),
            current_url="https://example.com",
        )

        # Execute the test with real LLM service
        result = self.test_instance.execute_test(test_snapshot)
        print("LLM Output:", result)  # See actual response from LLM
        self.assertIsInstance(result, bool, "LLM should return True or False")


if __name__ == "__main__":
    unittest.main()
