from urllib.parse import urljoin, urlparse
import networkx as nx
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


class WebCrawler:
    """
    A web crawler that crawls URLs starting from a given start URL.

    Args:
        start_url (str): The URL to start crawling from.

    Attributes:
        domain (str): The domain of the start URL.
    """

    def __init__(self, start_url):
        parsed = urlparse(start_url)
        self.domain = f"{parsed.scheme}://{parsed.netloc}"

    def crawl_urls(self, start_url, max_depth=2):
        """
        Crawl URLs starting from the given start URL (synchronous - uses requests).
        """
        visited_urls = set()
        all_urls = []

        def strip_query_params(url):
            parsed_local = urlparse(url)
            return f"{parsed_local.scheme}://{parsed_local.netloc}{parsed_local.path}"

        def _crawl(url, depth):
            if not url.startswith(self.domain):
                return

            normalized_url = strip_query_params(url)

            if normalized_url in visited_urls:
                return
            if depth > max_depth:
                return

            visited_urls.add(normalized_url)
            all_urls.append(url)

            try:
                response = requests.get(url)
            except Exception as e:
                print(f"Failed to fetch {url}. Reason: {e}")
                return

            if response.status_code != 200:
                return

            soup_local = BeautifulSoup(response.text, "html.parser")
            for a_tag in soup_local.find_all("a"):
                new_url = a_tag.get("href")
                if new_url:
                    new_url = urljoin(url, new_url)
                    _crawl(new_url, depth + 1)

        _crawl(start_url, 0)
        return all_urls

    async def get_links_selenium(self, url):
        """
        Get links from a URL using the async Playwright API.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto(url)
            # Wait up to 10 seconds for the page to load
            await page.wait_for_timeout(10000)

            html = await page.content()
            soup_local = BeautifulSoup(html, "html.parser")
            links = soup_local.find_all("a", href=True)
            urls = [link["href"] for link in links if link["href"].startswith("http")]

            await context.close()
            await browser.close()
        return urls

    def create_graph(self, home_url):
        """
        Creates a directed graph of links from the given home_url, depth=1.
        """
        graph = nx.DiGraph()
        graph.add_node(home_url)
        links = self.crawl_urls(start_url=home_url, max_depth=1)
        for link in links:
            graph.add_edge(home_url, link)
        return graph, links
