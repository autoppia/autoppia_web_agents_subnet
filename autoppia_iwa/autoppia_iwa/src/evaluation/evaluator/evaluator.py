import asyncio
import hashlib
import traceback
from collections import defaultdict
from typing import List, Optional

from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from autoppia_iwa.src.backend_demo_web.backend_demo_web_service import BackendDemoWebService
from autoppia_iwa.src.data_generation.domain.classes import BrowserSpecification, Task
from autoppia_iwa.src.evaluation.classes import EvaluationResult as BaseEvaluationResult
from autoppia_iwa.src.evaluation.classes import Feedback
from autoppia_iwa.src.evaluation.evaluator.feedback_generator import FeedbackGenerator
from autoppia_iwa.src.evaluation.evaluator.test_runner import TestRunner
from autoppia_iwa.src.evaluation.interfaces import IEvaluator
from autoppia_iwa.src.execution.actions.base import BaseAction
from autoppia_iwa.src.execution.browser_executor import PlaywrightBrowserExecutor
from autoppia_iwa.src.execution.classes import ActionExecutionResult
from autoppia_iwa.src.web_agents.classes import TaskSolution


class EvaluationResult(BaseEvaluationResult):
    # Extend the base model if needed to hold the web_agent_id
    web_agent_id: Optional[str] = None


class EvaluatorConfig(BaseModel):
    current_url: str
    save_results_in_db: bool = False
    task_delay_in_seconds: float = Field(default=0.2, gt=0)
    chunk_size: int = Field(default=3, gt=0)
    browser_timeout: float = Field(default=10000, gt=0)
    event_monitor_interval: float = Field(default=0.1, gt=0, le=0.5)


