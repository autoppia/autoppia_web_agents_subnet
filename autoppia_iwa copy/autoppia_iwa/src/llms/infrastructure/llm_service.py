from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI

from ..domain.interfaces import ILLMService
from ..domain.openai.classes import BaseOpenAIResponseFormat, OpenAILLMModelMixin


class BaseLLMService(ILLMService):
    """
    Base class for LLM Task Generators, providing common HTTP request functionality.
    """

    def make_request(
        self,
        message_payload: List[Dict[str, str]],
        llm_kwargs: Optional[Dict[str, Any]] = None,
        chat_completion_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Any:
        raise NotImplementedError("Subclasses must implement this method.")

    @staticmethod
    def _make_http_request(url: str, payload: Dict, headers: Optional[Dict] = None, method: str = "post") -> Dict:
        """
        Makes an HTTP request.

        Args:
            url (str): The target URL.
            payload (Dict): The request payload.
            headers (Optional[Dict]): HTTP headers.
            method (str): HTTP method ('post' or 'get').

        Returns:
            Dict: JSON response from the server or error details.
        """
        try:
            if method.lower() == "post":
                response = requests.post(url, headers=headers, json=payload)
            elif method.lower() == "get":
                response = requests.get(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error in _make_request: {e}")
            return {"error": str(e)}


class LocalLLMService(BaseLLMService):
    """
    No waiting or canceling because tasks complete immediately.
    """

    def __init__(self, endpoint_url: str, threshold: int = 100):
        self.endpoint_url = endpoint_url

    def make_request(
        self,
        message_payload: List[Dict[str, str]],
        llm_kwargs: Optional[Dict[str, Any]] = None,
        chat_completion_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Any:
        payload = {"input": {"text": message_payload}}
        if llm_kwargs:
            payload["input"]["llm_kwargs"] = llm_kwargs
        if chat_completion_kwargs:
            payload["input"]["chat_completion_kwargs"] = chat_completion_kwargs

        response = self._make_http_request(self.endpoint_url, payload)
        # As local is synchronous, we can return the result directly.
        return response.get("output", {"error": "No output from local model"})


class OpenAIService(BaseLLMService, OpenAILLMModelMixin):
    """
    Service for interacting with OpenAI's GPT models.
    """

    def __init__(self, api_key: str, model: str, max_tokens: int = 2000, temperature: float = 0.7):
        """
        Initialize the OpenAI Service.

        Args:
            model (str): The GPT model to use, e.g., "gpt-4" or "gpt-3.5-turbo".
            max_tokens (int): Maximum number of tokens for the response.
            temperature (float): Sampling temperature for randomness.
        """
        self._model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._messages: List[dict] = []
        self.client = OpenAI(api_key=api_key)

    def make_request(
        self,
        message_payload: List[Dict[str, str]],
        llm_kwargs: Optional[Dict[str, Any]] = None,
        chat_completion_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Implementation of make_request from BaseLLMService.

        Args:
            message_payload (List[Dict[str, str]]): The input prompt.
            llm_kwargs (Optional[Dict[str, Any]]): Additional parameters for the LLM.
            chat_completion_kwargs (Optional[Dict[str, Any]]): Chat-specific parameters.

        Returns:
            Any: The response content from OpenAI.
        """
        # Configure the parameters for the call to OpenAI
        parameters = {
            "model": self._model,
            "messages": message_payload,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        if chat_completion_kwargs:
            parameters["temperature"] = chat_completion_kwargs.get("temperature", self.temperature)
            response_format = chat_completion_kwargs.get("response_format", {})
            if response_format:
                response_format_model = BaseOpenAIResponseFormat(**response_format)
                parameters["response_format"] = response_format_model.model_dump()

        try:
            # Make the call to OpenAI
            response = self.client.chat.completions.create(**parameters)

            # Extract the response from the assistant
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"Error with OpenAI API: {e}")
