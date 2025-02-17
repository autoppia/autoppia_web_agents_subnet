import json
from typing import Dict, List, Optional

from dependency_injector.wiring import Provide

from autoppia_iwa.config.config import PROJECT_BASE_DIR

from ...data_generation.domain.tests_classes import BaseTaskTest, CheckEventEmittedTest, CheckPageViewEventTest, FindInHtmlTest, OpinionBaseOnHTML
from ...di_container import DIContainer
from ...shared.utils import extract_html
from ...web_analysis.application.web_llm_utils import ILLMService
from ...web_analysis.domain.analysis_classes import DomainAnalysis, LLMWebAnalysis, SinglePageAnalysis
from ..domain.classes import WebProject

BASE_SYSTEM_MSG = """
1. IMPORTANT RULES:
    - You are a professional evaluator responsible for generating structured test cases for tasks on a website. 
    - Based on a task description and page analysis, you must classify and generate tests into categories.
    - For CheckEventTest, only mention the valid urls in the web_analysis
    - If there is any navigation performed then there must be a CheckPageViewTest.
    - In most cases, all three test types—CheckEventTest, CheckPageViewTest, and CheckHTMLTest—are necessary.
    - However, certain scenarios may require only one or two of them instead of all three.

    1.1. OUTPUT FORMAT:
        - Always return the tests as a valid JSON array, without additional text or delimiters. The format must strictly follow this structure:
        [
            {"type": "CheckEventTest","event_name": "<event>"},
            {"type": "CheckHTMLTest","html_keywords": ["<keyword1>", "<keyword2>", ...]},
            {"type": "CheckPageViewTest","url": "<url>"}
        ]
        - For instance, if the task is to change the website's language by clicking a flag button, it is unlikely to trigger any backend events. In such cases, return only a list of CheckHTMLTest without any CheckEventTest. For example, if the task is to view a specific page, a CheckPageViewTest might be sufficient.

2. TEST TYPES:
    2.1. CheckEventTest:
        - Verifies that a backend event was triggered as a result of the task.
        - Possible backend events include:
{/event_list/}
        - Always use one of the above event names in the `event_name` field.

    2.2. CheckHTMLTest:
        - Verifies specific words or phrases in the HTML content to confirm task completion.
        - The keywords should logically indicate the success of the task. For example:
            - For a login task, use keywords like "Logout", "Sign Out", or "Welcome".
            - For a registration task, use keywords like "Thank you", "Registration Successful", or "Welcome Aboard".

    2.3. CheckPageViewTest:
        - Validates that a specific page view event was logged in the backend.
        - Use the `url` field to specify the page URL that should have been logged.
        - Example: A page view event for the URL "/login".

3. EXAMPLES:
    3.1. Task: Perform Login
        - Backend Event: Expect the "login" event to be triggered in the backend.
        - HTML Content: Look for keywords like "Logout", "Sign Out", or "Welcome".
        - Page View: Validate the page view event for the URL "/dashboard".

        Output:
        [
            {"type": "CheckEventTest", "event_name": "login"},
            {"type": "CheckHTMLTest","html_keywords": ["Logout", "Sign Out", "Welcome"]},
            {"type": "CheckPageViewTest", "url": "/dashboard"}
        ]

    3.2. Task: Register for an Account
        - Backend Event: Expect the "registration" event to be triggered in the backend.
        - HTML Content: Look for keywords like "Thank you", "Registration Successful", or "Welcome Aboard".

        Output:
        [
            {"type": "CheckEventTest","event_name": "registration" },
            {"type": "CheckHTMLTest","html_keywords": ["Thank you", "Registration Successful", "Welcome Aboard"] }
        ]

    3.3. Task: Search for a Product
        - Backend Event: Expect the "search" event to be triggered in the backend.
        - HTML Content: Look for keywords like "Results", "Products Found", or "Search Completed".

        Output:
        [
            {"type": "CheckEventTest","event_name": "search"},
            {"type": "CheckHTMLTest","html_keywords": ["Results", "Products Found", "Search Completed"]}
        ]

    3.4. Task: Visit the Login Page
        - Page View: Validate the page view event for the URL "/login". 

        Output:
        [
            {"type": "CheckPageViewTest","url": "/login"}
        ]
"""


