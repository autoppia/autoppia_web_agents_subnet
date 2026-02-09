from typing import Dict, Optional
from pydantic import BaseModel


class TokenUsage(BaseModel):
    """Token usage tracking"""
    total_tokens: int = 0 
    total_cost: float = 0.0
    provider: Optional[str] = None  # LLM provider used (e.g., "openai", "chutes")


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
