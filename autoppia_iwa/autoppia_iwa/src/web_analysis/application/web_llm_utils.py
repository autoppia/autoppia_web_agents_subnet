import copy
import json
from typing import Any, Dict, List

from dependency_injector.wiring import Provide

from autoppia_iwa.src.di_container import DIContainer
from autoppia_iwa.src.llms.domain.interfaces import ILLMService
from autoppia_iwa.src.web_analysis.domain.analysis_classes import LLMWebAnalysis
from autoppia_iwa.src.web_analysis.domain.classes import Element
from autoppia_iwa.src.web_analysis.domain.prompt_llm_template import PromptLLMTemplate

CONVERT_RESPONSE_TO_JSON_PROMPT = """
You are an expert JSON content reviewer tasked with analyzing the given RAW JSON/Unstructured
 segment of a webpage and providing a strictly valid JSON-formatted analysis.

Important Requirements:
- Return only one JSON object (no arrays, no multiple objects).
- The output must be valid JSON that can be directly parsed by `json.loads` without modification.
- Use double quotes for all keys and string values.
- Do not include trailing commas.
- Do not include any text or explanation outside of the JSON object.
- If something is not relevant, omit it entirely rather than returning empty lists or objects.
- Do not include comments or additional text outside the JSON.
- Do not include code fences (```).

If the input cannot be summarized into a valid JSON object, return an empty JSON object: {}.
"""


class WebLLMAnalyzer:
    def __init__(self, llm_service: ILLMService = Provide[DIContainer.llm_service]):
        """
        Initialize the web page structure extractor with a start URL.

        Args:
            llm_service (ILLMService): the model to extract data from.
        """
        self.llm_service: ILLMService = llm_service

    def analyze_element(self, element: Element) -> LLMWebAnalysis:
        template = PromptLLMTemplate.get_instance_from_file(
            "config/prompts/web_analysis/analyze_element.txt",
            "config/schemas/web_analysis/analyze_element_schema.json",
            {
                "element": element.to_dict(),
            },
        )
        return self._analyze_prompt_template(template=template)

    def analyze_element_parent(self, element: Element, children_analysis: List) -> LLMWebAnalysis:
        element_without_children = copy.deepcopy(element)
        del element_without_children.children

        # Text analysis about the sub segment
        template = PromptLLMTemplate.get_instance_from_file(
            "config/prompts/web_analysis/analyze_element_parent.txt",
            "config/schemas/web_analysis/analyze_element_parent_schema.json",
            {
                "element_without_children": element.to_dict(),
                "children_analysis": children_analysis,
            },
        )
        return self._analyze_prompt_template(template=template)

    def summarize_web_page(self, domain: str, page_url: str, elements_analysis_result) -> LLMWebAnalysis:
        for element in elements_analysis_result:
            if isinstance(element.get("analysis"), LLMWebAnalysis):
                element["analysis"] = element["analysis"].model_dump()
        template = PromptLLMTemplate.get_instance_from_file(
            "config/prompts/web_analysis/analyze_page_url.txt",
            "config/schemas/web_analysis/analyze_page_url_schema.json",
            {
                "domain": domain,
                "page_url": page_url,
                "html_page_analysis": elements_analysis_result,
            },
        )
        return self._analyze_prompt_template(template=template)

    def _analyze_prompt_template(self, template: PromptLLMTemplate) -> LLMWebAnalysis:
        prompt = PromptLLMTemplate.clean_prompt(template.current_prompt)
        json_schema = template.get_schema()
        llm_message = self._create_llm_message(prompt)
        response: str = self.llm_service.make_request(llm_message, {"chat_format": "chatml"}, json_schema)
        json_result = self._parse_json_response(response)
        analysis = LLMWebAnalysis(**json_result)
        return analysis

    @staticmethod
    def _create_llm_message(prompt: str, system_instructions: str = CONVERT_RESPONSE_TO_JSON_PROMPT) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": system_instructions.strip()},
            {"role": "user", "content": prompt.strip()},
        ]

    @staticmethod
    def _parse_json_response(response: str) -> Dict[Any, Any]:
        """Parses a JSON response from the LLM."""
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}")