class TaskTestGenerator:
    """
    Generates and classifies test cases into FrontendTest and BackendTest based on a task description and web analysis.
    """

    def __init__(
        self,
        web_project: WebProject,
        web_analysis: DomainAnalysis,
        llm_service: ILLMService = Provide[DIContainer.llm_service],
    ) -> None:
        self.web_project = web_project
        self.web_analysis = web_analysis
        self.llm_service = llm_service

    async def generate_task_tests(self, task_description: str, page_url: str, page_html: Optional[str] = None) -> List[BaseTaskTest]:
        """
        Generates and classifies test cases for a specific task description on a given page,
        using the configuration provided by WebProject.

        Args:
            task_description (str): The description of the task to be tested.
            page_url (str): The URL of the page (may differ from demo_web_project.url).
            page_html (Optional[str]): Pre-fetched HTML content of the page. If None, it will be extracted.

        Returns:
            List[BaseTaskTest]: A list of validated test cases.
        """
        # 1) Retrieve allowed events directly from WebProject
        allowed_events = self.web_project.events_to_check

        # 2) Prepare the system message and validation schema
        system_message = self._build_system_message(allowed_events)
        tests_schema = self._load_and_modify_schema(allowed_events)

        # 3) Fetch page analysis (or fallback to local HTML if provided)
        page_analysis = self._get_page_analysis(page_url)
        effective_html = page_html or await extract_html(page_url) or page_analysis.html_source

        relevant_fields = [field for element_analysis in (page_analysis.elements_analysis_result or []) for field in (element_analysis.get("analysis", {}) or {}).get("relevant_fields", []) or []]

        # 4) Generate tests via LLM
        raw_tests = self._call_llm_for_test_cases(
            task_description=task_description,
            html_source=effective_html,
            summary_page_url=page_analysis.web_summary,
            system_message=system_message,
            validation_schema=tests_schema,
            relevant_fields=relevant_fields,
        )

        # 5) Classify and validate the tests, returning them as a list
        return self._classify_and_validate_tests(raw_tests, allowed_events)

    @staticmethod
    def _build_system_message(allowed_events: List[str]) -> str:
        """
        Constructs the system message dynamically with the current set of events.
        """
        event_list = "\n".join(f'        - "{event}"' for event in allowed_events)
        return BASE_SYSTEM_MSG.replace("{/event_list/}", event_list)

    def _load_and_modify_schema(self, allowed_events: List[str]) -> dict:
        """Loads the base JSON schema for tests and updates it with current allowed events."""
        schema = self._load_base_schema()
        self._update_schema_events(schema, allowed_events)
        return schema

    @staticmethod
    def _load_base_schema() -> dict:
        """
        Loads the base schema from a JSON file. Adjust the path if needed.
        """
        schema_path = PROJECT_BASE_DIR / "config/schemas/task_test_schema.json"
        with schema_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _update_schema_events(schema: dict, allowed_events: List[str]) -> None:
        """
        Update the schema so that the CheckEventTest event_name field has the correct enum list.
        """
        for test_type in schema["properties"]["tests"]["items"]["oneOf"]:
            if test_type.get("properties", {}).get("type", {}).get("const") == "CheckEventTest":
                test_type["properties"]["event_name"]["enum"] = allowed_events
                break

    def _call_llm_for_test_cases(
        self,
        task_description: str,
        html_source: str,
        summary_page_url: LLMWebAnalysis,
        system_message: str,
        validation_schema: dict,
        relevant_fields: Optional[list],
    ) -> List[Dict[str, str]]:
        """
        Calls the LLM to generate test cases in JSON format, validated against 'validation_schema'.
        """
        user_message_parts = [f"Task Description: {task_description}", f"HTML Content: {html_source}"]

        if summary_page_url:
            summary_dict = summary_page_url.model_dump()
            keywords = summary_dict.pop("key_words", None)
            if keywords:
                user_message_parts.append(f"Allowed keywords for CheckHTMLTest: {keywords}")
            user_message_parts.append(f"Page Analysis Summary: {summary_dict}")
        if relevant_fields:
            user_message_parts.append(f"Relevant words for the CheckPageViewTest: {relevant_fields}")
        user_message_parts.append("Generate tests following the specified format.")
        user_message = "\n\n".join(user_message_parts)

        response = self.llm_service.make_request(
            message_payload=[{"role": "system", "content": system_message}, {"role": "user", "content": user_message}],
            chat_completion_kwargs={
                "temperature": 0.6,
                "top_k": 50,
                "response_format": {"type": "json_object", "schema": validation_schema},
            },
        )
        return json.loads(response).get("tests", []) if response else []

    def _classify_and_validate_tests(self, raw_tests: List[Dict], allowed_events: List[str]) -> List[BaseTaskTest]:
        """
        Classify each raw test dict as one of the known test types (CheckEventTest,
        CheckHTMLTest, CheckPageViewTest) and build the appropriate objects.
        """
        valid_tests = []
        for test in raw_tests:
            try:
                test_type = test["type"]
                if test_type == "CheckEventTest" and test["event_name"] in allowed_events:
                    valid_tests.append(CheckEventEmittedTest(event_name=test["event_name"]))
                elif test_type == "CheckHTMLTest":
                    valid_tests.append(FindInHtmlTest(keywords=test["html_keywords"]))
                elif test_type == "CheckPageViewTest":
                    valid_tests.append(CheckPageViewEventTest(page_view_url=test["url"]))
            except (KeyError, ValueError) as e:
                print(f"Test error: {e}")
                # If JSON is malformed, skip this test
                continue
        if not self.web_project.is_real_web:
            return valid_tests

        real_website_tests = []
        for test in valid_tests:
            if test.test_type == "backend":
                print("Can't initialize backend tests for the real webs")
                continue
            elif test.test_type == "frontend":
                real_website_tests.append(test)
                real_website_tests.append(OpinionBaseOnHTML())
        return real_website_tests

    def _get_page_analysis(self, target_url: str) -> SinglePageAnalysis:
        """
        Retrieves or matches the single page analysis for 'target_url' from self.web_analysis.
        """
        for page in self.web_analysis.analyzed_urls:
            if page.page_url == target_url:
                return page
        raise ValueError(f"Page analysis not found for URL: {target_url}")