class ConcurrentEvaluator(IEvaluator):
    def __init__(self, config: EvaluatorConfig):
        self.config = config

    async def evaluate_single_task(self, task_solution: TaskSolution) -> EvaluationResult:
        return await self._evaluate_single_task(task_solution.task, task_solution.actions, task_solution.web_agent_id)

    async def evaluate_all_tasks(self, task_solutions: List[TaskSolution]) -> List[EvaluationResult]:
        return await self._group_and_evaluate_tasks(task_solutions)

    async def _group_and_evaluate_tasks(self, task_solutions: List[TaskSolution]) -> List[EvaluationResult]:
        grouped_tasks = defaultdict(list)
        for task_solution in task_solutions:
            grouped_tasks[self._hash_actions(task_solution.actions)].append(task_solution)

        semaphore = asyncio.Semaphore(self.config.chunk_size)
        group_tasks = [self._evaluate_group_with_semaphore(group, semaphore) for group in grouped_tasks.values()]

        raw_results = await asyncio.gather(*group_tasks, return_exceptions=True)
        final_results = []
        for result in raw_results:
            if isinstance(result, Exception):
                print(f"Exception occurred: {type(result).__name__}, {result}")
            else:
                final_results.extend(result)

        print(f"All tasks processed. Total tasks evaluated: {len(final_results)} / {len(task_solutions)}")
        return final_results

    async def _evaluate_group_with_semaphore(self, group: List[TaskSolution], semaphore: asyncio.Semaphore) -> List[EvaluationResult]:
        async with semaphore:
            representative = group[0]
            try:
                # Evaluate the representative actions
                rep_result = await self._evaluate_single_task(representative.task, representative.actions, representative.web_agent_id)
                # Clone results for each web_agent in the group
                results: List[EvaluationResult] = []
                for task_solution in group:
                    cloned_result = rep_result.copy(deep=True)
                    cloned_result.web_agent_id = task_solution.web_agent_id
                    results.append(cloned_result)

                return results
            except Exception as e:
                print(f"Error evaluating actions for group: {e}")
                print(traceback.format_exc())
                return [EvaluationResult(web_agent_id=ts.web_agent_id, final_score=0, test_results=[], feedback=None, execution_history=[]) for ts in group]

    @staticmethod
    def _hash_actions(actions: List[BaseAction]) -> str:
        try:
            return hashlib.sha256("|".join(str(action.model_dump()) for action in actions).encode()).hexdigest()
        except Exception:
            print("Error generating hash for actions.")
            return ""

    async def _evaluate_single_task(self, task: Task, actions: List[BaseAction], web_agent_id: str, delay: float = None) -> EvaluationResult:
        if not actions:
            return EvaluationResult(web_agent_id=web_agent_id, final_score=0, test_results=[], feedback=None, execution_history=[])

        if delay:
            await asyncio.sleep(delay)

        backend_service = BackendDemoWebService(task.url)
        backend_service.reset_backend_events_db(web_agent_id)

        execution_history = await self._evaluate_in_browser(task, web_agent_id, actions, backend_service)
        test_results = self._run_tests(task, execution_history)
        feedback = self._generate_feedback(task, execution_history, test_results)

        result = EvaluationResult(
            web_agent_id=web_agent_id,
            final_score=feedback.final_score,
            test_results=test_results,
            feedback=feedback,
            execution_history=execution_history,
        )

        # Example place to store in DB if config says so (but still return the same object)
        if self.config.save_results_in_db:
            # e.g. DatabaseService.save_result(result.model_dump())
            pass

        return result

    async def _evaluate_in_browser(self, task: Task, web_agent_id: str, actions: List[BaseAction], backend_service: BackendDemoWebService) -> List[ActionExecutionResult]:
        async with async_playwright() as playwright:
            browser, context = None, None
            try:
                browser = await playwright.chromium.launch(headless=True)
                context = await browser.new_context(extra_http_headers={"X-WebAgent-Id": web_agent_id})
                context.set_default_timeout(self.config.browser_timeout)
                page = await context.new_page()
                print(f"Started evaluation for task URL: {task.url}, Miner ID: {web_agent_id}")

                monitor_task = asyncio.create_task(self._monitor_browser(task.url, page, web_agent_id))
                browser_executor = PlaywrightBrowserExecutor(BrowserSpecification(), backend_service, page)

                try:
                    results = await browser_executor.execute_actions_standalone(actions, web_agent_id)
                finally:
                    monitor_task.cancel()
                    await asyncio.gather(monitor_task, return_exceptions=True)

                print(f"Completed evaluation for task URL: {task.url}, Miner ID: {web_agent_id}")
                return results

            except Exception as e:
                print(f"Error during browser evaluation for task URL: {task.url}, Miner ID: {web_agent_id}")
                print(f"Exception: {e}__{traceback.format_exc()}")
                return []
            finally:
                if context:
                    await context.close()
                if browser:
                    await browser.close()

    async def _monitor_browser(self, task_url, page, web_agent_id):
        def on_frame_navigated(frame):
            try:
                if frame.url:
                    asyncio.create_task(BackendDemoWebService(task_url).send_page_view_event(frame.url, web_agent_id))
            except Exception as e:
                print(f"Error handling frame navigation: {e}")

        page.on("framenavigated", on_frame_navigated)

        try:
            while not page.is_closed():
                await asyncio.sleep(self.config.event_monitor_interval)
        except asyncio.CancelledError:
            print("Monitoring stopped.")

    @staticmethod
    def _run_tests(task: Task, execution_history: List[ActionExecutionResult]) -> List:
        all_test_results = []
        for action_result in execution_history:
            snapshot = action_result.browser_snapshot
            test_runner = TestRunner(task.tests, snapshot)
            all_test_results.extend(test_runner.run_tests())
        return all_test_results

    @staticmethod
    def _generate_feedback(task: Task, execution_history: List[ActionExecutionResult], test_results: List) -> Feedback:
        return FeedbackGenerator().generate_feedback(task_prompt=task.prompt, execution_history=execution_history, test_results=test_results)
