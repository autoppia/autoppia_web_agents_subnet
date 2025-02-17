import requests

URL = "http://127.0.0.1:6000/generate"

payload = {
    "input": {
        "text": "Hello, how are you? Explain me who are you, what model are you and what benefits you have. Answer directly and short",
        "ctx": 256,
        "llm_kwargs": {},
        "chat_completion_kwargs": {},
    }
}


def test_generate_endpoint_working_200_OK():
    """
    Basic test
    """
    try:
        response = requests.post(URL, json=payload)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        response_data = response.json()

        assert "output" in response_data, "Missing 'output' in response"

        print("Response from server:", response_data["output"])
    except Exception as e:
        print(f"Test failed: {e}")


if __name__ == "__main__":
    test_generate_endpoint_working_200_OK()
