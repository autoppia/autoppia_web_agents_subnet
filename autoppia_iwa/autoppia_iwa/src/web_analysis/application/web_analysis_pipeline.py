import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from dependency_injector.wiring import Provide

from ...di_container import DIContainer
from ...llms.domain.interfaces import ILLMService
from ...shared.infrastructure.databases.base_mongo_repository import BaseMongoRepository
from ..domain.analysis_classes import DomainAnalysis, SinglePageAnalysis
from .web_crawler import WebCrawler
from .web_llm_utils import WebLLMAnalyzer
from .web_page_structure_extractor import WebPageStructureExtractor

MAX_TOKENS_ELEMENT_ANALYZER = 10000


class WebAnalysisPipeline:
    def __init__(
        self,
        start_url: str,
        analysis_repository: BaseMongoRepository = Provide[DIContainer.analysis_repository],
        llm_service: ILLMService = Provide[DIContainer.llm_service],
    ):
        self.start_url = start_url
        self.domain = urlparse(start_url).netloc
        self.llm_service = llm_service
        self.analysis_repository = analysis_repository

        self.web_crawler = WebCrawler(start_url=start_url)
        self.page_structure_extractor = WebPageStructureExtractor()
        self.llm_analyzer = WebLLMAnalyzer(llm_service=self.llm_service)

        self.analyzed_urls: List[SinglePageAnalysis] = []

    async def analyze(
        self,
        save_results_in_db: bool = True,
        get_analysis_from_cache: bool = True,
        enable_crawl: bool = True,
    ) -> DomainAnalysis:
        """
        Executes a full analysis for a domain, processing all URLs.

        Args:
        save_results_in_db (bool): Whether to save the results in the database. Default is False.
        get_analysis_from_cache (bool): Whether to check for cached results before analyzing. Default is True.
        enable_crawl (bool): Whether to crawl the domain for URLs. Default is True.

        Returns:
            Optional[Dict]: The analysis result, or None if unsuccessful.
        """
        cached_result = self._get_analysis_from_cache() if get_analysis_from_cache else None
        if cached_result:
            return cached_result

        self._initialize_analysis()
        urls_to_analyze = self._get_urls_to_analyze(enable_crawl)
        for url in urls_to_analyze:
            try:
                print(url)
                await self._analyze_url(url)
            except Exception as e:
                print(f"Error analyzing {url}: {e}")
        self._finalize_analysis()

        if save_results_in_db:
            self._save_results_in_db()
        if not isinstance(self.analysis_result, DomainAnalysis):
            self.analysis_result = DomainAnalysis(**self.analysis_result)
        return self.analysis_result

    def _get_analysis_from_cache(self) -> Optional[DomainAnalysis]:
        """
        Check if analysis results already exist in the database.

        Returns:
            Optional[DomainAnalysis]: Cached analysis result, or None if not found.
        """
        try:
            cached_result = self.analysis_repository.find_one({"start_url": self.start_url})
            if cached_result:
                print(f"Analysis for '{self.start_url}' already exists in Cache")
                return DomainAnalysis(**cached_result)
            print(f"No cached data found for url {self.start_url}")
            return None
        except Exception as e:
            print(f"Error checking cache for {self.start_url}: {e}")
            return None

    def _initialize_analysis(self):
        """
        Initialize metadata for the analysis process.
        """
        self.start_time = time.time()
        self.analysis_result = DomainAnalysis(
            domain=self.domain,
            status="processing",
            analyzed_urls=[],
            started_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ended_time="",
            total_time=0,
            start_url=self.start_url,
        )

    def _get_urls_to_analyze(self, enable_crawl) -> List[str]:
        """
        Crawl and retrieve URLs to analyze from the starting domain.

        Returns:
            List[str]: A list of URLs to analyze.
        """
        try:
            if not enable_crawl:
                return [self.start_url]
            all_urls = self.web_crawler.crawl_urls(start_url=self.start_url, max_depth=1)
            return list(set(all_urls))
        except Exception as e:
            print(f"Error crawling URLs for {self.start_url}: {e}")
            return []

    async def _analyze_url(self, url: str):
        """
        Analyze a URL with error handling to ensure the pipeline continues.

        Args:
            url (str): The URL to analyze.
        """
        try:
            # Extract HTML structure
            elements, html_source = await self.page_structure_extractor.get_elements(url)

            # Analyze each element using the LLM
            elements_analysis_result = []
            for element in elements:
                print(f"Analysing element: {element.tag} from url {url}")
                try:
                    elements_analysis_result.append(
                        element.analyze(
                            max_tokens=MAX_TOKENS_ELEMENT_ANALYZER, analyze_element_function=self.llm_analyzer.analyze_element, analyze_parent_function=self.llm_analyzer.analyze_element_parent
                        )
                    )
                except Exception as e:
                    print(f"Error analyzing element {element.element_id}: {e}")

            # Summarize the page
            page_summary_analysis = self.llm_analyzer.summarize_web_page(
                domain=self.domain,
                page_url=url,
                elements_analysis_result=elements_analysis_result,
            )
            if page_summary_analysis:
                single_page_analysis = SinglePageAnalysis(
                    page_url=url,
                    elements_analysis_result=elements_analysis_result,
                    web_summary=page_summary_analysis,
                    html_source=html_source,
                )
                self.analyzed_urls.append(single_page_analysis)

        except Exception as e:
            print(f"Failed to analyze URL {url}. Reason: {e}")

    def _finalize_analysis(self):
        """
        Finalize the analysis by updating metadata and storing results.
        """
        self.analysis_result.status = "done"
        self.analysis_result.analyzed_urls = self.analyzed_urls
        self.analysis_result.ended_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.analysis_result.total_time = time.time() - self.start_time

    def _save_results_in_db(self):
        """
        Save the analysis result in the database.
        """
        try:
            self.analysis_repository.save(self.analysis_result.model_dump())
            print("Analysis results saved successfully.")
        except Exception as e:
            print(f"Failed to save analysis results. Reason: {e}")
