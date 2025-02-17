from dependency_injector import containers, providers
from pymongo import MongoClient

from ..config.config import (
    ANALYSIS_COLLECTION,
    GENERATE_MILESTONES,
    LLM_ENPOINT,
    LLM_PROVIDER,
    LLM_THRESHOLD,
    MONGODB_NAME,
    MONGODB_URL,
    OPENAI_API_KEY,
    OPENAI_MAX_TOKENS,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    TASKS_COLLECTION,
)
from .llms.infrastructure.llm_service import LocalLLMService, OpenAIService
from .shared.infrastructure.databases.base_mongo_repository import BaseMongoRepository


class DIContainer(containers.DeclarativeContainer):
    """Dependency Injection Container."""

    # Configuration
    config = providers.Configuration()
    wiring_config = containers.WiringConfiguration(packages=["autoppia_iwa.src"])

    # Initialize MongoDB client as Singleton
    mongo_client = providers.Singleton(lambda: MongoClient(MONGODB_URL))

    # Repository of analysis results as Factory
    analysis_repository = providers.Factory(
        BaseMongoRepository,
        mongo_client=mongo_client,
        db_name=MONGODB_NAME,
        collection_name=ANALYSIS_COLLECTION,
    )

    # Synthetic Task Repository
    synthetic_task_repository = providers.Factory(
        BaseMongoRepository,
        mongo_client=mongo_client,
        db_name=MONGODB_NAME,
        collection_name=TASKS_COLLECTION,
    )

    # Task Generator (local or serverless)
    llm_service = providers.Singleton(lambda: DIContainer._get_llm_service())

    # Milestone Configuration
    generate_milestones = GENERATE_MILESTONES

    @classmethod
    def register_service(cls, service_name: str, service_instance):
        """
        Register a new service in the dependency container.
        """
        if hasattr(cls, service_name):
            raise AttributeError(f"Service {service_name} is already registered.")
        setattr(cls, service_name, providers.Singleton(service_instance))

    @staticmethod
    def _get_llm_service():
        if LLM_PROVIDER == "local":
            return LocalLLMService(
                endpoint_url=LLM_ENPOINT,
                threshold=LLM_THRESHOLD,
            )

        elif LLM_PROVIDER == "openai":
            return OpenAIService(
                api_key=OPENAI_API_KEY,
                model=OPENAI_MODEL,
                max_tokens=OPENAI_MAX_TOKENS,
                temperature=OPENAI_TEMPERATURE,
            )

        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")
