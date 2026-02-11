from typing import Dict, Optional
from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    """Token usage tracking"""
    tokens: dict[str, dict[str, int]] = Field(default_factory=dict)  # provider -> model -> tokens
    cost: dict[str, dict[str, float]] = Field(default_factory=dict)   # provider -> model -> cost

    def add_usage(self, provider: str, model: str, tokens: int, cost: float):
        if provider not in self.tokens:
            self.tokens[provider] = {}
        if provider not in self.cost:
            self.cost[provider] = {}

        self.tokens[provider][model] = self.tokens[provider].get(model, 0) + tokens
        self.cost[provider][model] = self.cost[provider].get(model, 0.0) + cost

    @property
    def total_tokens(self) -> int:
        return sum(tokens for provider in self.tokens.values() for tokens in provider.values())

    @property
    def total_cost(self) -> float:
        return sum(cost for provider in self.cost.values() for cost in provider.values())


class ProviderConfig(BaseModel):
    """Configuration for LLM providers"""
    name: str
    base_url: str
    pricing: Dict[str, Dict[str, float]]


DEFAULT_PROVIDER_CONFIGS = {
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com",
        pricing={
            "gpt-5.2": {"input": 1.75, "output": 14.0},
            "gpt-5.1": {"input": 1.25, "output": 10.0},
            "gpt-5": {"input": 1.25, "output": 10.0},
            "gpt-5-mini": {"input": 0.25, "output": 2.0},
        }
    )
}
