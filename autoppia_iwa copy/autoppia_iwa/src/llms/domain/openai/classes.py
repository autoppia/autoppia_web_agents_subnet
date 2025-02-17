from typing import Any, Dict

from pydantic import BaseModel, Field, field_validator


class OpenAILLMModelMixin:
    @property
    def temperature(self) -> float:
        return self._temperature

    @temperature.setter
    def temperature(self, value):
        if not isinstance(value, float):
            raise TypeError("Temperature must be a float")
        if value < 0 or value > 1:
            raise ValueError("Value cannot be negative nor bigger than 1")
        self._temperature = value

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value):
        if not isinstance(value, int):
            raise TypeError("Max tokens must be an integer")
        if value < 0:
            raise ValueError("Value cannot be negative")
        self._max_tokens = value


class BaseOpenAIResponseFormat(BaseModel):
    """
    Pydantic model for validating OpenAI response format.
    Ensures that the schema has necessary fields.
    """

    schema_data: Dict[str, Any] = Field(..., alias="schema")
    type: str

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value):
        if not value:
            raise ValueError("Type must be provided")
        if "json_schema" not in value:
            return "json_schema"
        return value

    @field_validator("schema_data", mode="before")  # Update validator name
    @classmethod
    def json_schema_validator(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Validates and ensures required fields exist in the JSON schema."""
        if not value:
            raise ValueError("JSON schema cannot be empty.")

        updated_value = {}
        if "name" not in updated_value:
            updated_value["name"] = "sample_actions"
        if "schema" not in updated_value:
            updated_value["schema"] = value  # Preserve schema structure

        return updated_value

    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:
        return {"json_schema": self.schema_data, "type": self.type}
