import datetime
from typing import List
from urllib.parse import urlparse

import aiohttp
import requests
from requests.exceptions import RequestException

from autoppia_iwa.src.backend_demo_web.classes import BackendEvent


class BackendDemoWebService:
    """
    Service for interacting with backend of the demo web endpoints.
    """

    def __init__(self, base_url: str) -> None:
        """
        Initialize the service.

        Args:
            base_url (str): Base URL for the backend API.
        """
        self.base_url = self._parse_base_url(base_url)
        self.session = requests.Session()

    def __del__(self) -> None:
        """Ensure proper cleanup of resources."""
        self.session.close()

    def get_backend_events(self, web_agent_id: str) -> List[BackendEvent]:
        """
        Fetch recent events from the backend.

        Args:
            web_agent_id (str): The ID of the web_agent to filter events for.

        Returns:
            List[BackendEvent]: A list of `BackendEvent` objects retrieved from the backend.

        """
        endpoint = f"{self.base_url}/api/events/list/"
        headers = {"X-WebAgent-Id": web_agent_id}
        try:
            response = self.session.get(endpoint, headers=headers)
            response.raise_for_status()  # Raise an exception for bad status codes
            events_data = response.json()
            return [BackendEvent(**event) for event in events_data]
        except RequestException as e:
            print(f"[ERROR] Network error while fetching backend events: {e}")
        except ValueError as e:
            print(f"[ERROR] Error parsing JSON response: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected error fetching backend events: {e}")
        return []  # Return an empty list in case of any failure

    def reset_backend_events_db(self, web_agent_id: str) -> None:
        """
        Resets backend events for the given task.

        Args:
            web_agent_id (str): Identifier for the web_agent.

        Raises:
            RuntimeError: If the reset operation fails.
        """
        endpoint = f"{self.base_url}/api/events/reset/"
        headers = {"X-WebAgent-Id": web_agent_id}
        try:
            response = self.session.delete(endpoint, headers=headers, timeout=10)
            response.raise_for_status()
            if response.status_code == 204:
                print(f"[INFO] Successfully reset events for web_agent '{web_agent_id}'.")
            else:
                print(f"[WARNING] Reset operation completed with unexpected status: {response.status_code}")
        except RequestException as e:
            error_message = f"[ERROR] Failed to reset backend events for web_agent '{web_agent_id}': {e}"
            print(error_message)
            raise RuntimeError(error_message) from e

    async def send_page_view_event(self, url: str, web_agent_id: str) -> None:
        """
        Sends a PageView event to the backend.

        Args:
            url (str): The current page URL.
            web_agent_id (str): The ID of the web_agent.
        """
        parsed_url = urlparse(url)
        path_only = parsed_url.path
        payload = {
            "event_type": "page_view",
            "description": "Page viewed",
            "data": {
                "url": path_only,
                "timestamp": datetime.datetime.now().isoformat(),
            },
            "web_agent_id": web_agent_id,
        }
        endpoint = f"{self.base_url}/api/events/add/"
        headers = {"X-WebAgent-Id": web_agent_id}

        # Use aiohttp for async request handling
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(endpoint, json=payload, headers=headers, timeout=10) as response:
                    response.raise_for_status()
                    print(f"[INFO] PageView event sent successfully. Status: {response.status}")
            except aiohttp.ClientError as e:
                print(f"[ERROR] Failed to send PageView event: {e}")
            except Exception as e:
                print(f"[ERROR] Unexpected error while sending PageView event: {e}")

    @staticmethod
    def _parse_base_url(url: str) -> str:
        """
        Extract the base URL and detect the application type.

        Args:
            url (str): The URL to parse.

        Returns:
            str: A tuple containing the base URL and the application type.
        """
        parsed = urlparse(url)
        if not parsed.scheme:
            url = f"http://{url}"
            parsed = urlparse(url)

        return f"{parsed.scheme}://{parsed.netloc}"
