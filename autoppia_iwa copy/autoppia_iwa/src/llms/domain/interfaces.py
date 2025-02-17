from abc import ABC, abstractmethod
from typing import Dict, List


class ILLMModel(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        pass

    @property
    @abstractmethod
    def temperature(self) -> float:
        pass

    @property
    @abstractmethod
    def max_tokens(self) -> int:
        pass

    @abstractmethod
    def get_model(self) -> str:
        pass

    @abstractmethod
    def predict(self, messages: str) -> str:
        pass

    @abstractmethod
    def get_response(self, request) -> str:
        pass

    @abstractmethod
    def get_response_with_json_format(self, request) -> str:
        pass


# ------------------ESTO ESTA RELACIONADO CON LA GENERACION DE TASK----------------
# TODO: Quizas en un futuro hay que unificar este llmTaskGenerator con el LLM de arriba
class ILLMService(ABC):
    @abstractmethod
    def make_request(
        self,
        message_payload: List[Dict[str, str]],
        llm_kwargs=None,
        chat_completion_kwargs=None,
    ) -> str:
        """
        Make a request using LLM Local or serverless.

        Args:
            message_payload (List[Dict[str, str]]): Input message for the model.
            llm_kwargs (dict): Additional model parameters.
            chat_completion_kwargs (dict): Additional chat-specific parameters.

        Returns:
            str: The response from the serverless model, or an error message if the request fails.
        """
