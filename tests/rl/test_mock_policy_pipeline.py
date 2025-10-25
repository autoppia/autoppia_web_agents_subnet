from __future__ import annotations

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_gym_stub() -> None:
    import importlib
    import types

    if "gymnasium" in sys.modules:
        return

    try:
        importlib.import_module("gymnasium")
        return
    except ModuleNotFoundError:
        pass

    class Env:  # pragma: no cover - compatibility stub
        metadata: dict[str, object] = {}

        def __init__(self, *_, **__):
            self.metadata = {}

        def reset(self, *, seed=None, options=None):  # pragma: no cover - stub
            return None

        def step(self, action):  # pragma: no cover - stub
            raise NotImplementedError

    class Discrete:
        def __init__(self, n: int):
            self.n = int(n)

    class Dict:
        def __init__(self, spaces_dict):
            self.spaces = dict(spaces_dict)

    spaces_module = types.ModuleType("gymnasium.spaces")
    spaces_module.Discrete = Discrete
    spaces_module.Dict = Dict

    gym_module = types.ModuleType("gymnasium")
    gym_module.Env = Env
    gym_module.spaces = spaces_module

    sys.modules["gymnasium"] = gym_module
    sys.modules["gymnasium.spaces"] = spaces_module


_ensure_gym_stub()


def test_mock_ppo_rollout_zero_reward():
    from rl.drivers.browser import Browser, BrowserAdapter
    from rl.envs import IWAWebEnv
    from rl.envs.types import BrowserInputsState, BrowserSnapshot, ElementMetadata, TaskSpec
    from rl.validator.iwa_evaluator_client import IWAValidator, ValidatorFeedback

    class StaticBrowserAdapter(BrowserAdapter):
        def __init__(self) -> None:
            self._snapshot = BrowserSnapshot(
                url="https://example.com",
                dom_text="Sample page",
                elements=[
                    ElementMetadata(
                        element_id="noop",
                        role="paragraph",
                        tag="p",
                        text="Nothing to do",
                        clickable=False,
                        focusable=False,
                    )
                ],
                inputs_state=BrowserInputsState(values={}),
                metadata={"can_go_back": False},
            )

        def reset(self, demo_web_id: str) -> BrowserSnapshot:
            return self._snapshot

        def snapshot(self) -> BrowserSnapshot:
            return self._snapshot

        def click(self, element_id: str) -> BrowserSnapshot:
            return self._snapshot

        def focus(self, element_id: str) -> BrowserSnapshot:
            return self._snapshot

        def type_and_confirm(self, text: str) -> BrowserSnapshot:
            return self._snapshot

        def submit(self) -> BrowserSnapshot:
            return self._snapshot

        def scroll(self, direction: str) -> BrowserSnapshot:
            return self._snapshot

        def back(self) -> BrowserSnapshot:
            return self._snapshot

    class ZeroValidatorClient:
        def __init__(self) -> None:
            self.evaluate_calls = 0

        def sample_task(self, options):
            return {
                "task_id": "static",
                "demo_web_id": "static_web",
                "goal": "Stay idle",
            }

        def evaluate_snapshot(self, task: TaskSpec, previous, current):
            self.evaluate_calls += 1
            return ValidatorFeedback(success=False, shaped_reward=0.0, milestones=[])

    browser = Browser(adapter=StaticBrowserAdapter())
    validator_client = ZeroValidatorClient()
    validator = IWAValidator(client=validator_client)
    env = IWAWebEnv(cfg={"max_steps": 5, "topk": 1}, browser=browser, validator=validator)

    class MockPPO:
        def __init__(self, action_space):
            self.action_space = action_space

        def predict(self, observation, state=None, mask=None, deterministic=True):
            # Always choose NOOP to emulate a non-trained policy.
            return np.array([0]), state

    policy = MockPPO(env.action_space)
    task_override = {
        "task_id": "static",
        "demo_web_id": "static_web",
        "goal": "Stay idle",
    }

    observation, info = env.reset(options={"task": task_override})
    total_reward = 0.0
    done = False
    steps = 0
    state = None

    while not done:
        action, state = policy.predict(observation, state=state, mask=info.get("action_mask"))
        observation, reward, terminated, truncated, info = env.step(int(action.item()))
        steps += 1
        total_reward += reward
        done = terminated or truncated
        if steps > env.max_steps + 1:  # pragma: no cover - safety guard
            break

    assert steps >= 1
    assert validator_client.evaluate_calls >= steps
    assert info.get("success") is False
    assert total_reward <= 0.0
