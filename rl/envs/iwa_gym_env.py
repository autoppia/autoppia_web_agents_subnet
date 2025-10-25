from __future__ import annotations

import enum
import random
from collections import Counter, deque
from typing import Deque, Mapping, Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .dom_ranker import rank_clickables
from .obs_builders import ObservationBuilder
from .rewards import RewardComputer
from .types import ActionResult, BrowserSnapshot, RankResult, TaskSpec
from ..drivers.browser import Browser
from ..validator.iwa_evaluator_client import IWAValidator


class MacroAction(enum.IntEnum):
    TYPE_CONFIRM = 0
    SUBMIT = 1
    SCROLL_UP = 2
    SCROLL_DOWN = 3
    BACK = 4


class IWAWebEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        cfg: Optional[Mapping[str, object]] = None,
        *,
        browser: Optional[Browser] = None,
        validator: Optional[IWAValidator] = None,
    ) -> None:
        super().__init__()
        self.cfg = dict(cfg or {})
        self.K = int(self.cfg.get("topk", 24))
        self.max_steps = int(self.cfg.get("max_steps", 50))
        self.loop_window = int(self.cfg.get("loop_window", 6))
        self.loop_threshold = int(self.cfg.get("loop_threshold", 3))

        obs_cfg = dict(self.cfg.get("observations") or {})
        reward_cfg = dict(self.cfg.get("rewards") or {})
        validator_cfg = dict(self.cfg.get("validator") or {})
        browser_cfg = dict(self.cfg.get("browser") or {})

        if browser is None:
            browser = Browser(config=browser_cfg)
        self.browser = browser

        self.validator = validator or IWAValidator(config=validator_cfg)
        self.reward_computer = RewardComputer(config=reward_cfg, validator=self.validator)
        self.observation_builder = ObservationBuilder(obs_cfg)

        self.action_history: Deque[int] = deque(maxlen=self.observation_builder.history_length)
        self.recent_signatures: Deque[str] = deque(maxlen=self.loop_window)

        self.task: Optional[TaskSpec] = None
        self.previous_snapshot: Optional[BrowserSnapshot] = None
        self.snapshot: Optional[BrowserSnapshot] = None
        self.rank: RankResult = RankResult(elements=[], click_mask=[], focus_mask=[])
        self.step_count = 0

        # Action space layout: [NOOP] + [CLICK_K] + [FOCUS_K] + macros
        self.action_offset_click = 1
        self.action_offset_focus = self.action_offset_click + self.K
        self.action_offset_macros = self.action_offset_focus + self.K
        self.action_space = spaces.Discrete(self.action_offset_macros + len(MacroAction))
        self.observation_space = self.observation_builder.space(self.action_space.n, self.K)

    # ------------------------------------------------------------------
    # Gym API
    # ------------------------------------------------------------------
    def reset(self, *, seed: Optional[int] = None, options: Optional[Mapping[str, object]] = None):
        super().reset(seed=seed)
        options = options or {}
        self.task = self._sample_task(options)
        self.browser.reset_to_demo(self.task.demo_web_id)
        self.snapshot = self.browser.snapshot
        self.previous_snapshot = None
        self.rank = rank_clickables(self.snapshot.elements, self.task, self.K)
        self.action_history.clear()
        self.recent_signatures.clear()
        self.step_count = 0

        obs = self._build_observation()
        info = {"task_id": self.task.task_id, "action_mask": self._action_mask()}
        return obs, info

    def step(self, action: int):
        if self.task is None or self.snapshot is None:
            raise RuntimeError("Environment must be reset before stepping")

        self.step_count += 1
        action = int(action)
        self.action_history.append(action)

        action_result = self._apply_action(action)
        self.previous_snapshot = self.snapshot
        self.snapshot = self.browser.snapshot
        self.rank = rank_clickables(self.snapshot.elements, self.task, self.K)

        loop_penalty = self._register_signature(action_result.signature)
        reward_signal = self.reward_computer.compute(
            task=self.task,
            previous=self.previous_snapshot,
            current=self.snapshot,
            invalid_action=action_result.invalid,
            loop_penalty=loop_penalty,
        )

        terminated = bool(reward_signal.success or reward_signal.invalid_episode)
        truncated = bool(self.step_count >= self.max_steps)
        obs = self._build_observation()
        info = {
            "success": reward_signal.success,
            "milestones": reward_signal.milestones,
            "action_mask": self._action_mask(),
            "invalid_action": action_result.invalid,
        }

        return obs, reward_signal.reward, terminated, truncated, info

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_observation(self):
        if self.task is None or self.snapshot is None:
            raise RuntimeError("Observation requested without an active task")
        return self.observation_builder.build(
            task=self.task,
            snapshot=self.snapshot,
            rank=self.rank,
            action_history=self.action_history,
            top_k=self.K,
        )

    def _sample_task(self, options: Mapping[str, object]) -> TaskSpec:
        if options:
            if "task" in options:
                return self._coerce_task_spec(options["task"])
            if "task_spec" in options:
                return self._coerce_task_spec(options["task_spec"])

        options = dict(options or {})
        if "index" not in options:
            options["index"] = random.randint(0, 10_000)
        return self.validator.sample_task(options)

    @staticmethod
    def _coerce_task_spec(value: object) -> TaskSpec:
        if isinstance(value, TaskSpec):
            return value
        if isinstance(value, Mapping):
            mapping = value
            try:
                task_id = str(mapping["task_id"])
                demo_web_id = str(mapping["demo_web_id"])
                goal = str(mapping["goal"])
            except KeyError as exc:  # pragma: no cover - defensive, validated by tests
                raise ValueError("Task specification mapping must include task_id, demo_web_id and goal") from exc
            metadata = dict(mapping.get("metadata") or {})
            return TaskSpec(task_id=task_id, demo_web_id=demo_web_id, goal=goal, metadata=metadata)
        raise TypeError(
            "Task specification must be a TaskSpec instance or a mapping with task_id/demo_web_id/goal"
        )

    def _register_signature(self, signature: str) -> bool:
        if not signature:
            return False
        self.recent_signatures.append(signature)
        counts = Counter(self.recent_signatures)
        return counts[signature] >= self.loop_threshold

    def _apply_action(self, action: int) -> ActionResult:
        if action == 0:
            return ActionResult(invalid=False, description="noop", signature="noop")

        if self.rank is None:
            raise RuntimeError("Rank is not initialized")

        if self.action_offset_click <= action < self.action_offset_focus:
            idx = action - self.action_offset_click
            element = self._element_from_rank(idx)
            if element is None or not element.clickable:
                return ActionResult(invalid=True, description="invalid_click", signature=f"click:{idx}")
            self.browser.click(element)
            return ActionResult(invalid=False, description="click", signature=f"click:{element.element_id}")

        if self.action_offset_focus <= action < self.action_offset_macros:
            idx = action - self.action_offset_focus
            element = self._element_from_rank(idx)
            if element is None or not element.focusable:
                return ActionResult(invalid=True, description="invalid_focus", signature=f"focus:{idx}")
            self.browser.focus(element)
            return ActionResult(invalid=False, description="focus", signature=f"focus:{element.element_id}")

        macro_index = action - self.action_offset_macros
        try:
            macro = MacroAction(macro_index)
        except ValueError as exc:
            raise ValueError(f"Unsupported macro action index: {macro_index}") from exc
        if macro is MacroAction.TYPE_CONFIRM:
            text = self._text_to_type()
            if not text:
                return ActionResult(invalid=True, description="empty_type", signature="type")
            self.browser.type_confirm(text)
            return ActionResult(invalid=False, description="type_confirm", signature="type")
        if macro is MacroAction.SUBMIT:
            if not self.browser.can_submit():
                return ActionResult(invalid=True, description="invalid_submit", signature="submit")
            self.browser.submit()
            return ActionResult(invalid=False, description="submit", signature="submit")
        if macro is MacroAction.SCROLL_UP:
            if not self.browser.can_scroll():
                return ActionResult(invalid=True, description="invalid_scroll_up", signature="scroll_up")
            self.browser.scroll("up")
            return ActionResult(invalid=False, description="scroll_up", signature="scroll_up")
        if macro is MacroAction.SCROLL_DOWN:
            if not self.browser.can_scroll():
                return ActionResult(invalid=True, description="invalid_scroll_down", signature="scroll_down")
            self.browser.scroll("down")
            return ActionResult(invalid=False, description="scroll_down", signature="scroll_down")
        if macro is MacroAction.BACK:
            if not self.browser.can_go_back():
                return ActionResult(invalid=True, description="invalid_back", signature="back")
            self.browser.back()
            return ActionResult(invalid=False, description="back", signature="back")

        raise ValueError(f"Unsupported action index: {action}")

    def _element_from_rank(self, idx: int):
        if idx < 0 or idx >= len(self.rank.elements):
            return None
        return self.rank.elements[idx].element

    def _text_to_type(self) -> str:
        if self.task is None:
            return ""
        metadata = self.task.metadata or {}
        if "type_text" in metadata:
            return str(metadata["type_text"])
        return self.task.goal

    def _action_mask(self) -> np.ndarray:
        mask = np.zeros(self.action_space.n, dtype=np.bool_)
        mask[0] = True  # NOOP is always allowed

        for idx in range(self.K):
            click_allowed = idx < len(self.rank.click_mask) and bool(self.rank.click_mask[idx])
            focus_allowed = idx < len(self.rank.focus_mask) and bool(self.rank.focus_mask[idx])
            mask[self.action_offset_click + idx] = click_allowed
            mask[self.action_offset_focus + idx] = focus_allowed

        mask[self.action_offset_macros + MacroAction.TYPE_CONFIRM] = self.browser.has_focusable_inputs()
        mask[self.action_offset_macros + MacroAction.SUBMIT] = self.browser.can_submit()
        mask[self.action_offset_macros + MacroAction.SCROLL_UP] = self.browser.can_scroll()
        mask[self.action_offset_macros + MacroAction.SCROLL_DOWN] = self.browser.can_scroll()
        mask[self.action_offset_macros + MacroAction.BACK] = self.browser.can_go_back()
        return mask


__all__ = ["IWAWebEnv", "MacroAction"]
