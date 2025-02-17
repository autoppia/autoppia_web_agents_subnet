import asyncio
from dataclasses import fields
from typing import List, Optional, Union
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from autoppia_iwa.config.config import CHROME_PATH, CHROMEDRIVER_PATH, PROFILE, PROFILE_DIR
from autoppia_iwa.src.web_analysis.domain.classes import Element


class WebPageStructureExtractor:
    """
    A web page structure extractor that extracts structured data from web pages.
    """

    ALLOWED_HTML_TAGS = [
        "header",
        "nav",
        "main",
        "section",
        "article",
        "aside",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "form",
        "p",
        "div",
        "a",
        "span",
        "ul",
        "li",
        "button",
        "input",
        "select",
        "textarea",
        "img",
        "video",
        "audio",
    ]

    def __init__(self):
        pass

    async def get_elements(
        self,
        source: Union[str, BeautifulSoup],
        allowed_tags: Optional[List[str]] = None,
    ) -> tuple[List[Element], str]:
        """
        Extract structured data from a web page or BeautifulSoup object asynchronously.
        """
        allowed_tags = allowed_tags if allowed_tags else WebPageStructureExtractor.ALLOWED_HTML_TAGS

        if isinstance(source, str):
            # Ensure the URL is well-formed
            if not source.startswith("http://") and not source.startswith("https://"):
                source = "http://" + source

            if not Path(CHROMEDRIVER_PATH).exists():
                raise RuntimeError("ChromeDriver path is not valid or not set")

            async with async_playwright() as p:
                launch_options = {"headless": True}

                if PROFILE_DIR and Path(PROFILE_DIR).exists():
                    launch_options["user_data_dir"] = str(PROFILE_DIR)
                if CHROME_PATH and Path(CHROME_PATH).exists():
                    launch_options["executable_path"] = str(CHROME_PATH)

                browser = await p.chromium.launch(**launch_options)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(source)
                # Replace time.sleep(2) with async wait
                await page.wait_for_timeout(2000)

                html_source = await page.content()
                soup = BeautifulSoup(html_source, "html.parser")

                await context.close()
                await browser.close()
        else:
            soup = source

        cleaned_soup = self.__clean_soup(soup)
        elements = []
        cleaned_soup_body = cleaned_soup.find("body")
        element_id_counter = 0
        if cleaned_soup_body is None:
            cleaned_soup_body = cleaned_soup

        for soup_element in cleaned_soup_body.find_all(allowed_tags, recursive=False):
            element, element_id_counter = self.__convert_soup_element_to_element(
                soup_element, allowed_tags, None, "/", element_id_counter
            )
            if element:
                elements.append(element)

        return elements, cleaned_soup.prettify()

    def __clean_soup(self, soup: BeautifulSoup) -> BeautifulSoup:
        """
        Clean the HTML soup by removing unnecessary tags and attributes.
        """
        TAGS_TO_EXCLUDE = ["style", "script", "svg"]
        ATTRIBUTES_TO_EXCLUDE = ["class", "name", "style"]
        DATA_ATTRIBUTES_PREFIX = "data-"

        for data in soup(TAGS_TO_EXCLUDE):
            data.decompose()

        for tag in soup():
            for attribute in ATTRIBUTES_TO_EXCLUDE:
                if attribute in tag.attrs:
                    del tag[attribute]

        for tag in soup():
            for attr in list(tag.attrs):
                if attr.startswith(DATA_ATTRIBUTES_PREFIX):
                    del tag[attr]

        return soup

    def __convert_soup_element_to_element(
        self,
        soup_element,
        allowed_tags: List[str],
        parent_id: Optional[int],
        base_path: str,
        current_id: int,
    ) -> tuple[Optional[Element], int]:
        """
        Recursively extract the hierarchy of an HTML element.
        """
        if soup_element.name not in allowed_tags:
            return None, current_id

        current_id += 1
        element_id = current_id
        path = f"{base_path}/{element_id}"

        info = {
            "tag": soup_element.name,
            "attributes": dict(soup_element.attrs),
            "children": [],
            "textContent": soup_element.get_text().strip(),
            "id": soup_element.get("id"),
            "element_id": element_id,
            "parent_element_id": parent_id,
            "path": path,
            "data_attributes": {
                k: v for k, v in soup_element.attrs.items() if k.startswith("data-")
            },
        }

        if not info["data_attributes"]:
            del info["data_attributes"]

        if soup_element.name == "a":
            info["link_target"] = soup_element.get("href")
        if soup_element.name == "input":
            info["input_type"] = soup_element.get("type")
        if soup_element.name in ["input", "textarea", "select"]:
            info["value"] = soup_element.get("value")

        style_content = soup_element.get("style")
        if style_content and "display:none" in style_content.replace(" ", "").lower():
            info["invisible"] = True

        valid_keys = {f.name for f in fields(Element)}
        filtered_info = {k: v for k, v in info.items() if k in valid_keys}

        filtered_info["events_triggered"] = []
        filtered_info["analysis"] = None

        element = Element(**filtered_info)

        for child in soup_element.children:
            child_info, current_id = self.__convert_soup_element_to_element(
                child, allowed_tags, element_id, path, current_id
            )
            if child_info:
                element.children.append(child_info)

        return element, current_id
