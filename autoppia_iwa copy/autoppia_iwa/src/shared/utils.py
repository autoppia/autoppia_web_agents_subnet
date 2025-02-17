import random
import string
from pathlib import Path

from bs4 import BeautifulSoup, Comment
from playwright.async_api import async_playwright

from autoppia_iwa.config.config import CHROME_PATH, CHROMEDRIVER_PATH, PROFILE, PROFILE_DIR
from autoppia_iwa.src.data_generation.domain.tests_classes import (
    CheckEventEmittedTest,
    CheckPageViewEventTest,
    FindInHtmlTest,
)


async def extract_html(page_url):
    """
    Extract HTML from a page using async Playwright.
    """
    if not Path(CHROMEDRIVER_PATH).exists():
        raise RuntimeError("ChromeDriver path is not valid or not set")

    async with async_playwright() as p:
        launch_options = {"headless": True}

        # If CHROME_PATH is provided
        if CHROME_PATH and Path(CHROME_PATH).exists():
            launch_options["executable_path"] = str(CHROME_PATH)

        if PROFILE_DIR and Path(PROFILE_DIR).exists():
            # Use launch_persistent_context when PROFILE_DIR is provided.
            context = await p.chromium.launch_persistent_context(str(PROFILE_DIR), **launch_options)
        else:
            browser = await p.chromium.launch(**launch_options)
            context = await browser.new_context()

        page = await context.new_page()
        await page.goto(page_url)
        html = await page.content()

        await context.close()
        # If using a non-persistent context, also close the browser.
        if not (PROFILE_DIR and Path(PROFILE_DIR).exists()):
            await browser.close()
        return html


def clean_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove unwanted tags
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.decompose()

    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove hidden elements
    for tag in soup.find_all():
        if tag.has_attr("style") and "display: none" in tag["style"]:
            tag.decompose()
            continue
        if tag.has_attr("hidden"):
            tag.decompose()
            continue

    # Remove inline event attributes and other non-essential attributes
    for tag in soup.find_all():
        event_attrs = [attr for attr in tag.attrs if attr.startswith("on")]
        for attr in event_attrs:
            del tag[attr]

        for attr in ["class", "id", "style"]:
            if attr in tag.attrs:
                del tag[attr]

    # Remove empty elements
    for tag in soup.find_all():
        if not tag.text.strip() and not tag.find_all():
            tag.decompose()

    cleaned_html = soup.body if soup.body else soup
    return cleaned_html.prettify()


def instantiate_test(test_data):
    if test_data["test_type"] == "frontend":
        return FindInHtmlTest(
            description=test_data["description"],
            test_type=test_data["test_type"],
            keywords=test_data["keywords"],
        )
    elif test_data["test_type"] == "backend":
        if "page_view_url" in test_data:
            return CheckPageViewEventTest(
                description=test_data["description"],
                test_type=test_data["test_type"],
                page_view_url=test_data["page_view_url"],
            )
        return CheckEventEmittedTest(
            description=test_data["description"],
            test_type=test_data["test_type"],
            event_name=test_data["event_name"],
        )
    else:
        raise ValueError(f"Unknown test type: {test_data['test_type']}")


def generate_random_web_agent_id(length=16):
    """
    Generates a random alphanumeric string for the web_agent ID.
    """
    letters_and_digits = string.ascii_letters + string.digits
    return "".join(random.choice(letters_and_digits) for _ in range(length))
