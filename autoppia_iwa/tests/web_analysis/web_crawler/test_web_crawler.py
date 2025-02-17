from urllib.parse import urljoin, urlparse

import matplotlib.pyplot as plt
import networkx as nx
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from autoppia_iwa.src.web_analysis.domain.classes import WebCrawlerConfig


class WebCrawler:
    def __init__(self, startUrl):
        parsed = urlparse(startUrl)
        self.domain = f"{parsed.scheme}://{parsed.netloc}"

    def crawl_urls(self, start_url, max_depth=2):
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
        Renamed to 'get_links_selenium' but uses async Playwright.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url)
            await page.wait_for_timeout(10000)

            html = await page.content()
            soup_local = BeautifulSoup(html, "html.parser")
            links = soup_local.find_all("a", href=True)
            urls = [link["href"] for link in links if link["href"].startswith("http")]

            await context.close()
            await browser.close()
        return urls

    def create_graph(self, home_url):
        graph = nx.DiGraph()
        graph.add_node(home_url)
        links = self.crawl_urls(start_url=home_url, max_depth=1)

        for link in links:
            graph.add_edge(home_url, link)

        return graph, links


# Define the configuration for the web crawler
crawler_config = WebCrawlerConfig(start_url="https://ajedrezenmadrid.com", max_depth=2)

# Initialize the web crawler with the start URL
web_crawler = WebCrawler(crawler_config.start_url)

# Use the crawler to get URLs (sync method)
crawled_urls = web_crawler.crawl_urls(crawler_config.start_url, crawler_config.max_depth)

print("Crawled URLs:")
for url in crawled_urls:
    print(url)

# Get links from a specific URL using async Playwright.
# (Example usage with asyncio run; adapt to your existing async flow.)
import asyncio

async def run_async_playwright():
    selenium_links = await web_crawler.get_links_selenium("https://ajedrezenmadrid.com")
    print("Links obtained using async Playwright:")
    for link in selenium_links:
        print(link)

asyncio.run(run_async_playwright())

# Create a graph of the crawled URLs
graph, links = web_crawler.create_graph(crawler_config.start_url)

print("Links in the graph:")
for link in links:
    print(link)

# Visualize the graph
plt.figure(figsize=(12, 12))
nx.draw(
    graph,
    with_labels=True,
    node_size=3000,
    node_color="skyblue",
    font_size=10,
    font_weight="bold",
)
plt.title("Web Crawler Graph")
plt.savefig("web_crawler_graph.png")
