import math

import pytest

from autoppia_web_agents_subnet.validator import penalties


class MockSelector:
    def __init__(self, type=None, attribute=None, value=None):
        self.type = type
        self.attribute = attribute
        self.value = value


class MockAction:
    def __init__(
        self,
        *,
        type: str,
        selector=None,
        text=None,
        value=None,
        url=None,
        x=None,
        y=None,
        up=False,
        down=False,
        left=False,
        right=False,
        time_seconds=None,
    ) -> None:
        self.type = type
        self.selector = selector
        self.text = text
        self.value = value
        self.url = url
        self.x = x
        self.y = y
        self.up = up
        self.down = down
        self.left = left
        self.right = right
        self.time_seconds = time_seconds


class MockSolution:
    def __init__(self, actions):
        self.actions = actions


def _identical_pair():
    actions = [
        MockAction(type="clickaction", selector=MockSelector(type="attribute", attribute="data-testid", value="login-btn")),
        MockAction(type="typeaction", selector=MockSelector(type="attribute", attribute="name", value="username"), text="user1"),
        MockAction(type="typeaction", selector=MockSelector(type="attribute", attribute="name", value="password"), text="pass1234"),
    ]
    return MockSolution(actions), MockSolution(list(actions))


def _different_pair():
    a1 = [
        MockAction(type="navigateaction", url="https://example.com/login"),
        MockAction(type="typeaction", selector=MockSelector(type="attribute", attribute="name", value="email"), text="a@example.com"),
    ]
    a2 = [
        MockAction(type="navigateaction", url="https://shop.example.com"),
        MockAction(type="clickaction", selector=MockSelector(type="attribute", attribute="data-testid", value="product")),
    ]
    return MockSolution(a1), MockSolution(a2)


def _similar_but_not_identical():
    base = [
        MockAction(type="clickaction", selector=MockSelector(type="attribute", attribute="data-testid", value="search")),
        MockAction(type="typeaction", selector=MockSelector(type="attribute", attribute="name", value="q"), text="python tutorial"),
    ]
    s1 = MockSolution(base + [MockAction(type="waitaction", time_seconds=2.0)])
    s2 = MockSolution(base + [MockAction(type="scrollaction", down=True)])
    return s1, s2


@pytest.fixture(autouse=True)
def reset_penalty_config(monkeypatch):
    monkeypatch.setattr(penalties, "SAME_SOLUTION_SIM_THRESHOLD", 0.90, raising=False)
    monkeypatch.setattr(penalties, "SAME_SOLUTION_PENALTY", 0.0, raising=False)


def test_identical_solutions_are_penalized():
    penalties.SAME_SOLUTION_PENALTY = 0.0
    s1, s2 = _identical_pair()
    scores = [0.92, 0.87]
    out = penalties.apply_same_solution_penalty([s1, s2], scores)
    assert math.isclose(float(out[0]), 0.0, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[1]), 0.0, rel_tol=1e-6, abs_tol=1e-6)


def test_different_solutions_not_penalized():
    s1, s2 = _different_pair()
    scores = [0.75, 0.66]
    out = penalties.apply_same_solution_penalty([s1, s2], scores)
    assert math.isclose(float(out[0]), 0.75, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[1]), 0.66, rel_tol=1e-6, abs_tol=1e-6)


def test_similar_below_threshold_not_penalized():
    penalties.SAME_SOLUTION_SIM_THRESHOLD = 0.99
    s1, s2 = _similar_but_not_identical()
    scores = [0.83, 0.81]
    out = penalties.apply_same_solution_penalty([s1, s2], scores)
    assert math.isclose(float(out[0]), 0.83, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[1]), 0.81, rel_tol=1e-6, abs_tol=1e-6)


def test_groups_metadata_returned():
    penalties.SAME_SOLUTION_PENALTY = 0.5
    a, b = _identical_pair()
    c1, _ = _different_pair()
    solutions = [a, b, c1]
    scores = [0.80, 0.70, 0.60]
    penalized, groups = penalties.apply_same_solution_penalty_with_meta(solutions, scores)
    assert groups and groups[0] == [0, 1]
    assert math.isclose(float(penalized[0]), 0.40, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(penalized[1]), 0.35, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(penalized[2]), 0.60, rel_tol=1e-6, abs_tol=1e-6)
