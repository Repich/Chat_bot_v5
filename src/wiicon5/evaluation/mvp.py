from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4


SUCCESS_SOURCES = {"query_synthesis_ok", "skill_execution_ok"}


@dataclass(frozen=True)
class MvpEvaluationCase:
    case_id: str
    cold_question: str
    warm_question: str
    warm_expectation: str = "reuse_new_skill"
    description: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MvpEvaluationCase":
        return cls(
            case_id=str(payload.get("case_id") or "").strip(),
            cold_question=str(payload.get("cold_question") or "").strip(),
            warm_question=str(payload.get("warm_question") or "").strip(),
            warm_expectation=str(payload.get("warm_expectation") or "reuse_new_skill").strip(),
            description=str(payload.get("description") or "").strip(),
        )

    def validation_errors(self) -> List[str]:
        errors: List[str] = []
        if not self.case_id:
            errors.append("case_id_missing")
        if not self.cold_question:
            errors.append("cold_question_missing")
        if not self.warm_question:
            errors.append("warm_question_missing")
        if self.warm_expectation not in {"reuse_new_skill", "reuse_any_skill", "do_not_reuse_new_skill"}:
            errors.append("warm_expectation_invalid")
        return errors


@dataclass(frozen=True)
class MvpEvaluationCaseResult:
    case_id: str
    ok: bool
    warm_expectation: str = ""
    cold_source: str = ""
    warm_source: str = ""
    created_skill_ids: List[str] = field(default_factory=list)
    warm_plan_skill_ids: List[str] = field(default_factory=list)
    reused_created_skill_ids: List[str] = field(default_factory=list)
    cold_trace_path: str = ""
    warm_trace_path: str = ""
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "ok": self.ok,
            "warm_expectation": self.warm_expectation,
            "cold_source": self.cold_source,
            "warm_source": self.warm_source,
            "created_skill_ids": list(self.created_skill_ids),
            "warm_plan_skill_ids": list(self.warm_plan_skill_ids),
            "reused_created_skill_ids": list(self.reused_created_skill_ids),
            "cold_trace_path": self.cold_trace_path,
            "warm_trace_path": self.warm_trace_path,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class MvpEvaluationResult:
    run_id: str
    ok: bool
    started_at: str
    finished_at: str
    case_results: List[MvpEvaluationCaseResult]

    def to_dict(self) -> Dict[str, Any]:
        positive = [item for item in self.case_results if item.warm_expectation == "reuse_new_skill"]
        reusable = [
            item
            for item in self.case_results
            if item.warm_expectation in {"reuse_new_skill", "reuse_any_skill"}
        ]
        return {
            "run_id": self.run_id,
            "ok": self.ok,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": {
                "cases": len(self.case_results),
                "passed": sum(1 for item in self.case_results if item.ok),
                "failed": sum(1 for item in self.case_results if not item.ok),
                "cold_answer_rate": ratio(
                    sum(1 for item in self.case_results if item.cold_source in SUCCESS_SOURCES),
                    len(self.case_results),
                ),
                "warm_answer_rate": ratio(
                    sum(1 for item in self.case_results if item.warm_source in SUCCESS_SOURCES),
                    len(self.case_results),
                ),
                "created_skill_reuse_rate": ratio(
                    sum(1 for item in positive if item.reused_created_skill_ids),
                    len(positive),
                ),
                "warm_skill_plan_rate": ratio(
                    sum(1 for item in reusable if item.warm_source == "skill_execution_ok" and item.warm_plan_skill_ids),
                    len(reusable),
                ),
            },
            "cases": [item.to_dict() for item in self.case_results],
        }


