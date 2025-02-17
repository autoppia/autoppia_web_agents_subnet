# base.py
import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ------------------------------------------------------
# SELECTOR LOGIC
# ------------------------------------------------------

class SelectorType(str, Enum):
    ATTRIBUTE_VALUE_SELECTOR = "attributeValueSelector"
    TAG_CONTAINS_SELECTOR = "tagContainsSelector"
    XPATH_SELECTOR = "xpathSelector"


class Selector(BaseModel):
    type: SelectorType
    attribute: Optional[str] = None
    value: str
    case_sensitive: bool = False

    def to_playwright_selector(self) -> str:
        """
        Returns the final selector string for use with Playwright.
        """
        ATTRIBUTE_FORMATS = {
            "id": "#",
            "class": ".",
            "placeholder": "[placeholder='{value}']",
            "name": "[name='{value}']",
            "role": "[role='{value}']",
            "value": "[value='{value}']",
            "type": "[type='{value}']",
            "aria-label": "[aria-label='{value}']",
            "aria-labelledby": "[aria-labelledby='{value}']",
            "data-testid": "[data-testid='{value}']",
            "data-custom": "[data-custom='{value}']",
            "href": "a[href='{value}']",
        }

        if self.type == SelectorType.ATTRIBUTE_VALUE_SELECTOR:
            if self.attribute in ATTRIBUTE_FORMATS:
                fmt = ATTRIBUTE_FORMATS[self.attribute]
                if self.attribute in ["id", "class"]:
                    # #id or .class
                    return f"{fmt}{self.value}"
                return fmt.format(value=self.value)
            return f"[{self.attribute}='{self.value}']"

        elif self.type == SelectorType.TAG_CONTAINS_SELECTOR:
            if self.case_sensitive:
                return f'text="{self.value}"'
            return f"text={self.value}"

        elif self.type == SelectorType.XPATH_SELECTOR:
            if not self.value.startswith("//"):
                return f"xpath=//{self.value}"
            return f"xpath={self.value}"

        else:
            raise ValueError(f"Unsupported selector type: {self.type}")


# ------------------------------------------------------
# BASE ACTION CLASSES
# ------------------------------------------------------

class BaseAction(BaseModel):
    """
    Base for all actions with a discriminating 'type' field.
    """
    type: str = Field(..., description="Discriminated action type")

    class Config:
        extra = "allow"

    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        """
        Each subclass must implement its own `execute` logic.
        """
        raise NotImplementedError("Execute method must be implemented by subclasses.")


class BaseActionWithSelector(BaseAction):
    selector: Optional[Selector] = None

    def validate_selector(self) -> str:
        if not self.selector:
            raise ValueError("Selector is required for this action.")
        return self.selector.to_playwright_selector()
