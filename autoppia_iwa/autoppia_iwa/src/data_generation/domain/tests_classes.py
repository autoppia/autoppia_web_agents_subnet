import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Literal

from dependency_injector.wiring import Provide
from pydantic import BaseModel, Field, field_validator

from ....config.config import PROJECT_BASE_DIR
from ...di_container import DIContainer
from ...execution.classes import BrowserSnapshot
from ...llms.infrastructure.llm_service import OpenAIService


class ITest(ABC):
    @abstractmethod
    def _execute_test(self, test_context: BrowserSnapshot) -> bool:
        """
        Abstract method to implement the specific logic for the test.

        Args:
            test_context (BrowserSnapshot): The context containing data for the test.

        Returns:
            bool: True if the test passes, otherwise False.
        """
        pass


class BaseTaskTest(BaseModel, ITest):
    """
    Abstract base class for task tests.
    Defines a common interface and structure for test execution.
    """

    description: str = Field(default="Base task test", description="Description of the test")
    test_type: Literal["frontend", "backend"] = Field(default="frontend", description="Type of the test")

    def execute_test(self, test_context: BrowserSnapshot) -> bool:
        """
        Executes the test using the provided context.

        Args:
            test_context (BrowserSnapshot): The context containing data for the test.

        Returns:
            bool: True if the test passes, otherwise False.
        """
        return self._execute_test(test_context)

    def _execute_test(self, test_context: BrowserSnapshot) -> bool:
        raise NotImplementedError("Subclasses must implement this method.")

    @classmethod
    def assign_tests(cls, test_configs: List[Dict]) -> List["BaseTaskTest"]:
        """
        Assigns and instantiates tests based on the provided test configurations.

        Args:
            test_configs (List[Dict]): A list of test configurations.

        Returns:
            List[BaseTaskTest]: A list of instantiated test objects.
        """
        assigned_tests = []

        for config in test_configs:
            test_type = config.get("test_type")

            # Instantiate the appropriate class based on test_type and configuration
            if test_type == "frontend" and "keywords" in config:
                assigned_tests.append(FindInHtmlTest(**config))
            elif test_type == "backend" and "page_view_url" in config:
                assigned_tests.append(CheckPageViewEventTest(**config))
            elif test_type == "backend" and "event_name" in config:
                assigned_tests.append(CheckEventEmittedTest(**config))
            else:
                raise ValueError(f"Unsupported test configuration: {config}")

        return assigned_tests


class FindInHtmlTest(BaseTaskTest):
    """
    Test class to find specific keywords in the current HTML content.
    """

    keywords: List[str] = Field(..., description="List of keywords to search for in the HTML")
    description: str = Field(
        default="Find keywords in the current HTML content",
        description="Description of the test",
    )
    test_type: Literal["frontend"] = "frontend"

    @field_validator('keywords')
    @classmethod
    def validate_keywords(cls, keywords: List[str]) -> List[str]:
        """
        Validate the list of keywords.

        Args:
            keywords (List[str]): The list of keywords to validate.

        Returns:
            List[str]: The validated list of keywords.

        Raises:
            ValueError: If the number of keywords exceeds the limit or if any keyword is empty.
        """
        if not all(keyword.strip() for keyword in keywords):
            raise ValueError("Keywords cannot be empty or consist of only whitespace")
        return [keyword.strip().lower() for keyword in keywords]

    def _execute_test(self, test_context: BrowserSnapshot) -> bool:
        content = test_context.current_html.lower()
        return any(keyword in content for keyword in self.keywords)


class CheckEventEmittedTest(BaseTaskTest):
    """
    Test class to verify if a specific backend event was emitted.
    """

    event_name: str = Field(..., description="Name of the expected backend event")

    description: str = Field(
        default="Verify if the backend emitted the specified event",
        description="Description of the test",
    )
    test_type: Literal["backend"] = "backend"

    def _execute_test(self, test_context: BrowserSnapshot) -> bool:
        return any(event.event_type == self.event_name for event in test_context.backend_events)


