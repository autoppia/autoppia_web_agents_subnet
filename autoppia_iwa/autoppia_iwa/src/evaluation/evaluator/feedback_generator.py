from collections import defaultdict
from typing import List

from ...execution.classes import ActionExecutionResult
from ..classes import Feedback, TestEvaluated


class FeedbackGenerator:
    @staticmethod
    def make_immutable(data):
        """Convert mutable types in extra_data to immutable ones."""
        if isinstance(data, dict):
            # Convert list values to tuples, then create a frozenset of key-value pairs
            return frozenset((key, tuple(value) if isinstance(value, list) else value) for key, value in data.items())
        return None

    @staticmethod
    def calculate_score(success_count: int, total_count: int, scale: int = 10) -> float:
        """Calculate a score based on the ratio of successes to the total count."""
        return (success_count / total_count) * scale if total_count > 0 else 0

    @staticmethod
    def group_test_results(test_results: List['TestEvaluated']) -> dict:
        """
        Group tests by (description, test_type, extra_data).

        Each group represents a unique test. A group is considered passed if any execution is successful.
        """
        grouped_tests = defaultdict(list)
        for test in test_results:
            key = (test.description, test.test_type, FeedbackGenerator.make_immutable(test.extra_data))
            grouped_tests[key].append(test.is_success)
        return grouped_tests

    @staticmethod
    def calculate_test_score(grouped_tests: dict) -> tuple[int, int, float]:
        """
        Calculate the test score based on the grouped tests.

        Returns:
            passed_tests (int): Number of test groups that passed.
            failed_tests (int): Number of test groups that failed.
            test_score (float): Score calculated from the ratio of passed tests.
        """
        passed_tests = sum(1 for results in grouped_tests.values() if any(results))
        total_tests = len(grouped_tests)

        # Only if all groups passed, calculate the score normally.
        if passed_tests < total_tests:
            test_score = 0.0
        else:
            test_score = FeedbackGenerator.calculate_score(passed_tests, total_tests)

        failed_tests = total_tests - passed_tests
        return passed_tests, failed_tests, test_score

    @staticmethod
    def calculate_critical_failures(grouped_tests: dict) -> int:
        """
        Calculate the number of critical failures.

        A critical failure is counted when the immutable extra_data contains the key 'event_name'
        and the corresponding test group did not pass.
        """
        critical_failures = 0
        for key, results in grouped_tests.items():
            # key structure: (description, test_type, immutable_extra_data)
            immutable_extra_data = key[2]
            if immutable_extra_data is not None:
                if any(k == 'event_name' for k, v in immutable_extra_data) and not any(results):
                    critical_failures += 1
        return critical_failures

    @staticmethod
    def calculate_time_penalty(total_execution_time: float, expected_time: float) -> float:
        """
        Calculate the time penalty based on the extra execution time.

        For every 5 extra seconds beyond the expected time, 0.5 points are subtracted.
        """
        extra_time = total_execution_time - expected_time

        return max(0, (extra_time / 5.0) * 0.5)

    @staticmethod
    def generate_feedback(
        task_prompt: str,
        execution_history: List['ActionExecutionResult'],
        test_results: List['TestEvaluated'],
        expected_time: float = 50.0,
    ) -> 'Feedback':
        """
        Generates structured feedback for the task evaluation.

        Args:
            task_prompt (str): The description of the evaluated task.
            execution_history (List[ActionExecutionResult]): History of executed actions.
            test_results (List[TestEvaluated]): Results of the evaluated tests.
            expected_time (float): The expected time to complete the task (in seconds).

        Returns:
            Feedback: Structured feedback object summarizing the evaluation.
        """

        # ---------------------------
        # Action execution metrics
        # ---------------------------
        total_actions = len(execution_history)
        successful_actions = sum(1 for record in execution_history if record.is_successfully_executed)
        failed_actions = total_actions - successful_actions

        # Adjust expected time based on the number of actions
        if total_actions > 5:
            expected_time = total_actions * 5  # Allow 5 seconds per action

        # ---------------------------
        # Test results processing
        # ---------------------------
        # Group tests by (description, test_type, extra_data)
        grouped_tests = FeedbackGenerator.group_test_results(test_results)
        passed_tests, failed_tests, test_score = FeedbackGenerator.calculate_test_score(grouped_tests)

        # Calculate critical failure penalty: 2 point for each critical failure
        critical_failures = FeedbackGenerator.calculate_critical_failures(grouped_tests)
        critical_penalty = critical_failures * 2

        # ---------------------------
        # Time penalty calculation
        # ---------------------------
        total_execution_time = sum(record.execution_time for record in execution_history if record.execution_time)
        time_penalty = FeedbackGenerator.calculate_time_penalty(total_execution_time, expected_time)

        # ---------------------------
        # Final score calculation
        # ---------------------------
        final_score = test_score  # - critical_penalty - time_penalty
        final_score = max(0, min(10, final_score))
        final_score = round(final_score, 1)

        # ---------------------------
        # Return the structured feedback
        # ---------------------------
        return Feedback(
            task_prompt=task_prompt,
            final_score=final_score,
            executed_actions=successful_actions,
            failed_actions=failed_actions,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            total_execution_time=total_execution_time,
            time_penalty=round(time_penalty, 1),
            critical_test_penalty=critical_penalty,
            test_results=test_results,
            execution_history=execution_history,
        )
