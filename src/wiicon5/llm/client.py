from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLMProviderError(Exception):
    pass


class LLMClient(ABC):
    @abstractmethod
    def complete_json(self, *, system_prompt: str, user_payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        temperature: float = 0.0,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def complete_json(self, *, system_prompt: str, user_payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        raw = self._post_chat_completions(payload)
        content = response_content(raw)
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = extract_json_object(content)
        if not isinstance(parsed, dict):
            raise LLMProviderError("LLM response JSON root must be an object.")
        return parsed

    def _post_chat_completions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(response.status)
                raw_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise LLMProviderError(f"LLM HTTP {exc.code}: {raw_body[:1000]}") from exc
        except OSError as exc:
            raise LLMProviderError(str(exc)) from exc
        if status_code >= 400:
            raise LLMProviderError(f"LLM HTTP {status_code}: {raw_body[:1000]}")
        try:
            data = json.loads(raw_body)
        except ValueError as exc:
            raise LLMProviderError("LLM returned non-JSON HTTP body.") from exc
        if not isinstance(data, dict):
            raise LLMProviderError("LLM HTTP response JSON root must be an object.")
        return data


class ScriptedLLMClient(LLMClient):
    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def complete_json(self, *, system_prompt: str, user_payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"system_prompt": system_prompt, "user_payload": user_payload})
        if not self.responses:
            raise LLMProviderError("No scripted LLM response.")
        return self.responses.pop(0)


def response_content(response: Dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderError("LLM response has no choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMProviderError("LLM choice must be an object.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMProviderError("LLM choice has no message object.")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMProviderError("LLM message content must be a string.")
    return content


def extract_json_object(text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise LLMProviderError("LLM response does not contain a JSON object.")
    raw_json = match.group(0)
    try:
        parsed = json.loads(raw_json)
    except ValueError as exc:
        preview = raw_json[:500].replace("\n", "\\n")
        raise LLMProviderError(f"LLM response contains invalid JSON object: {preview}") from exc
    if not isinstance(parsed, dict):
        raise LLMProviderError("Extracted JSON root must be an object.")
    return parsed