class CheckPageViewEventTest(BaseTaskTest):
    """
    Test class to verify if a specific page view event was logged in the backend.
    """

    page_view_url: str = Field(..., description="The URL expected to trigger a page view event")
    description: str = Field(
        default="Check if the backend logged a page view event for the specified URL",
        description="Description of the test",
    )
    test_type: Literal["backend"] = "backend"

    def _execute_test(self, test_context: BrowserSnapshot) -> bool:
        events = test_context.backend_events
        return self.page_view_url in [event.data.get("url", "") for event in events if event.data]


class OpinionBaseOnHTML(BaseTaskTest):
    """
    Test class to generate an opinion based on changes in HTML before and after an action.
    """

    description: str = Field(default="Generate an opinion based on HTML changes")
    test_type: Literal["frontend"] = "frontend"
    llm_service: Any = Field(default=Provide[DIContainer.llm_service], exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def _execute_test(self, test_context: BrowserSnapshot) -> bool:
        from autoppia_iwa.src.shared.utils import clean_html

        html_before = clean_html(test_context.prev_html)
        html_after = clean_html(test_context.current_html)
        action = str(test_context.action)
        return self._analyze_htmls(action, html_before, html_after)

    def _analyze_htmls(self, action: str, html_before: str, html_after: str) -> bool:
        """
        Sends a request to the LLM service for evaluation.
        """
        system_message = (
            "You are a professional web page analyzer. Your task is to determine whether the given task was completed with the action given, by analyzing the HTML before and after the action."
        )
        user_message = f"Current action: {action}HTML Before:\n{html_before}\n\nHTML After:\n{html_after}"

        payload = [{"role": "system", "content": system_message}, {"role": "user", "content": user_message}]
        with Path(PROJECT_BASE_DIR / "config/schemas/eval_html_test.json").open(encoding="utf-8") as f:
            json_schema = json.load(f)
        chat_completion_kwargs = {"response_format": {"type": "json_object", "schema": json_schema}, "temperature": 0.6, "top_k": 50}

        result = self.llm_service.make_request(payload, chat_completion_kwargs=chat_completion_kwargs)
        parsed_result = json.loads(result)
        return parsed_result["task_completed"]


class OpinionBaseOnScreenshot(BaseTaskTest):
    """
    Test class to generate an opinion based on screenshots before and after an action.
    Uses an LLM service to evaluate whether the task was completed successfully.
    """

    task: str = Field(..., description="Task description that is intended to be completed")
    description: str = Field(default="Generate an opinion based on screenshot differences")
    test_type: Literal["frontend"] = "frontend"
    llm_service: OpenAIService = Field(default_factory=OpenAIService, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def _execute_test(self, test_context: BrowserSnapshot) -> bool:
        return self._analyze_screenshots(test_context.screenshot_before, test_context.screenshot_after)

    def _analyze_screenshots(self, screenshot_before: str, screenshot_after: str) -> bool:
        """
        Sends a request to the LLM service for evaluation.
        """
        # Define the system and user prompts
        system_message = (
            "You are a professional web page analyzer. Your task is to determine whether the given task was completed "
            "by analyzing the screenshots before and after the action. Your response must be a JSON object with a single "
            "key 'result' containing either `true` or `false`."
        )
        user_message = f"Task: '{self.task}'"
        payload = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_before}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_after}"}},
                ],
            },
        ]

        # Load the JSON schema for validation
        schema_path = Path(PROJECT_BASE_DIR) / "config/schemas/screenshot_test_schema.json"
        try:
            with schema_path.open(encoding="utf-8") as f:
                json_schema = json.load(f)
        except Exception as e:
            print(f"Error loading JSON schema: {e}")
            return False

        chat_completion_kwargs = {"response_format": {"type": "json_object", "schema": json_schema}, "temperature": 0.6, "top_k": 50}

        result = self.llm_service.make_request(payload, chat_completion_kwargs=chat_completion_kwargs)
        parsed_result = json.loads(result)

        return parsed_result["result"]
