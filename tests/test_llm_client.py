from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from wiicon5.llm.client import LLMProviderError, OpenAICompatibleLLMClient


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def http_error(status: int, payload: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.test/chat/completions",
        status,
        "error",
        {},
        io.BytesIO(json.dumps(payload).encode("utf-8")),
    )


class OpenAICompatibleLLMClientTests(unittest.TestCase):
    def client(self) -> OpenAICompatibleLLMClient:
        return OpenAICompatibleLLMClient(
            api_base="https://example.test",
            api_key="secret",
            model="model",
            max_retries=2,
            retry_backoff_seconds=0,
        )

    def test_retries_temporary_503_then_returns_json(self) -> None:
        success = FakeResponse(
            {"choices": [{"message": {"content": json.dumps({"query": "ВЫБРАТЬ 1"})}}]}
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=[http_error(503, {"request_id": "router-request-1"}), success],
        ) as urlopen:
            result = self.client().complete_json(system_prompt="system", user_payload={"message": "test"})

        self.assertEqual(result["query"], "ВЫБРАТЬ 1")
        self.assertEqual(urlopen.call_count, 2)

    def test_does_not_retry_authentication_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=http_error(401, {"request_id": "auth-request"})) as urlopen:
            with self.assertRaises(LLMProviderError):
                self.client().complete_json(system_prompt="system", user_payload={})

        self.assertEqual(urlopen.call_count, 1)

    def test_final_503_preserves_gateway_request_id(self) -> None:
        errors = [http_error(503, {"request_id": f"router-request-{index}"}) for index in range(3)]
        with patch("urllib.request.urlopen", side_effect=errors) as urlopen:
            with self.assertRaises(LLMProviderError) as raised:
                self.client().complete_json(system_prompt="system", user_payload={})

        self.assertEqual(urlopen.call_count, 3)
        self.assertIn("router-request-2", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
