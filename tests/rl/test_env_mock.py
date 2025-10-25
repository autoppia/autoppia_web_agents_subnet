from __future__ import annotations

import pathlib
import sys
from typing import TYPE_CHECKING

import pytest

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

    class Env:  # minimal stub
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

    class Box:
        def __init__(self, low, high, shape, dtype):
            self.low = low
            self.high = high
            self.shape = shape
            self.dtype = dtype

    class Dict:
        def __init__(self, spaces_dict):
            self.spaces = dict(spaces_dict)

        def items(self):
            return self.spaces.items()

        def __getitem__(self, key):
            return self.spaces[key]

    spaces_module = types.ModuleType("gymnasium.spaces")
    spaces_module.Discrete = Discrete
    spaces_module.Box = Box
    spaces_module.Dict = Dict

    gym_module = types.ModuleType("gymnasium")
    gym_module.Env = Env
    gym_module.spaces = spaces_module

    sys.modules["gymnasium"] = gym_module
    sys.modules["gymnasium.spaces"] = spaces_module


_ensure_gym_stub()

if TYPE_CHECKING:  # pragma: no cover - import for type hints only
    from rl.drivers.browser import BrowserAdapter
    from rl.envs.types import BrowserInputsState, BrowserSnapshot, ElementMetadata, TaskSpec
    from rl.validator.iwa_evaluator_client import IWAValidator, ValidatorFeedback


def test_env_reset_and_step():
    from rl.drivers.browser import Browser, BrowserAdapter
    from rl.envs import IWAWebEnv, MacroAction
    from rl.envs.types import BrowserInputsState, BrowserSnapshot, ElementMetadata, TaskSpec
    from rl.validator.iwa_evaluator_client import IWAValidator, ValidatorFeedback

    class MockBrowserAdapter(BrowserAdapter):
        def __init__(self) -> None:
            self.reset("demo")

        def reset(self, demo_web_id: str) -> BrowserSnapshot:  # noqa: D401 - part of protocol
            self._typed = False
            self._submitted = False
            self._elements = [
                ElementMetadata(
                    element_id="btn",
                    role="button",
                    tag="button",
                    text="Submit",
                    clickable=True,
                    focusable=False,
                ),
                ElementMetadata(
                    element_id="input",
                    role="textbox",
                    tag="input",
                    text="",
                    clickable=True,
                    focusable=True,
                    editable=True,
                ),
            ]
            self._snapshot = BrowserSnapshot(
                url="https://example.com",
                dom_text="Submit form",
                elements=list(self._elements),
                inputs_state=BrowserInputsState(values={}),
                metadata={},
            )
            return self._snapshot

        def snapshot(self) -> BrowserSnapshot:
            return self._snapshot

        def click(self, element_id: str) -> BrowserSnapshot:
            snapshot = self._clone_snapshot()
            snapshot.metadata["clicked"] = element_id
            self._snapshot = snapshot
            return snapshot

        def focus(self, element_id: str) -> BrowserSnapshot:
            snapshot = self._clone_snapshot()
            snapshot.metadata["focused"] = element_id
            self._snapshot = snapshot
            return snapshot

        def type_and_confirm(self, text: str) -> BrowserSnapshot:
            self._typed = True
            snapshot = self._clone_snapshot()
            snapshot.inputs_state.values["input"] = text
            snapshot.metadata["typed"] = True
            self._snapshot = snapshot
            return snapshot

        def submit(self) -> BrowserSnapshot:
            self._submitted = True
            snapshot = self._clone_snapshot()
            snapshot.metadata["submitted"] = True
            self._snapshot = snapshot
            return snapshot

        def scroll(self, direction: str) -> BrowserSnapshot:
            snapshot = self._clone_snapshot()
            snapshot.metadata["scrolled"] = direction
            self._snapshot = snapshot
            return snapshot

        def back(self) -> BrowserSnapshot:
            snapshot = self._clone_snapshot()
            snapshot.metadata["went_back"] = True
            self._snapshot = snapshot
            return snapshot

        def _clone_snapshot(self) -> BrowserSnapshot:
            return BrowserSnapshot(
                url=self._snapshot.url,
                dom_text=self._snapshot.dom_text,
                elements=list(self._elements),
                inputs_state=BrowserInputsState(values=dict(self._snapshot.inputs_state.values)),
                cart_items=self._snapshot.cart_items,
                metadata=dict(self._snapshot.metadata),
            )

    class MockValidatorClient:
        def sample_task(self, options):
            return {
                "task_id": "1",
                "demo_web_id": "demo",
                "goal": "Submit the form",
            }

        def evaluate_snapshot(self, task: TaskSpec, previous, current):
            success = bool(current.metadata.get("submitted"))
            shaped_reward = 0.1 if current.metadata.get("typed") else 0.0
            milestones = ["typed"] if shaped_reward else []
            if success:
                milestones.append("submitted")
            return ValidatorFeedback(success=success, shaped_reward=shaped_reward, milestones=milestones)

    browser = Browser(adapter=MockBrowserAdapter())
    validator = IWAValidator(client=MockValidatorClient())
    env = IWAWebEnv(cfg={"topk": 2}, browser=browser, validator=validator)

    obs, info = env.reset()
    assert "action_mask" in info
    assert obs["topk_meta"].shape == (env.K, env.observation_builder.topk_meta_dim)

    mask = info["action_mask"]
    click_action = env.action_offset_click
    assert mask[click_action]

    obs, reward, terminated, truncated, info = env.step(int(click_action))
    assert isinstance(obs, dict)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert "action_mask" in info

    invalid_focus_action = env.action_offset_focus
    obs, reward, terminated, truncated, info = env.step(int(invalid_focus_action))
    assert info["invalid_action"]
    assert reward < 0.0
    assert not terminated

    valid_focus_action = env.action_offset_focus + 1
    assert info["action_mask"][valid_focus_action]
    obs, reward, terminated, truncated, info = env.step(int(valid_focus_action))
    assert not info["invalid_action"]

    type_action = env.action_offset_macros + MacroAction.TYPE_CONFIRM
    assert info["action_mask"][type_action]
    obs, reward, terminated, truncated, info = env.step(int(type_action))
    assert "typed" in info["milestones"] or reward > 0.0

    submit_action = env.action_offset_macros + MacroAction.SUBMIT
    assert info["action_mask"][submit_action]
    obs, reward, terminated, truncated, info = env.step(int(submit_action))
    assert terminated
    assert info["success"]
