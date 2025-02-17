from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class LLMWebAnalysis(BaseModel):
    one_phrase_summary: str
    summary: str
    categories: List[str]
    functionality: List[str]
    media_files_description: Optional[Union[str, List[Dict[str, Any]], List[str]]] = None
    key_words: List[str]
    relevant_fields: Optional[List[Union[str, Dict[str, Union[str, Any]]]]] = None
    curiosities: Optional[str] = None
    accessibility: Optional[Union[str, List[str]]] = None
    user_experience: Optional[str] = None
    advertisements: Optional[str] = None
    seo_considerations: Optional[str] = None
    additional_notes: Optional[str] = None


class SinglePageAnalysis(BaseModel):
    page_url: str
    elements_analysis_result: List[Dict]
    web_summary: LLMWebAnalysis
    html_source: str


class DomainAnalysis(BaseModel):
    domain: str
    status: str
    analyzed_urls: List[SinglePageAnalysis]
    started_time: str
    ended_time: str
    total_time: float
    start_url: str