def load_mvp_cases(path: Path) -> List[MvpEvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("cases") if isinstance(payload, Mapping) else payload
    if not isinstance(items, list):
        raise ValueError("MVP evaluation file must contain a list or an object with a cases list.")
    return [MvpEvaluationCase.from_dict(item) for item in items if isinstance(item, Mapping)]


def run_mvp_evaluation(
    cases: Iterable[MvpEvaluationCase],
    agent=None,
    *,
    agent_factory: Optional[Callable[[MvpEvaluationCase], Any]] = None,
) -> MvpEvaluationResult:
    if agent is None and agent_factory is None:
        raise ValueError("agent_or_agent_factory_required")
    run_id = uuid4().hex
    started_at = utc_iso()
    results: List[MvpEvaluationCaseResult] = []
    for index, case in enumerate(cases, start=1):
        validation_errors = case.validation_errors()
        if validation_errors:
            results.append(
                MvpEvaluationCaseResult(
                    case_id=case.case_id,
                    ok=False,
                    warm_expectation=case.warm_expectation,
                    issues=validation_errors,
                )
            )
            continue
        try:
            case_agent = agent_factory(case) if agent_factory is not None else agent
        except Exception as exc:
            results.append(exception_case_result(case, "agent_factory", exc))
            continue
        before = learned_skill_ids(case_agent)
        try:
            cold = case_agent.handle(case.cold_question, session_id=f"mvp-{run_id}-{index}-cold")
        except Exception as exc:
            results.append(exception_case_result(case, "cold", exc))
            continue
        after_cold = learned_skill_ids(case_agent)
        created = sorted(after_cold - before)
        try:
            warm = case_agent.handle(case.warm_question, session_id=f"mvp-{run_id}-{index}-warm")
        except Exception as exc:
            results.append(
                MvpEvaluationCaseResult(
                    case_id=case.case_id,
                    ok=False,
                    warm_expectation=case.warm_expectation,
                    cold_source=cold.source,
                    created_skill_ids=created,
                    cold_trace_path=str(cold.trace_path or ""),
                    issues=[exception_issue("warm", exc)],
                )
            )
            continue
        warm_plan_ids = plan_skill_ids(warm)
        reused = sorted(set(warm_plan_ids) & set(created))
        issues: List[str] = []
        if cold.source not in SUCCESS_SOURCES:
            issues.append(f"cold_answer_failed:{cold.source}")
        if warm.source not in SUCCESS_SOURCES:
            issues.append(f"warm_answer_failed:{warm.source}")
        if case.warm_expectation == "reuse_new_skill":
            if not created:
                issues.append("new_skill_not_created")
            if not reused:
                issues.append("created_skill_not_reused")
            if warm.source != "skill_execution_ok":
                issues.append(f"warm_did_not_use_skill:{warm.source}")
        elif case.warm_expectation == "reuse_any_skill":
            if warm.source != "skill_execution_ok" or not warm_plan_ids:
                issues.append(f"warm_did_not_use_skill:{warm.source}")
        elif reused:
            issues.append("false_reuse_of_cold_skill")
        results.append(
            MvpEvaluationCaseResult(
                case_id=case.case_id,
                ok=not issues,
                warm_expectation=case.warm_expectation,
                cold_source=cold.source,
                warm_source=warm.source,
                created_skill_ids=created,
                warm_plan_skill_ids=warm_plan_ids,
                reused_created_skill_ids=reused,
                cold_trace_path=str(cold.trace_path or ""),
                warm_trace_path=str(warm.trace_path or ""),
                issues=issues,
            )
        )
    return MvpEvaluationResult(
        run_id=run_id,
        ok=all(item.ok for item in results),
        started_at=started_at,
        finished_at=utc_iso(),
        case_results=results,
    )


def exception_case_result(
    case: MvpEvaluationCase,
    stage: str,
    exc: Exception,
) -> MvpEvaluationCaseResult:
    return MvpEvaluationCaseResult(
        case_id=case.case_id,
        ok=False,
        warm_expectation=case.warm_expectation,
        issues=[exception_issue(stage, exc)],
    )


def exception_issue(stage: str, exc: Exception) -> str:
    message = " ".join(str(exc).split())[:500]
    return f"{stage}_exception:{type(exc).__name__}:{message}"


def learned_skill_ids(agent) -> set[str]:
    registry = getattr(agent, "registry", None)
    if registry is None:
        return set()
    return {
        skill.skill_id
        for skill in registry.all()
        if skill.implementation_strategy == "learned_query" and skill.status.value in {"verified", "stable"}
    }


def plan_skill_ids(result) -> List[str]:
    plan = getattr(result, "plan", None)
    if plan is None:
        return []
    return [node.skill_id for node in plan.nodes]


def save_mvp_evaluation(result: MvpEvaluationResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
