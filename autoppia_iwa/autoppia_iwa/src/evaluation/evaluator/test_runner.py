from typing import List

from autoppia_iwa.src.data_generation.domain.classes import BaseTaskTest
from autoppia_iwa.src.execution.classes import BrowserSnapshot

from ..classes import TestEvaluated


class TestRunner:
    def __init__(self, tests: List[BaseTaskTest], browser_snapshot: BrowserSnapshot):
        self.tests = tests
        self.browser_snapshot = browser_snapshot

    def run_tests(self) -> List[TestEvaluated]:
        results = []
        for test in self.tests:
            success = test.execute_test(self.browser_snapshot)

            # Create TestEvaluated instance with extra_data
            evaluated_test = TestEvaluated(
                description=test.description,
                test_type=test.test_type,
                is_success=success,
                extra_data={key: value for key, value in test.model_dump().items() if key not in {"description", "test_type"}},
            )
            results.append(evaluated_test)

        return results
