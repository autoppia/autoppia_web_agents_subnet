import os
import sys
import math
import importlib
import importlib.util
import types

# Ensure repository root on path for package imports
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _get_penalties_module():
    # Provide a minimal package structure and config stub so the module can import
    pkg_name = 'autoppia_web_agents_subnet'
    subpkg_name = 'autoppia_web_agents_subnet.validator'
    cfg_name = 'autoppia_web_agents_subnet.validator.config'

    if pkg_name not in sys.modules:
        pkg_mod = types.ModuleType(pkg_name)
        pkg_mod.__path__ = [os.path.join(ROOT_DIR, 'autoppia_web_agents_subnet')]
        sys.modules[pkg_name] = pkg_mod
    if subpkg_name not in sys.modules:
        subpkg_mod = types.ModuleType(subpkg_name)
        subpkg_mod.__path__ = [os.path.join(ROOT_DIR, 'autoppia_web_agents_subnet', 'validator')]
        sys.modules[subpkg_name] = subpkg_mod
    # Create or update config stub
    cfg_mod = sys.modules.get(cfg_name) or types.ModuleType(cfg_name)
    if not hasattr(cfg_mod, 'SAME_SOLUTION_PENALTY'):
        cfg_mod.SAME_SOLUTION_PENALTY = 0.0
    if not hasattr(cfg_mod, 'SAME_SOLUTION_SIM_THRESHOLD'):
        cfg_mod.SAME_SOLUTION_SIM_THRESHOLD = 0.95
    sys.modules[cfg_name] = cfg_mod

    path = os.path.join(ROOT_DIR, 'autoppia_web_agents_subnet', 'validator', 'penalties.py')
    spec = importlib.util.spec_from_file_location('penalties_test', path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# ------------------------------
# Simple mocks for actions/solutions
# ------------------------------


class MockSelector:
    def __init__(self, type=None, attribute=None, value=None):
        self.type = type
        self.attribute = attribute
        self.value = value


class MockAction:
    def __init__(self, *, type, selector=None, text=None, value=None, url=None, x=None, y=None, up=False, down=False, left=False, right=False, time_seconds=None):
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
        MockAction(type='clickaction', selector=MockSelector(type='attribute', attribute='data-testid', value='login-btn')),
        MockAction(type='typeaction', selector=MockSelector(type='attribute', attribute='name', value='username'), text='user1'),
        MockAction(type='typeaction', selector=MockSelector(type='attribute', attribute='name', value='password'), text='pass1234'),
        MockAction(type='clickaction', selector=MockSelector(type='attribute', attribute='data-testid', value='submit')),
        MockAction(type='waitaction', time_seconds=1.2),
    ]
    return MockSolution(actions), MockSolution(list(actions))


def _different_pair():
    a1 = [
        MockAction(type='navigateaction', url='https://example.com/login'),
        MockAction(type='typeaction', selector=MockSelector(type='attribute', attribute='name', value='email'), text='a@example.com'),
        MockAction(type='clickaction', selector=MockSelector(type='attribute', attribute='data-testid', value='go')),
    ]
    a2 = [
        MockAction(type='navigateaction', url='https://shop.example.com'),
        MockAction(type='clickaction', selector=MockSelector(type='attribute', attribute='data-testid', value='product')),
        MockAction(type='clickaction', selector=MockSelector(type='attribute', attribute='data-testid', value='checkout')),
    ]
    return MockSolution(a1), MockSolution(a2)


def _similar_but_not_identical():
    base = [
        MockAction(type='clickaction', selector=MockSelector(type='attribute', attribute='data-testid', value='search')),
        MockAction(type='typeaction', selector=MockSelector(type='attribute', attribute='name', value='q'), text='python tutorial'),
        MockAction(type='clickaction', selector=MockSelector(type='attribute', attribute='data-testid', value='submit')),
    ]
    s1 = MockSolution(base + [MockAction(type='waitaction', time_seconds=2.0)])
    s2 = MockSolution(base + [MockAction(type='scrollaction', down=True)])
    return s1, s2


def test_identical_solutions_are_penalized():
    penalties = _get_penalties_module()
    penalties.SAME_SOLUTION_SIM_THRESHOLD = 0.90
    penalties.SAME_SOLUTION_PENALTY = 0.0

    s1, s2 = _identical_pair()
    scores = [0.92, 0.87]
    out = penalties.apply_same_solution_penalty([s1, s2], scores)
    assert out.shape[0] == 2
    assert math.isclose(float(out[0]), 0.0, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[1]), 0.0, rel_tol=1e-6, abs_tol=1e-6)


def test_different_solutions_not_penalized():
    penalties = _get_penalties_module()
    penalties.SAME_SOLUTION_SIM_THRESHOLD = 0.90
    penalties.SAME_SOLUTION_PENALTY = 0.0

    s1, s2 = _different_pair()
    scores = [0.75, 0.66]
    out = penalties.apply_same_solution_penalty([s1, s2], scores)
    assert math.isclose(float(out[0]), 0.75, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[1]), 0.66, rel_tol=1e-6, abs_tol=1e-6)


def test_similar_below_threshold_not_penalized():
    # Keep threshold very strict to avoid false positives
    penalties = _get_penalties_module()
    penalties.SAME_SOLUTION_SIM_THRESHOLD = 0.99
    penalties.SAME_SOLUTION_PENALTY = 0.0

    s1, s2 = _similar_but_not_identical()
    scores = [0.83, 0.81]
    out = penalties.apply_same_solution_penalty([s1, s2], scores)
    assert math.isclose(float(out[0]), 0.83, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[1]), 0.81, rel_tol=1e-6, abs_tol=1e-6)


def test_only_duplicates_in_group_are_penalized():
    # Use penalty 0.5 so we can observe scaling (vs zeroing)
    penalties = _get_penalties_module()
    penalties.SAME_SOLUTION_SIM_THRESHOLD = 0.90
    penalties.SAME_SOLUTION_PENALTY = 0.5

    a, b = _identical_pair()
    c1, _ = _different_pair()
    solutions = [a, b, c1]
    scores = [0.80, 0.70, 0.60]
    out = penalties.apply_same_solution_penalty(solutions, scores)
    # First two should be scaled by 0.5; third unchanged
    assert math.isclose(float(out[0]), 0.40, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[1]), 0.35, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(out[2]), 0.60, rel_tol=1e-6, abs_tol=1e-6)
