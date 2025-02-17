# actions.py
import asyncio
import json
import logging
from typing import Union, Optional
from typing_extensions import Annotated, Literal

from pydantic import Field
from playwright.async_api import Page

# Use your new combined base classes
from .base import BaseAction, BaseActionWithSelector

action_logger = logging.getLogger(__name__)


def log_action(action_name: str):
    """Decorator to log action execution around the `execute` call."""
    def decorator(func):
        async def wrapper(self, page: Optional[Page], backend_service, web_agent_id: str):
            action_logger.debug(f"Executing {action_name} with data: {self.model_dump()}")
            try:
                return await func(self, page, backend_service, web_agent_id)
            except Exception as e:
                action_logger.error(f"{action_name} failed: {e}")
                raise
        return wrapper
    return decorator


# -------------------------------------------------------------------
# Concrete Actions
# -------------------------------------------------------------------

class ClickAction(BaseActionWithSelector):
    type: Literal["ClickAction"] = "ClickAction"
    x: Optional[int] = None
    y: Optional[int] = None

    @log_action("ClickAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        if self.selector:
            selector_str = self.validate_selector()
            await page.click(selector_str)
        elif self.x is not None and self.y is not None:
            await page.mouse.click(self.x, self.y)
        else:
            raise ValueError("Either a selector or (x, y) must be provided.")


class DoubleClickAction(BaseActionWithSelector):
    type: Literal["DoubleClickAction"] = "DoubleClickAction"

    @log_action("DoubleClickAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        selector_str = self.validate_selector()
        await page.dblclick(selector_str)


class NavigateAction(BaseAction):
    type: Literal["NavigateAction"] = "NavigateAction"
    url: Optional[str] = ""
    go_back: bool = False
    go_forward: bool = False

    @log_action("NavigateAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        if self.go_back:
            await page.go_back()
        elif self.go_forward:
            await page.go_forward()
        elif not self.url:
            raise ValueError("URL must be provided for navigation.")
        else:
            await page.goto(self.url)


class TypeAction(BaseActionWithSelector):
    type: Literal["TypeAction"] = "TypeAction"
    text: str

    @log_action("TypeAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        sel_str = self.validate_selector()
        await page.fill(sel_str, self.text)


class SelectAction(BaseActionWithSelector):
    type: Literal["SelectAction"] = "SelectAction"
    value: str

    @log_action("SelectAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        sel_str = self.validate_selector()
        await page.select_option(sel_str, self.value)


class HoverAction(BaseActionWithSelector):
    type: Literal["HoverAction"] = "HoverAction"

    @log_action("HoverAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        sel_str = self.validate_selector()
        await page.hover(sel_str)


class WaitAction(BaseActionWithSelector):
    type: Literal["WaitAction"] = "WaitAction"
    time_seconds: Optional[float] = None

    @log_action("WaitAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        if self.selector:
            sel_str = self.validate_selector()
            await page.wait_for_selector(sel_str, timeout=self.time_seconds * 1000 if self.time_seconds else None)
        elif self.time_seconds:
            await page.wait_for_timeout(self.time_seconds * 1000)
        else:
            raise ValueError("Either selector or time_seconds must be provided.")


class ScrollAction(BaseAction):
    type: Literal["ScrollAction"] = "ScrollAction"
    value: Optional[Union[str, int]] = None
    up: bool = False
    down: bool = False

    @log_action("ScrollAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        if self.up:
            try:
                await page.evaluate(f"window.scrollBy(0, -{self.value});")
            except:
                await page.keyboard.press("PageUp")
        elif self.down:
            try:
                await page.evaluate(f"window.scrollBy(0, {self.value});")
            except:
                await page.keyboard.press("PageDown")
        else:
            # Attempt text-based scroll
            locators = [
                page.get_by_text(str(self.value), exact=False),
                page.locator(f"text={self.value}"),
                page.locator(f"//*[contains(text(), '{self.value}')]"),
            ]
            for locator in locators:
                try:
                    if await locator.count() > 0 and await locator.first.is_visible():
                        await locator.first.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        return
                except:
                    continue
            raise ValueError(f"Could not scroll to: {self.value}")


class SubmitAction(BaseActionWithSelector):
    type: Literal["SubmitAction"] = "SubmitAction"

    @log_action("SubmitAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        sel_str = self.validate_selector()
        await page.locator(sel_str).press("Enter")


class AssertAction(BaseAction):
    type: Literal["AssertAction"] = "AssertAction"
    text_to_assert: str

    @log_action("AssertAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        content = await page.content()
        if self.text_to_assert not in content:
            raise AssertionError(f"'{self.text_to_assert}' not found in page source.")


class DragAndDropAction(BaseAction):
    type: Literal["DragAndDropAction"] = "DragAndDropAction"
    source_selector: str = Field(..., alias="sourceSelector")
    target_selector: str = Field(..., alias="targetSelector")

    @log_action("DragAndDropAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        await page.drag_and_drop(self.source_selector, self.target_selector)


class ScreenshotAction(BaseAction):
    type: Literal["ScreenshotAction"] = "ScreenshotAction"
    file_path: str

    @log_action("ScreenshotAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        await page.screenshot(path=self.file_path)


class SendKeysIWAAction(BaseAction):
    type: Literal["SendKeysIWAAction"] = "SendKeysIWAAction"
    keys: str

    @log_action("SendKeysIWAAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        await page.keyboard.press(self.keys)


class GetDropDownOptions(BaseActionWithSelector):
    type: Literal["GetDropDownOptions"] = "GetDropDownOptions"

    @log_action("GetDropDownOptions")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        xpath = self.validate_selector()
        all_options = []
        frame_index = 0

        for frame in page.frames:
            try:
                options = await frame.evaluate(
                    """
                    (xp) => {
                        const select = document.evaluate(xp, document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        if (!select) return null;
                        return {
                            options: Array.from(select.options).map(opt => ({
                                text: opt.text,
                                value: opt.value,
                                index: opt.index
                            })),
                            id: select.id,
                            name: select.name
                        };
                    }
                    """,
                    xpath
                )
                if options:
                    action_logger.debug(f"Found dropdown in frame {frame_index}")
                    formatted = []
                    for opt in options["options"]:
                        encoded_text = json.dumps(opt["text"])
                        formatted.append(f'{opt["index"]}: text={encoded_text}')
                    all_options.extend(formatted)
            except Exception as e:
                action_logger.debug(f"Frame {frame_index} evaluate error: {str(e)}")
            frame_index += 1

        if all_options:
            msg = "\n".join(all_options) + "\nUse the exact string in SelectDropDownOption"
            action_logger.info(msg)
        else:
            action_logger.info("No options found in any frame for dropdown")


class SelectDropDownOption(BaseActionWithSelector):
    type: Literal["SelectDropDownOption"] = "SelectDropDownOption"
    text: str

    @log_action("SelectDropDownOption")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        xpath = self.validate_selector()
        frame_index = 0
        found = False

        for frame in page.frames:
            try:
                dropdown_info = await frame.evaluate(
                    """
                    (xp) => {
                        const select = document.evaluate(xp, document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        if (!select) return { found: false, error: 'No select found' };
                        if (select.tagName.toLowerCase() !== 'select') {
                            return {
                                found: false,
                                error: `Element is ${select.tagName}, not SELECT`
                            };
                        }
                        return {
                            found: true,
                            id: select.id,
                            name: select.name,
                            optionCount: select.options.length,
                            currentValue: select.value,
                            availableOptions: Array.from(select.options).map(o => o.text.trim())
                        };
                    }
                    """,
                    xpath
                )
                if dropdown_info.get("found"):
                    selected = await frame.locator(xpath).nth(0).select_option(label=self.text, timeout=1000)
                    action_logger.info(f"Selected '{self.text}' => {selected} in frame {frame_index}")
                    found = True
                    break
            except Exception as e:
                action_logger.debug(f"Frame {frame_index} attempt failed: {e}")
            frame_index += 1

        if not found:
            action_logger.info(f"Could not select option '{self.text}' in any frame")


class UndefinedAction(BaseAction):
    type: Literal["UndefinedAction"] = "UndefinedAction"

    @log_action("UndefinedAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        pass


class IdleAction(BaseAction):
    type: Literal["IdleAction"] = "IdleAction"

    @log_action("IdleAction")
    async def execute(self, page: Optional[Page], backend_service, web_agent_id: str):
        pass


# -------------------------------------------------------------------
# Union Type to Handle All Actions by Discriminator
# -------------------------------------------------------------------

AllActionsUnion = Annotated[
    Union[
        ClickAction,
        DoubleClickAction,
        NavigateAction,
        TypeAction,
        SelectAction,
        HoverAction,
        WaitAction,
        ScrollAction,
        SubmitAction,
        AssertAction,
        DragAndDropAction,
        ScreenshotAction,
        SendKeysIWAAction,
        GetDropDownOptions,
        SelectDropDownOption,
        UndefinedAction,
        IdleAction,
    ],
    Field(discriminator="type")
]


# -------------------------------------------------------------------
# MAPS (as requested, appended at the end)
# -------------------------------------------------------------------

ACTION_CLASS_MAP_LOWER = {
    "click": ClickAction,
    "type": TypeAction,
    "hover": HoverAction,
    "navigate": NavigateAction,
    "dragAndDrop": DragAndDropAction,
    "submit": SubmitAction,
    "doubleClick": DoubleClickAction,
    "scroll": ScrollAction,
    "screenshot": ScreenshotAction,
    "wait": WaitAction,
    "assert": AssertAction,
    "select": SelectAction,
    "idle": IdleAction,
    "undefined": UndefinedAction,
    "sendkeysiwa": SendKeysIWAAction,
    "getdropdownoptions": GetDropDownOptions,
    "selectdropdownoption": SelectDropDownOption,
}

ACTION_CLASS_MAP_CAPS = {
    "ClickAction": ClickAction,
    "TypeAction": TypeAction,
    "HoverAction": HoverAction,
    "NavigateAction": NavigateAction,
    "DragAndDropAction": DragAndDropAction,
    "SubmitAction": SubmitAction,
    "DoubleClickAction": DoubleClickAction,
    "ScrollAction": ScrollAction,
    "ScreenshotAction": ScreenshotAction,
    "WaitAction": WaitAction,
    "AssertAction": AssertAction,
    "SelectAction": SelectAction,
    "IdleAction": IdleAction,
    "UndefinedAction": UndefinedAction,
    "SendKeysIWAAction": SendKeysIWAAction,
    "GetDropDownOptions": GetDropDownOptions,
    "SelectDropDownOption": SelectDropDownOption,
}

ACTION_CLASS_MAP = {**ACTION_CLASS_MAP_CAPS, **ACTION_CLASS_MAP_LOWER}
