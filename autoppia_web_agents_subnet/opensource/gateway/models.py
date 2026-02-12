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
            "gpt-5.2": {"input": 1.75, "output": 14.0},
            "gpt-5.1": {"input": 1.25, "output": 10.0},
            "gpt-5": {"input": 1.25, "output": 10.0},
            "gpt-5-mini": {"input": 0.25, "output": 2.0},
        },
        # Conservative fallback (operator can override pricing map as needed).
        default_input_price=1.25,
        default_output_price=10.0,
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
