import json
from dataclasses import dataclass, field, fields
from typing import Dict, List, Optional

from autoppia_iwa.src.llms.domain.openai.utils import OpenAIUtilsMixin


@dataclass
class EventTriggered:
    type: str

    def to_dict(self):
        field_names = [f.name for f in fields(self)]
        d = {k: getattr(self, k) for k in field_names}
        return d


@dataclass
class Element:
    tag: str
    attributes: Dict[str, str]
    textContent: str
    children: List["Element"] = field(default_factory=list)
    id: Optional[str] = None
    element_id: Optional[int] = None
    parent_element_id: Optional[int] = None
    path: Optional[str] = None
    events_triggered: List[EventTriggered] = field(default_factory=list)
    analysis: Optional[str] = None

    def to_dict(self):
        field_names = [f.name for f in fields(self)]
        d = {k: getattr(self, k) for k in field_names}
        if "children" in d:
            d["children"] = [child.to_dict() for child in self.children]
        if "events_triggered" in d:
            d["events_triggered"] = [event.to_dict() if isinstance(event, EventTriggered) else event for event in self.events_triggered]
            for event in d["events_triggered"]:
                if "target" in event:
                    del event["target"]
        return d

    def calculate_element_size(self) -> int:
        element_dict = self.to_dict()
        element_size = OpenAIUtilsMixin.num_tokens_from_string(json.dumps(element_dict))
        children_size = OpenAIUtilsMixin.num_tokens_from_string(json.dumps(element_dict.get("children", [])))
        return element_size + children_size

    def analyze(self, max_tokens, analyze_element_function, analyze_parent_function) -> Dict:
        tokens = self.calculate_element_size()
        result = {"tag": self.tag, "size": tokens, "analysis": None, "children": []}

        if tokens < max_tokens:
            print(f"Element {self.tag} with tokens {tokens} is smaller than max_tokens: {max_tokens}")
            result["analysis"] = analyze_element_function(self)
        else:
            print(f"Element {self.tag} with tokens {tokens} is bigger than max_tokens: {max_tokens}")
            for child in self.children:
                result["children"].append(child.analyze(max_tokens, analyze_element_function, analyze_parent_function))
            result["analysis"] = analyze_parent_function(self, result["children"])

        print(f"For element {self.tag} analysis result: {result}")
        return result


# ---------WEB CRAWL--------
@dataclass
class WebCrawlerConfig:
    start_url: str
    max_depth: int = 2
