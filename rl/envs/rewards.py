from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .types import BrowserSnapshot, RewardSignal, TaskSpec
from ..validator.iwa_evaluator_client import IWAValidator, ValidatorFeedback


@dataclass
class RewardConfig:
    success_reward: float = 1.0
    milestone_reward: float = 0.1
    step_penalty: float = 0.001
    invalid_action_penalty: float = 0.05
    loop_penalty: float = 0.05

    @classmethod
    def from_mapping(cls, mapping: Optional[Mapping[str, float]]) -> "RewardConfig":
        if mapping is None:
            return cls()
        params = {}
        for field in cls.__dataclass_fields__.values():
            value = mapping.get(field.name, getattr(cls, field.name))
            if value is None:
                value = getattr(cls, field.name)
            params[field.name] = float(value)
        return cls(**params)


class RewardComputer:
    def __init__(self, config: Optional[Mapping[str, float]] = None, validator: Optional[IWAValidator] = None):
        self.cfg = RewardConfig.from_mapping(config)
        self.validator = validator

    def compute(
        self,
        task: TaskSpec,
        previous: Optional[BrowserSnapshot],
        current: BrowserSnapshot,
        *,
        invalid_action: bool = False,
        loop_penalty: bool = False,
    ) -> RewardSignal:
        reward = -self.cfg.step_penalty
        milestones: list[str] = []

        if previous is not None:
            if previous.url != current.url and current.url:
                reward += self.cfg.milestone_reward
                milestones.append("url_changed")

            inputs_delta = current.inputs_state.diff(previous.inputs_state)
            for key, (_, after) in inputs_delta.items():
                if after:
                    reward += self.cfg.milestone_reward
                    milestones.append(f"input_filled:{key}")

            if current.cart_items > previous.cart_items:
                reward += self.cfg.milestone_reward
                milestones.append("cart_increase")

        feedback = ValidatorFeedback()
        if self.validator is not None:
            feedback = self.validator.evaluate(task=task, previous=previous, current=current)
            if feedback.shaped_reward:
                reward += float(feedback.shaped_reward)
                if feedback.milestones:
                    milestones.extend(feedback.milestones)

        success = bool(feedback.success)
        invalid_episode = bool(feedback.invalid)

        if success:
            reward += self.cfg.success_reward
            milestones.append("success")

        if invalid_action:
            reward -= self.cfg.invalid_action_penalty

        if loop_penalty:
            reward -= self.cfg.loop_penalty
            milestones.append("loop_penalty")

        return RewardSignal(
            reward=reward,
            success=success,
            invalid_episode=invalid_episode,
            milestones=milestones,
            invalid_action=invalid_action,
        )


__all__ = ["RewardComputer", "RewardConfig"]
