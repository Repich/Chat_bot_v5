from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from wiicon5.llm.client import LLMClient, LLMProviderError, extract_json_object


FAILURE_SOLVER_PROMPT = """
Ты аварийный эксперт WIICON ChatBot по запросам 1С.

Тебе передают полный диагностический контекст неудачного построения запроса:
исходный вопрос пользователя, цель, контекст диалога, метаданные 1С,
попытки построения запросов, ответы MCP и причину отказа.

Твоя задача:
1. Если можно получить ответ без изменения кода бота, верни action="retry_query"
   и новый безопасный запрос на языке запросов 1С.
2. Если проблема требует изменения кода, архитектуры, валидатора или недостающих
   возможностей MCP, верни action="needs_developer".
3. Если данных или метаданных недостаточно, верни action="cannot_solve".

Нельзя:
- предлагать изменение исходного кода как часть retry_query;
- возвращать DDL/DML, запись, удаление, изменение данных;
- повторять тот же промежуточный запрос, который уже признан недостаточным;
- выдумывать неподтвержденные поля, если в диагностике есть проверенные метаданные.

Ответ должен быть JSON-объектом:
{
  "action": "retry_query | needs_developer | cannot_solve",
  "query": "1C query text, only for retry_query",
  "params": {},
  "limit": 100,
  "reasoning": "кратко почему это решает проблему",
  "answer_guidance": "как интерпретировать строки результата для пользователя",
  "developer_note": "что передать разработчику, если action != retry_query"
}
""".strip()


@dataclass(frozen=True)
class FailureSolverDecision:
    action: str
    query: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    limit: int = 100
    reasoning: str = ""
    answer_guidance: str = ""
    developer_note: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "FailureSolverDecision":
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"retry_query", "needs_developer", "cannot_solve", "unavailable"}:
            action = "cannot_solve"
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        limit = limit_from_value(payload.get("limit"))
        return cls(
            action=action,
            query=str(payload.get("query") or "").strip(),
            params=dict(params),
            limit=limit,
            reasoning=str(payload.get("reasoning") or "").strip(),
            answer_guidance=str(payload.get("answer_guidance") or "").strip(),
            developer_note=str(payload.get("developer_note") or "").strip(),
            raw=dict(payload),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "query": self.query,
            "params": dict(self.params),
            "limit": self.limit,
            "reasoning": self.reasoning,
            "answer_guidance": self.answer_guidance,
            "developer_note": self.developer_note,
            "raw": dict(self.raw),
        }


class FailureSolver:
    def solve(self, diagnostic_payload: Dict[str, Any]) -> FailureSolverDecision:
        raise NotImplementedError


class LLMFailureSolver(FailureSolver):
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def solve(self, diagnostic_payload: Dict[str, Any]) -> FailureSolverDecision:
        payload = dict(diagnostic_payload)
        payload["response_schema"] = {
            "action": "retry_query | needs_developer | cannot_solve",
            "query": "1C query text for retry_query",
            "params": {},
            "limit": 100,
            "reasoning": "short reasoning",
            "answer_guidance": "how to phrase final answer",
            "developer_note": "developer handoff when needed",
        }
        response = self.llm_client.complete_json(
            system_prompt=FAILURE_SOLVER_PROMPT,
            user_payload=payload,
        )
        return FailureSolverDecision.from_payload(response)


class CodexCliFailureSolver(FailureSolver):
    def __init__(self, *, command: str, timeout_seconds: float = 180.0) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds

    def solve(self, diagnostic_payload: Dict[str, Any]) -> FailureSolverDecision:
        if not self.command.strip():
            return FailureSolverDecision(
                action="unavailable",
                developer_note="Codex CLI failure solver command is not configured.",
            )
        stdin_payload = json.dumps(
            {
                "system_prompt": FAILURE_SOLVER_PROMPT,
                "diagnostic": diagnostic_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            completed = subprocess.run(
                shlex.split(self.command),
                input=stdin_payload,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return FailureSolverDecision(action="unavailable", developer_note=str(exc))
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if completed.returncode != 0:
            return FailureSolverDecision(
                action="unavailable",
                developer_note=f"Codex CLI failure solver exited with {completed.returncode}: {stderr[:1000]}",
            )
        try:
            parsed = json.loads(stdout)
        except ValueError:
            try:
                parsed = extract_json_object(stdout)
            except LLMProviderError as exc:
                return FailureSolverDecision(
                    action="unavailable",
                    developer_note=f"Codex CLI failure solver returned non-JSON output: {exc}",
                    raw={"stdout_preview": stdout[:2000], "stderr_preview": stderr[:1000]},
                )
        if not isinstance(parsed, dict):
            return FailureSolverDecision(action="unavailable", developer_note="Codex CLI response JSON root is not an object.")
        return FailureSolverDecision.from_payload(parsed)


class UnavailableFailureSolver(FailureSolver):
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def solve(self, diagnostic_payload: Dict[str, Any]) -> FailureSolverDecision:
        return FailureSolverDecision(action="unavailable", developer_note=self.reason)


def failure_diagnostic_payload(
    *,
    message: str,
    intent: Dict[str, Any],
    goal: Optional[Dict[str, Any]],
    conversation_context: Dict[str, Any],
    gaps: Any,
    failure_error: str,
    synthesis_trace: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "message": message,
        "intent": intent,
        "goal": goal,
        "conversation_context": conversation_context,
        "gaps": gaps,
        "failure_error": failure_error,
        "synthesis_trace": synthesis_trace,
    }


def limit_from_value(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 100
    return max(1, min(number, 1000))
