import traceback
from datetime import datetime
from typing import Optional, Tuple

from dependency_injector.wiring import Provide

from autoppia_iwa.src.data_generation.domain.classes import Task, TaskDifficultyLevel, TaskGenerationConfig, TasksGenerationOutput
from autoppia_iwa.src.di_container import DIContainer
from autoppia_iwa.src.llms.infrastructure.llm_service import ILLMService
from autoppia_iwa.src.shared.infrastructure.databases.base_mongo_repository import BaseMongoRepository
from autoppia_iwa.src.shared.utils import extract_html
from autoppia_iwa.src.web_analysis.application.web_analysis_pipeline import WebAnalysisPipeline
from autoppia_iwa.src.web_analysis.domain.analysis_classes import DomainAnalysis, SinglePageAnalysis

from .task_prompt_generator import TaskPromptGenerator
from .task_tests_generator import TaskTestGenerator


class TaskGenerationPipeline:
    def __init__(
        self,
        config: TaskGenerationConfig,
        synthetic_task_repository: BaseMongoRepository = Provide[DIContainer.synthetic_task_repository],
        llm_service: ILLMService = Provide[DIContainer.llm_service],
        web_analysis_repository: BaseMongoRepository = Provide[DIContainer.analysis_repository],
    ):
        """
        Initializes the task generation pipeline.

        :param config: Task generation input configuration.
        :param synthetic_task_repository: Repository to store generated tasks.
        :param llm_service: Language model service for generating prompts or tests.
        """
        self.task_config = config
        self.synthetic_task_repository = synthetic_task_repository
        self.llm_service = llm_service
        self.web_analysis_repository = web_analysis_repository

    async def generate(self, task_difficulty_level: TaskDifficultyLevel = TaskDifficultyLevel.EASY) -> TasksGenerationOutput:
        """
        Main method for task generation for a whole web project. Runs web analysis, generates prompts, and processes tasks.
        """
        start_time = datetime.now()
        global_tasks_output = TasksGenerationOutput(tasks=[], total_phase_time=0.0)

        try:
            # WEB ANALYSIS
            web_analysis = await self._run_web_analysis()
            if not web_analysis:
                raise ValueError("Failed to run web analysis!")

            # Initialize generators only once
            task_prompt_generator, task_test_generator = self._initialize_generators(web_analysis)

            # TASK PROMPT
            for page_analysis in web_analysis.analyzed_urls:
                current_html = await self._get_page_html(page_analysis)

                prompts_for_url = await task_prompt_generator.generate_task_prompts_for_url(
                    task_difficulty_level=task_difficulty_level,
                    specific_url=page_analysis.page_url,
                    current_html=current_html,
                )

                for task_prompts in prompts_for_url.task_prompts:
                    # TASK TEST
                    task_tests = await task_test_generator.generate_task_tests(
                        task_description=task_prompts,
                        page_url=prompts_for_url.page_url,
                        page_html=current_html,
                    )

                    global_task = Task(
                        prompt=task_prompts,
                        url=self.task_config.web_project.frontend_url,
                        tests=task_tests,
                    )

                    # Save task to database or append to output.
                    if self.task_config.save_task_in_db:
                        self.synthetic_task_repository.save(global_task.model_dump())

                    global_tasks_output.tasks.append(global_task)

            global_tasks_output.total_phase_time = (datetime.now() - start_time).total_seconds()
        except Exception as e:
            print(f"Tasks generation failed: {e}\n{traceback.format_exc()}")

        return global_tasks_output

    async def _run_web_analysis(self) -> Optional[DomainAnalysis]:
        """
        Executes the web analysis pipeline to gather information from the target page.
        """
        analyzer = WebAnalysisPipeline(start_url=self.task_config.web_project.frontend_url, llm_service=self.llm_service, analysis_repository=self.web_analysis_repository)
        return await analyzer.analyze(
            save_results_in_db=self.task_config.save_web_analysis_in_db,
            enable_crawl=self.task_config.enable_crawl,
        )

    def _initialize_generators(self, web_analysis: DomainAnalysis) -> Tuple[TaskPromptGenerator, TaskTestGenerator]:
        """
        Initializes and returns task prompt and test generators.
        """
        task_prompt_generator = TaskPromptGenerator(num_prompts_per_url=self.task_config.number_of_prompts_per_task, web_analysis=web_analysis, llm_service=self.llm_service)
        task_test_generator = TaskTestGenerator(self.task_config.web_project, web_analysis, llm_service=self.llm_service)
        return task_prompt_generator, task_test_generator

    @staticmethod
    async def _get_page_html(page_analysis: SinglePageAnalysis) -> str:
        """
        Retrieves the HTML for the current page from analysis or HTML source.
        """
        return await extract_html(page_analysis.page_url) or page_analysis.html_source
