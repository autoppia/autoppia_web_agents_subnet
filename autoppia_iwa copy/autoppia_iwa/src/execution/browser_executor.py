import asyncio
import base64
from datetime import datetime
from typing import List, Optional

from playwright.async_api import Page, async_playwright

from ..backend_demo_web.backend_demo_web_service import BackendDemoWebService
from ..data_generation.domain.classes import BrowserSpecification
from .actions.base import BaseAction
from .classes import ActionExecutionResult, BrowserSnapshot


class PlaywrightBrowserExecutor:
    def __init__(self, browser_config: BrowserSpecification, backend_demo_web_service: BackendDemoWebService, page: Optional[Page] = None):
        """
        Initializes the PlaywrightBrowserExecutor with a backend service and an optional Playwright page.

        Args:
            backend_demo_web_service: Service for interacting with the backend.
            page: Optional Playwright page object.
        """
        self.browser_config = browser_config
        self.page: Optional[Page] = page
        self.backend_demo_web_service = backend_demo_web_service
        self.action_execution_results: List[ActionExecutionResult] = []

    def execute_actions(self, actions: List[BaseAction], web_agent_id: str) -> List[ActionExecutionResult]:
        """
        Executes a list of actions synchronously using asyncio.

        Args:
            actions: List of actions to execute.
            web_agent_id: Identifier for the web agent.

        Returns:
            List[ActionExecutionResult]: List of execution results for each action.
        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.execute_actions_standalone(actions, web_agent_id))
        finally:
            asyncio.set_event_loop(None)
            loop.close()
        return result

    async def execute_actions_standalone(self, actions: List[BaseAction], web_agent_id: str) -> List[ActionExecutionResult]:
        """
        Executes a list of actions asynchronously.

        Args:
            actions: List of actions to execute.
            web_agent_id: Identifier for the web agent.

        Returns:
            List[ActionExecutionResult]: List of execution results for each action.
        """
        await self._initialize_playwright(web_agent_id)
        execution_results = []

        for iteration, action in enumerate(actions, start=1):
            execution_result = await self.execute_single_action(action, web_agent_id, iteration)
            execution_results.append(execution_result)

        return execution_results

    async def execute_single_action(self, action: BaseAction, web_agent_id: str, iteration: int) -> ActionExecutionResult:
        """
        Executes a single action and records results, including browser snapshots.

        Args:
            action: The action to execute.
            web_agent_id: Identifier for the web agent.
            iteration: The iteration number of the action.

        Returns:
            ActionExecutionResult: The result of the action execution.
        """
        if not self.page:
            raise RuntimeError("Playwright page is not initialized.")

        async def capture_snapshot() -> dict:
            """Helper function to capture browser state."""
            try:
                html = await self.page.content()
                screenshot = base64.b64encode(await self.page.screenshot(type="png", full_page=True)).decode("utf-8")
                current_url = self.page.url
                return {"html": html, "screenshot": screenshot, "url": current_url}
            except Exception as e:
                # Gracefully handle any errors during snapshot
                return {"html": "", "screenshot": "", "url": "", "error": str(e)}

        try:
            # Capture state before action execution
            snapshot_before = await capture_snapshot()
            start_time = datetime.now()

            # Execute the action
            await action.execute(self.page, self.backend_demo_web_service, web_agent_id)
            execution_time = (datetime.now() - start_time).total_seconds()

            # Capture backend events and updated browser state
            backend_events = self.backend_demo_web_service.get_backend_events(web_agent_id)
            await self.page.wait_for_load_state("domcontentloaded")
            snapshot_after = await capture_snapshot()

            # Create a detailed browser snapshot
            browser_snapshot = BrowserSnapshot(
                iteration=iteration,
                action=action,
                prev_html=snapshot_before["html"],
                current_html=snapshot_after["html"],
                backend_events=backend_events,
                timestamp=datetime.now(),
                current_url=snapshot_after["url"],
                screenshot_before=snapshot_before["screenshot"],
                screenshot_after=snapshot_after["screenshot"],
            )

            return ActionExecutionResult(
                action_event=action.__class__.__name__,
                is_successfully_executed=True,
                execution_time=execution_time,
                browser_snapshot=browser_snapshot,
                action=action,
            )

        except Exception as e:
            # Handle errors during action execution
            backend_events = self.backend_demo_web_service.get_backend_events(web_agent_id)
            snapshot_error = await capture_snapshot()

            # Create error snapshot
            browser_snapshot = BrowserSnapshot(
                iteration=iteration,
                action=action,
                prev_html=snapshot_error.get("html", ""),
                current_html=snapshot_error.get("html", ""),
                backend_events=backend_events,
                timestamp=datetime.now(),
                current_url=snapshot_error.get("url", ""),
                screenshot_before=snapshot_error.get("screenshot", ""),
                screenshot_after=snapshot_error.get("screenshot", ""),
            )

            return ActionExecutionResult(
                action_event=action.__class__.__name__,
                action=action,
                is_successfully_executed=False,
                error=str(e),
                execution_time=0,
                browser_snapshot=browser_snapshot,
            )

    async def _initialize_playwright(self, web_agent_id: str):
        """
        Initializes the Playwright browser and page if not already initialized.

        Args:
            web_agent_id: Identifier for the web agent.
        """
        if self.page:
            return

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(extra_http_headers={"X-WebAgent-Id": web_agent_id})
            context.set_default_timeout(5000)
            self.page = await context.new_page()
            await self.page.set_viewport_size({"width": self.browser_config.viewport_width, "height": self.browser_config.viewport_height})
