from typing import Dict
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
    pricing: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    # Fallback prices in USD per 1M tokens when model-specific pricing is unknown.
    default_input_price: float = 0.0
    default_output_price: float = 0.0


DEFAULT_PROVIDER_CONFIGS = {
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com",
        pricing={
            # Prices are USD per 1M tokens (Standard tier), per OpenAI pricing docs.
            # Keys: input, output, input_cache_read (optional).
            "gpt-5.2": {"input": 1.75, "input_cache_read": 0.175, "output": 14.0},
            "gpt-5.1": {"input": 1.25, "input_cache_read": 0.125, "output": 10.0},
            "gpt-5": {"input": 1.25, "input_cache_read": 0.125, "output": 10.0},
            "gpt-5-mini": {"input": 0.25, "input_cache_read": 0.025, "output": 2.0},
            "gpt-5-nano": {"input": 0.05, "input_cache_read": 0.005, "output": 0.40},
            "gpt-5.2-chat-latest": {"input": 1.75, "input_cache_read": 0.175, "output": 14.0},
            "gpt-5.1-chat-latest": {"input": 1.25, "input_cache_read": 0.125, "output": 10.0},
            "gpt-5-chat-latest": {"input": 1.25, "input_cache_read": 0.125, "output": 10.0},
            "gpt-5.2-codex": {"input": 1.75, "input_cache_read": 0.175, "output": 14.0},
            "gpt-5.1-codex-max": {"input": 1.25, "input_cache_read": 0.125, "output": 10.0},
            "gpt-5.1-codex": {"input": 1.25, "input_cache_read": 0.125, "output": 10.0},
            "gpt-5-codex": {"input": 1.25, "input_cache_read": 0.125, "output": 10.0},
            "gpt-5.2-pro": {"input": 21.0, "output": 168.0},
            "gpt-5-pro": {"input": 15.0, "output": 120.0},
            "gpt-4.1": {"input": 3.5, "input_cache_read": 0.875, "output": 14.0},
            "gpt-4.1-mini": {"input": 0.80, "input_cache_read": 0.20, "output": 3.20},
            "gpt-4.1-nano": {"input": 0.20, "input_cache_read": 0.05, "output": 0.80},
            "gpt-4.5": {"input": 75.0, "input_cache_read": 37.5, "output": 150.0},
            "gpt-4o": {"input": 2.5, "input_cache_read": 1.25, "output": 10.0},
            "gpt-4o-mini": {"input": 0.15, "input_cache_read": 0.075, "output": 0.60},
            "o1": {"input": 15.0, "input_cache_read": 7.5, "output": 60.0},
            "o1-pro": {"input": 150.0, "output": 600.0},
            "o3": {"input": 2.0, "input_cache_read": 0.50, "output": 8.0},
            "o3-pro": {"input": 20.0, "output": 80.0},
            "o3-mini": {"input": 1.10, "input_cache_read": 0.55, "output": 4.40},
            "o4-mini": {"input": 1.10, "input_cache_read": 0.275, "output": 4.40},
            "codex-mini-latest": {"input": 1.50, "input_cache_read": 0.375, "output": 6.00},
            "gpt-realtime": {"input": 4.0, "input_cache_read": 0.40, "output": 16.0},
            "gpt-realtime-mini": {"input": 0.80, "input_cache_read": 0.08, "output": 3.20},
            "gpt-realtime-nano": {"input": 0.40, "input_cache_read": 0.04, "output": 1.60},
            "gpt-audio": {"input": 2.5, "output": 10.0},
            "gpt-audio-mini": {"input": 0.15, "output": 0.60},
            "gpt-audio-nano": {"input": 0.05, "output": 0.20},
        },
        # Conservative fallback (operator can override pricing map as needed).
        default_input_price=1.75,
        default_output_price=14.0,
    ),
    # Chutes provides an OpenAI-compatible LLM endpoint at https://llm.chutes.ai/v1
    # We set base_url to the host and expect incoming gateway paths to include /v1/...
    "chutes": ProviderConfig(
        name="chutes",
        base_url="https://llm.chutes.ai",
        pricing={},
        # Conservative fallback; override by populating pricing as needed.
        default_input_price=1.0,
        default_output_price=4.0,
    ),
}
