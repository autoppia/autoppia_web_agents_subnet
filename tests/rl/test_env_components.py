from __future__ import annotations

from collections import deque
import pathlib
import sys

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

    class Env:
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

from rl.drivers.browser import Browser
from rl.envs.dom_ranker import rank_clickables
from rl.envs.obs_builders import ObservationBuilder
from rl.envs.rewards import RewardComputer
from rl.envs.types import (
    BrowserInputsState,
    BrowserSnapshot,
    ElementMetadata,
    RankResult,
    TaskSpec,
)
from rl.validator.iwa_evaluator_client import ValidatorFeedback


class StubBrowserAdapter:
    def __init__(self) -> None:
        self._snapshot = BrowserSnapshot(
            url="https://demo",
            dom_text="Go to checkout",
            elements=[
                ElementMetadata(
                    element_id="link",
                    role="link",
                    tag="a",
                    text="Checkout",
                    clickable=True,
                    focusable=False,
                    is_in_viewport=True,
                )
            ],
        )

    def reset(self, demo_web_id: str) -> BrowserSnapshot:
        return self._snapshot

    def snapshot(self) -> BrowserSnapshot:
        return self._snapshot

    def click(self, element_id: str) -> BrowserSnapshot:
        self._snapshot.metadata["clicked"] = element_id
        return self._snapshot

    def focus(self, element_id: str) -> BrowserSnapshot:
        self._snapshot.metadata["focused"] = element_id
        return self._snapshot

    def type_and_confirm(self, text: str) -> BrowserSnapshot:
        self._snapshot.inputs_state.values["field"] = text
        return self._snapshot

    def submit(self) -> BrowserSnapshot:
        self._snapshot.metadata["submitted"] = True
        return self._snapshot

    def scroll(self, direction: str) -> BrowserSnapshot:
        self._snapshot.metadata["scrolled"] = direction
        return self._snapshot

    def back(self) -> BrowserSnapshot:
        self._snapshot.metadata["back"] = True
        return self._snapshot


@pytest.fixture
def sample_task() -> TaskSpec:
    return TaskSpec(task_id="t1", demo_web_id="demo", goal="Submit the checkout form")


@pytest.fixture
def sample_elements() -> list[ElementMetadata]:
    return [
        ElementMetadata(
            element_id="button",
            role="button",
            tag="button",
            text="Submit order",
            clickable=True,
            focusable=False,
            is_in_viewport=True,
        ),
        ElementMetadata(
            element_id="input",
            role="textbox",
            tag="input",
            text="Email",
            clickable=True,
            focusable=True,
            editable=True,
            is_in_viewport=True,
        ),
        ElementMetadata(
            element_id="hidden",
            role="button",
            tag="button",
            text="Hidden",
            clickable=True,
            focusable=False,
            is_visible=False,
        ),
    ]


def test_rank_clickables_orders_visible_elements(sample_task: TaskSpec, sample_elements: list[ElementMetadata]):
    rank = rank_clickables(sample_elements, sample_task, top_k=3)
    element_ids = [item.element.element_id for item in rank.elements]
    assert element_ids == ["input", "button"]
    assert rank.click_mask == [True, True]
    assert rank.focus_mask == [True, False]


def test_observation_builder_shapes(sample_task: TaskSpec, sample_elements: list[ElementMetadata]):
    builder = ObservationBuilder({})
    rank = RankResult(
        elements=rank_clickables(sample_elements, sample_task, top_k=2).elements,
        click_mask=[True, True],
        focus_mask=[False, True],
    )
    snapshot = BrowserSnapshot(
        url="https://demo/step",
        dom_text="Submit order now",
        elements=sample_elements,
        inputs_state=BrowserInputsState(values={"input": "user@example.com"}),
        cart_items=2,
    )
    history = deque([1, 2, 3], maxlen=builder.history_length)
    obs = builder.build(sample_task, snapshot, rank, history, top_k=3)

    assert obs["goal_ids"].shape == (builder.max_goal_tokens,)
    assert obs["dom_ids"].shape == (builder.max_dom_tokens,)
    assert obs["topk_meta"].shape == (3, builder.topk_meta_dim)
    assert obs["topk_text_ids"].shape == (3, builder.max_element_tokens)
    assert obs["prev_actions"].shape == (builder.history_length,)
    assert obs["inputs_filled_ratio"].item() > 0.0
    assert obs["cart_items"].item() == pytest.approx(2.0)


def test_reward_computer_combines_milestones(sample_task: TaskSpec):
    previous = BrowserSnapshot(
        url="https://demo/start",
        dom_text="Start",
        elements=[],
        inputs_state=BrowserInputsState(values={"input": ""}),
        cart_items=0,
    )
    current = BrowserSnapshot(
        url="https://demo/finish",
        dom_text="Finish",
        elements=[],
        inputs_state=BrowserInputsState(values={"input": "value"}),
        cart_items=1,
    )

    class DummyValidator:
        def evaluate(self, task: TaskSpec, previous, current):
            return ValidatorFeedback(success=True, shaped_reward=0.5, milestones=["validator"])

    computer = RewardComputer(
        config={
            "success_reward": 1.0,
            "milestone_reward": 0.1,
            "step_penalty": 0.01,
        },
        validator=DummyValidator(),
    )

    signal = computer.compute(sample_task, previous, current)
    assert pytest.approx(signal.reward, rel=1e-6) == 1.79
    assert signal.success
    assert "url_changed" in signal.milestones
    assert "input_filled:input" in signal.milestones
    assert "cart_increase" in signal.milestones
    assert "validator" in signal.milestones


def test_browser_instantiates_adapter_from_config():
    browser = Browser(
        config={
            "adapter": {
                "class": "tests.rl.test_env_components:StubBrowserAdapter",
            }
        }
    )

    snapshot = browser.reset_to_demo("demo")
    assert snapshot.url == "https://demo"

    element = browser.get_visible_elements()[0]
    browser.click(element)
    assert browser.snapshot.metadata["clicked"] == "link"
