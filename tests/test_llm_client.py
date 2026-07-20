from __future__ import annotations

import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from wiicon5.llm.client import (
    DATA_CLASSIFICATION_PUBLIC,
    LLMDataBoundaryError,
    LLMProviderError,
    OpenAICompatibleLLMClient,
)


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
            trust_zone="internal",
            internal_allowed_hosts=["example.test"],
        )

    def test_external_provider_blocks_confidential_payload_before_network(self) -> None:
        client = OpenAICompatibleLLMClient(
            api_base="https://external.example/v1",
            api_key="secret",
            model="model",
            trust_zone="external",
        )
        with self.assertLogs("wiicon5.llm.client", level="WARNING") as audit, patch(
            "urllib.request.urlopen"
        ) as urlopen:
            with self.assertRaises(LLMDataBoundaryError):
                client.complete_json(
                    system_prompt="system",
                    user_payload={"message": "Иванов Иван, +7 999 111-22-33"},
                )

        urlopen.assert_not_called()
        combined_audit = "\n".join(audit.output)
        self.assertIn("decision=block", combined_audit)
        self.assertIn("payload_sha256=", combined_audit)
        self.assertNotIn("Иванов", combined_audit)
        self.assertNotIn("999 111", combined_audit)

    def test_external_provider_allows_only_explicit_public_payload(self) -> None:
        client = OpenAICompatibleLLMClient(
            api_base="https://external.example/v1",
            api_key="secret",
            model="model",
            trust_zone="external",
        )
        response = FakeResponse(
            {"choices": [{"message": {"content": json.dumps({"answer": "pong"})}}]}
        )
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = client.complete_json(
                system_prompt="Return JSON.",
                user_payload={"message": "ping"},
                data_classification=DATA_CLASSIFICATION_PUBLIC,
            )

        self.assertEqual(result["answer"], "pong")
        self.assertEqual(urlopen.call_count, 1)

    def test_external_provider_allows_confidential_payload_only_after_explicit_opt_in(self) -> None:
        client = OpenAICompatibleLLMClient(
            api_base="https://api.openai.example/v1",
            api_key="secret",
            model="gpt-test",
            trust_zone="external",
            allow_external_confidential_data=True,
        )
        response = FakeResponse(
            {"choices": [{"message": {"content": json.dumps({"answer": "ok"})}}]}
        )
        with self.assertLogs("wiicon5.llm.client", level="WARNING") as audit, patch(
            "urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            result = client.complete_json(
                system_prompt="system",
                user_payload={"message": "Иванов Иван, +7 999 111-22-33"},
            )

        self.assertEqual(result["answer"], "ok")
        self.assertEqual(urlopen.call_count, 1)
        combined_audit = "\n".join(audit.output)
        self.assertIn("decision=allow", combined_audit)
        self.assertIn("external_confidential_opt_in=True", combined_audit)
        self.assertNotIn("Иванов", combined_audit)
        self.assertNotIn("999 111", combined_audit)

    def test_internal_provider_requires_explicit_hostname_allowlist(self) -> None:
        with self.assertRaisesRegex(ValueError, "WIICON5_INTERNAL_LLM_ALLOWED_HOSTS"):
            OpenAICompatibleLLMClient(
                api_base="https://glm.internal.example/v1",
                api_key="secret",
                model="glm-5.2",
                trust_zone="internal",
                internal_allowed_hosts=[],
            )
        with self.assertRaisesRegex(ValueError, "not in WIICON5_INTERNAL_LLM_ALLOWED_HOSTS"):
            OpenAICompatibleLLMClient(
                api_base="https://glm.internal.example/v1",
                api_key="secret",
                model="glm-5.2",
                trust_zone="internal",
                internal_allowed_hosts=["another.internal.example"],
            )

    def test_runtime_source_has_no_explicit_public_llm_calls(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src" / "wiicon5"
        offenders = []
        for path in source_root.rglob("*.py"):
            if path.as_posix().endswith("/llm/client.py"):
                continue
            if "DATA_CLASSIFICATION_PUBLIC" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(source_root)))

        self.assertEqual(offenders, [])

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

    def test_guardrail_mask_failure_is_not_retried_with_identical_payload(self) -> None:
        error = http_error(
            503,
            {
                "error": {"code": "router_v4_guardrails_mask_failed"},
                "request_id": "mask-request-1",
            },
        )
        with patch("urllib.request.urlopen", side_effect=error) as urlopen:
            with self.assertRaises(LLMProviderError) as raised:
                self.client().complete_json(system_prompt="system", user_payload={})

        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("mask-request-1", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
