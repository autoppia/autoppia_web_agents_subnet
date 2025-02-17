import base64
import unittest
from datetime import datetime
from io import BytesIO

import numpy as np
from PIL import Image

from autoppia_iwa.config.config import OPENAI_API_KEY, OPENAI_MODEL
from autoppia_iwa.src.data_generation.domain.tests_classes import OpinionBaseOnScreenshot
from autoppia_iwa.src.execution.classes import BrowserSnapshot
from autoppia_iwa.src.llms.infrastructure.llm_service import OpenAIService


class TestOpinionBaseOnScreenshot(unittest.TestCase):
    def setUp(self):
        self.llm_service = OpenAIService(api_key=OPENAI_API_KEY, model=OPENAI_MODEL)
        self.test_instance = OpinionBaseOnScreenshot(task="Verify button click effect", llm_service=self.llm_service)
        # Create black and white blocks
        black_block_base64 = self.create_base64_encoded_block((0, 0, 0))
        white_block_base64 = self.create_base64_encoded_block((255, 255, 255))

        self.mock_snapshot = BrowserSnapshot(
            iteration=1,
            prev_html="<html><body><button>Click me</button></body></html>",
            current_html="<html><body><button>Clicked!</button></body></html>",
            backend_events=[],
            timestamp=datetime.fromisoformat("2025-02-10T12:00:00"),
            current_url="http://example.com",
            screenshot_before=black_block_base64,
            screenshot_after=white_block_base64,
        )

    def create_base64_encoded_block(self, color: tuple):
        block = np.full((10, 10, 3), color, dtype=np.uint8)
        img = Image.fromarray(block)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    def test_screenshot(self):
        result = self.test_instance.execute_test(self.mock_snapshot)
        print(result)


if __name__ == "__main__":
    unittest.main()
