from typing import List, Optional

from pydantic import BaseModel

from autoppia_iwa.src.execution.classes import ActionExecutionResult


class TestEvaluated(BaseModel):
    """Represents the evaluation result of a single test."""

    description: str  # Description of the test
    test_type: str  # Type of the test (e.g., "frontend", "backend")
    is_success: bool  # True if the test passed, False otherwise
    extra_data: Optional[dict] = None  # Additional data related to the test


class Feedback(BaseModel):
    task_prompt: str  # The description of the task being evaluated
    final_score: float  # Overall evaluation score (0-10)
    executed_actions: int  # Number of successfully executed actions
    failed_actions: int  # Number of failed actions
    passed_tests: int  # Number of tests that passed
    failed_tests: int  # Number of tests that failed
    total_execution_time: float  # Total time taken for execution
    time_penalty: float  # Penalty points for exceeding expected time
    critical_test_penalty: int  # Penalty points for failing critical tests
    test_results: List[TestEvaluated]  # Detailed test results
    execution_history: List[ActionExecutionResult]  # Detailed execution logs

    def to_text(self) -> str:
        """Generates a human-readable textual summary."""
        feedback = f"Task: '{self.task_prompt}'\n"
        feedback += f"Final Score: {self.final_score}/10\n"
        feedback += f"Executed Actions: {self.executed_actions}, Failed Actions: {self.failed_actions}\n"
        feedback += f"Tests Passed: {self.passed_tests}, Tests Failed: {self.failed_tests}\n"
        feedback += f"Total Execution Time: {self.total_execution_time:.2f}s\n"
        feedback += f"Time Penalty: {self.time_penalty:.1f} points\n"
        feedback += f"Critical Test Penalty: {self.critical_test_penalty} points\n"
        feedback += "\nTest Results:\n"
        for test in self.test_results:
            feedback += f"  - Test '{test.description}' ({test.test_type}): {'PASSED' if test.is_success else 'FAILED'}\n"
            if test.extra_data:
                feedback += f"      Extra Data: {test.extra_data}\n"

        feedback += "\nExecution History:\n"
        for record in self.execution_history:
            feedback += f"  - Action: {record.action_event}, Success: {record.is_successfully_executed}, Time: {record.execution_time:.2f}s\n"
            if record.error:
                feedback += f"      Error: {record.error}\n"

        return feedback


class EvaluationResult(BaseModel):
    """Encapsulates the output of a task evaluation."""

    final_score: float = 0
    test_results: List[TestEvaluated]  # List of test evaluation results
    execution_history: List[ActionExecutionResult]  # History of all actions executed
    feedback: Optional[Feedback] = None  # Feedback generated during the evaluation

    def model_dump(self, *args, **kwargs):
        base_dump = super().model_dump(*args, **kwargs)
        base_dump["execution_history"] = [action.model_dump() for action in self.execution_history]
        # Remove unwanted keys from feedback
        base_dump["feedback"].pop("execution_history", None)
        base_dump["feedback"].pop("test_results", None)
        return base_dump
