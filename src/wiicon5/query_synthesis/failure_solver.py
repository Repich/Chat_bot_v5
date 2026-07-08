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
                "diagnostic": compact_diagnostic_payload(diagnostic_payload),
            },
            ensure_ascii=False,
            indent=2,
        )
        command = shlex.split(self.command)
        try:
            completed = subprocess.run(
                command,
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
                raw={
                    "command": command,
                    "returncode": completed.returncode,
                    "stdout_preview": stdout[:4000],
                    "stderr_preview": stderr[:4000],
                    "timeout_seconds": self.timeout_seconds,
                },
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
                    raw={
                        "command": command,
                        "returncode": completed.returncode,
                        "stdout_preview": stdout[:4000],
                        "stderr_preview": stderr[:4000],
                        "timeout_seconds": self.timeout_seconds,
                    },
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


def compact_diagnostic_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    trace = payload.get("synthesis_trace") if isinstance(payload.get("synthesis_trace"), dict) else {}
    return {
        "message": payload.get("message"),
        "intent": payload.get("intent"),
        "goal": payload.get("goal"),
        "conversation_context": compact_conversation_context(payload.get("conversation_context")),
        "gaps": payload.get("gaps"),
        "failure_error": payload.get("failure_error"),
        "synthesis_trace": {
            "final_error": trace.get("final_error"),
            "discovery_response": trace.get("discovery_response"),
            "metadata_search_terms": list(trace.get("metadata_search_terms") or [])[:40],
            "metadata_requests": compact_metadata_requests(trace.get("metadata_requests")),
            "metadata_objects": compact_metadata_objects(trace.get("metadata_objects")),
            "successful_steps": compact_successful_steps(trace.get("successful_steps")),
            "attempts": compact_attempts(trace.get("attempts")),
            "query_review_guidance": trace.get("query_review_guidance"),
            "onboarding_evidence": compact_onboarding_evidence(trace.get("onboarding_evidence")),
        },
    }


def compact_conversation_context(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    messages = value.get("messages") if isinstance(value.get("messages"), list) else []
    artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), list) else []
    return {
        "session_id": value.get("session_id"),
        "config_fingerprint": value.get("config_fingerprint"),
        "messages": messages[-8:],
        "artifacts": [compact_artifact(item) for item in artifacts[-10:] if isinstance(item, dict)],
        "resolved_entities": value.get("resolved_entities") if isinstance(value.get("resolved_entities"), list) else [],
    }


def compact_artifact(value: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": value.get("name"),
        "type": value.get("type"),
        "value_preview": preview_value(value.get("value"), max_items=5),
        "provenance": value.get("provenance"),
    }


def compact_metadata_requests(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if item.get("returned") or item.get("error"):
            result.append(
                {
                    "operation": item.get("operation"),
                    "term": item.get("term"),
                    "full_name": item.get("full_name"),
                    "source": item.get("source"),
                    "success": item.get("success"),
                    "returned": item.get("returned"),
                    "error": item.get("error"),
                }
            )
    return result[-80:]


def compact_metadata_objects(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        field_details = item.get("field_details") if isinstance(item.get("field_details"), dict) else {}
        result.append(
            {
                "full_name": item.get("full_name"),
                "synonym": item.get("synonym"),
                "source": item.get("source"),
                "trust": item.get("trust"),
                "fields": list(item.get("fields") or [])[:120],
                "table_parts": item.get("table_parts") if isinstance(item.get("table_parts"), dict) else {},
                "field_details": compact_field_details(field_details),
            }
        )
    return result


def compact_field_details(value: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name, details in list(value.items())[:140]:
        if not isinstance(details, dict):
            continue
        result[name] = {
            "synonym": details.get("Синоним") or details.get("synonym"),
            "type": details.get("Тип") or details.get("type"),
            "category": details.get("_category"),
            "source": details.get("_source"),
            "trust": details.get("_trust"),
        }
    return result


def compact_successful_steps(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for step in value[-5:]:
        if not isinstance(step, dict):
            continue
        result.append(
            {
                "step": step.get("step"),
                "query": step.get("query"),
                "params": step.get("params"),
                "columns": step.get("columns"),
                "rows": preview_value(step.get("rows"), max_items=10),
                "sufficiency": step.get("sufficiency"),
            }
        )
    return result


def compact_attempts(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for attempt in value[-10:]:
        if not isinstance(attempt, dict):
            continue
        result.append(
            {
                "attempt": attempt.get("attempt"),
                "query_response": compact_query_response(attempt.get("query_response")),
                "query": attempt.get("query"),
                "params": attempt.get("params"),
                "limit": attempt.get("limit"),
                "validation": attempt.get("validation"),
                "validation_after_reference_resolution": attempt.get("validation_after_reference_resolution"),
                "validation_after_list_param_expansion": attempt.get("validation_after_list_param_expansion"),
                "reference_value_resolution": attempt.get("reference_value_resolution"),
                "list_param_expansion": attempt.get("list_param_expansion"),
                "query_review": compact_review(attempt.get("query_review")),
                "goal_semantic_review": attempt.get("goal_semantic_review"),
                "mcp_response": compact_mcp_response(attempt.get("mcp_response")),
                "row_count": attempt.get("row_count"),
                "result_sufficiency": attempt.get("result_sufficiency"),
                "error": attempt.get("error"),
                "repeated_partial_query": attempt.get("repeated_partial_query"),
                "empty_list_params": attempt.get("empty_list_params"),
                "metadata_repair_terms": attempt.get("metadata_repair_terms"),
            }
        )
    return result


def compact_query_response(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "query": value.get("query"),
        "params": value.get("params"),
        "limit": value.get("limit"),
        "reasoning": value.get("reasoning"),
    }


def compact_review(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "ok": value.get("ok"),
        "issues": value.get("issues"),
        "warnings": value.get("warnings"),
        "sources": value.get("sources"),
    }


def compact_mcp_response(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "success": value.get("success"),
        "error": value.get("error"),
        "status_code": value.get("status_code"),
        "data_preview": preview_value(value.get("data"), max_items=10),
        "schema": value.get("schema") if isinstance(value.get("schema"), dict) else {},
    }


def compact_onboarding_evidence(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "available": value.get("available"),
        "terms": list(value.get("terms") or [])[:20],
        "query_patterns": preview_value(value.get("query_patterns"), max_items=5),
        "register_usage": preview_value(value.get("register_usage"), max_items=10),
    }


def preview_value(value: Any, *, max_items: int) -> Any:
    if isinstance(value, list):
        return [preview_value(item, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, dict):
        return {key: preview_value(item, max_items=max_items) for key, item in list(value.items())[:40]}
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "...[truncated]"
    return value


def limit_from_value(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 100
    return max(1, min(number, 1000))
