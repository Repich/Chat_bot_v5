from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from wiicon5.intent.models import IntentResult
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.one_c_query_safety import validate_read_only_query
from wiicon5.query_synthesis import QuerySynthesisResult
from wiicon5.skills.query_template_learning import (
    LEARNED_QUERY_SCHEMA_VERSION,
    query_contract_consistency_issues,
    semantic_template_negative_checks,
    semantic_template_positive_check,
)
from wiicon5.skills.semantic_contract import SEMANTIC_CONTRACT_SCHEMA_VERSION, SemanticSkillContract


@dataclass(frozen=True)
class LearningGateCheck:
    name: str
    ok: bool
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "details": dict(self.details)}


@dataclass(frozen=True)
class LearningGateResult:
    ok: bool
    checks: List[LearningGateCheck] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [item.to_dict() for item in self.checks],
            "errors": list(self.errors),
        }


def evaluate_learning_gate(
    *,
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
    synthesis_result: QuerySynthesisResult,
    spec: Mapping[str, Any],
    config_fingerprint: str = "",
) -> LearningGateResult:
    checks: List[LearningGateCheck] = []

    fingerprint = (config_fingerprint or "").strip()
    fingerprint_ok = bool(fingerprint) and fingerprint.lower() not in {"auto", "computed", "unknown", "unresolved"}
    checks.append(
        LearningGateCheck(
            "configuration_fingerprint_resolved",
            fingerprint_ok,
            {"config_fingerprint": fingerprint},
        )
    )

    final_query = synthesis_result.trace.get("final_query")
    query = str(final_query.get("query") or "") if isinstance(final_query, Mapping) else ""
    params = dict(final_query.get("params") or {}) if isinstance(final_query, Mapping) else {}
    safety = validate_read_only_query(query, params)
    checks.append(LearningGateCheck("read_only_query", safety.ok, safety.to_dict()))

    contract = SemanticSkillContract.from_dict(spec.get("semantic_contract") if isinstance(spec, Mapping) else {})
    contract_ok = contract.schema_version == SEMANTIC_CONTRACT_SCHEMA_VERSION and bool(contract.operation)
    checks.append(
        LearningGateCheck(
            "semantic_contract_current",
            contract_ok,
            {"schema_version": contract.schema_version, "operation": contract.operation},
        )
    )

    template_schema_ok = int(spec.get("schema_version") or 0) == LEARNED_QUERY_SCHEMA_VERSION
    checks.append(
        LearningGateCheck(
            "query_template_schema_current",
            template_schema_ok,
            {"schema_version": spec.get("schema_version")},
        )
    )

    consistency_issues = query_contract_consistency_issues(spec)
    checks.append(
        LearningGateCheck(
            "query_matches_semantic_contract",
            not consistency_issues,
            {"issues": consistency_issues},
        )
    )

    sufficiency = final_sufficiency_review(synthesis_result.trace)
    sufficiency_ok = bool(sufficiency.get("sufficient")) and not bool(sufficiency.get("needs_clarification")) and not str(
        sufficiency.get("error") or ""
    ).strip()
    checks.append(
        LearningGateCheck(
            "successful_result_sufficient",
            sufficiency_ok,
            compact_sufficiency(sufficiency),
        )
    )

    replay = exact_replay_evidence(synthesis_result.trace, final_query if isinstance(final_query, Mapping) else {})
    checks.append(LearningGateCheck("exact_success_evidence", bool(replay.get("ok")), replay))

    positive = semantic_template_positive_check(intent=intent, goal=goal, spec=spec)
    checks.append(LearningGateCheck(positive["name"], bool(positive["ok"]), dict(positive.get("details") or {})))
    for negative in semantic_template_negative_checks(spec):
        checks.append(
            LearningGateCheck(
                str(negative.get("name") or "negative_contract_probe"),
                bool(negative.get("ok")),
                dict(negative.get("details") or {}),
            )
        )

    metadata_dependencies = [str(item) for item in spec.get("metadata_dependencies", []) or [] if str(item).strip()]
    checks.append(
        LearningGateCheck(
            "metadata_dependencies_recorded",
            bool(metadata_dependencies),
            {"metadata_dependencies": metadata_dependencies},
        )
    )

    errors = [check.name for check in checks if not check.ok]
    return LearningGateResult(ok=not errors, checks=checks, errors=errors)


def final_sufficiency_review(trace: Mapping[str, Any]) -> Dict[str, Any]:
    for collection_name in ["failure_solver_attempts", "attempts"]:
        attempts = trace.get(collection_name)
        if not isinstance(attempts, list):
            continue
        for attempt in reversed(attempts):
            if isinstance(attempt, Mapping) and isinstance(attempt.get("result_sufficiency"), Mapping):
                return dict(attempt["result_sufficiency"])
    steps = trace.get("successful_steps")
    if isinstance(steps, list):
        for step in reversed(steps):
            if isinstance(step, Mapping) and isinstance(step.get("sufficiency"), Mapping):
                return dict(step["sufficiency"])
    return {}


def exact_replay_evidence(trace: Mapping[str, Any], final_query: Mapping[str, Any]) -> Dict[str, Any]:
    expected_query = normalized_query(str(final_query.get("query") or ""))
    steps = trace.get("successful_steps")
    if not expected_query or not isinstance(steps, list):
        return {"ok": False, "reason": "successful_steps_missing"}
    for step in reversed(steps):
        if not isinstance(step, Mapping):
            continue
        if normalized_query(str(step.get("query") or "")) != expected_query:
            continue
        sufficiency = step.get("sufficiency") if isinstance(step.get("sufficiency"), Mapping) else {}
        return {
            "ok": bool(sufficiency.get("sufficient")) and not str(sufficiency.get("error") or "").strip(),
            "row_count": len(step.get("rows") or []),
            "columns": list(step.get("columns") or []),
        }
    return {"ok": False, "reason": "final_query_not_found_in_successful_steps"}


def compact_sufficiency(review: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: review.get(key)
        for key in ["sufficient", "partial", "missing_facts", "needs_clarification", "reasoning", "error"]
        if key in review
    }


def normalized_query(query: str) -> str:
    return " ".join(query.lower().split())
