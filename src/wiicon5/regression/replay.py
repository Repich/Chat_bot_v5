from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping
from uuid import uuid4

from wiicon5.regression.cases import RegressionCase, validate_case
from wiicon5.workbench.audit import utc_now
from wiicon5.workbench.models import jsonable
from wiicon5.workbench.store import atomic_write_text, safe_file_stem

if TYPE_CHECKING:
    from wiicon5.agent.orchestrator import AgentRunResult


@dataclass(frozen=True)
class RegressionCaseReplayResult:
    case_id: str
    question: str
    ok: bool
    source: str = ""
    artifact_type: str = ""
    trace_path: str = ""
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "ok": self.ok,
            "source": self.source,
            "artifact_type": self.artifact_type,
            "trace_path": self.trace_path,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class RegressionReplayResult:
    run_id: str
    ok: bool
    count: int
    passed: int
    failed: int
    started_at: str
    finished_at: str
    case_results: List[RegressionCaseReplayResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "ok": self.ok,
            "count": self.count,
            "passed": self.passed,
            "failed": self.failed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "case_results": [item.to_dict() for item in self.case_results],
        }


def run_regression_replay(
    cases: List[RegressionCase],
    agent,
    *,
    session_prefix: str = "regression",
) -> RegressionReplayResult:
    run_id = uuid4().hex
    started_at = utc_now()
    results: List[RegressionCaseReplayResult] = []
    for index, case in enumerate(cases, start=1):
        case_id = case.case_id or safe_file_stem(case.question)
        validation_issues = validate_case(case)
        if validation_issues:
            results.append(
                RegressionCaseReplayResult(
                    case_id=case_id,
                    question=case.question,
                    ok=False,
                    issues=[f"case_validation: {issue}" for issue in validation_issues],
                )
            )
            continue
        try:
            result = agent.handle(case.question, session_id=f"{session_prefix}-{run_id}-{index}")
            issues = replay_issues(case, result)
            results.append(
                RegressionCaseReplayResult(
                    case_id=case_id,
                    question=case.question,
                    ok=not issues,
                    source=result.source,
                    artifact_type=result.final_artifact.type if result.final_artifact else "",
                    trace_path=str(result.trace_path or ""),
                    issues=issues,
                )
            )
        except Exception as exc:
            results.append(
                RegressionCaseReplayResult(
                    case_id=case_id,
                    question=case.question,
                    ok=False,
                    issues=[f"agent_exception: {exc}"],
                )
            )
    passed = sum(1 for item in results if item.ok)
    failed = len(results) - passed
    return RegressionReplayResult(
        run_id=run_id,
        ok=failed == 0,
        count=len(results),
        passed=passed,
        failed=failed,
        started_at=started_at,
        finished_at=utc_now(),
        case_results=results,
    )


def replay_issues(case: RegressionCase, result: "AgentRunResult") -> List[str]:
    issues: List[str] = []
    if case.expected_source and result.source != case.expected_source:
        issues.append(f"expected_source {case.expected_source}, got {result.source}")
    if case.requires_clarification and result.source != "needs_clarification":
        issues.append(f"expected clarification, got {result.source}")
    if case.expected_behavior == "ok" and result.source in {
        "skill_gap",
        "skill_execution_failed",
        "query_synthesis_failed",
        "needs_goal_decomposition",
        "llm_unavailable",
    }:
        issues.append(f"expected ok behavior, got {result.source}")
    if case.expected_behavior == "uses_skills_or_synthesis" and result.source not in {
        "skill_execution_ok",
        "query_synthesis_ok",
    }:
        issues.append(f"expected skill or synthesis answer, got {result.source}")
    if case.expected_behavior == "needs_clarification" and result.source != "needs_clarification":
        issues.append(f"expected needs_clarification, got {result.source}")
    if case.expected_behavior == "skill_gap" and result.source != "skill_gap":
        issues.append(f"expected skill_gap, got {result.source}")
    artifact_type = result.final_artifact.type if result.final_artifact else ""
    if case.expected_artifact_type and artifact_type != case.expected_artifact_type:
        issues.append(f"expected artifact {case.expected_artifact_type}, got {artifact_type or '<none>'}")
    if case.expected_columns_any_of:
        columns = result_columns(result)
        if not any(all(column in columns for column in expected) for expected in case.expected_columns_any_of):
            issues.append(f"expected columns any of {case.expected_columns_any_of}, got {columns}")
    for object_name in case.must_not_use_objects:
        if object_name and object_used(result, object_name):
            issues.append(f"forbidden object used: {object_name}")
    return issues


def result_columns(result: "AgentRunResult") -> List[str]:
    artifact = result.final_artifact
    if artifact is None:
        return []
    value = artifact.value
    if isinstance(value, Mapping):
        columns = value.get("columns")
        if isinstance(columns, list):
            return [str(item) for item in columns]
        rows = value.get("rows")
        if isinstance(rows, list) and rows and isinstance(rows[0], Mapping):
            return [str(key) for key in rows[0].keys()]
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return [str(key) for key in value[0].keys()]
    return []


def object_used(result: "AgentRunResult", object_name: str) -> bool:
    payload = json.dumps(result.to_dict(), ensure_ascii=False, default=str)
    if object_name in payload:
        return True
    trace_path = Path(str(result.trace_path or ""))
    if not trace_path.exists():
        return False
    for path in trace_path.rglob("*.json"):
        try:
            if object_name in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def save_replay_result(result: RegressionReplayResult, results_dir: Path) -> Path:
    path = results_dir / f"{safe_file_stem(result.run_id)}.json"
    atomic_write_text(path, json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return path


def successful_replay_case_ids(results_dir: Path) -> set[str]:
    successful: set[str] = set()
    for result in read_replay_results(results_dir):
        if not result.get("ok"):
            continue
        for item in result.get("case_results", []):
            if isinstance(item, Mapping) and item.get("ok") and item.get("case_id"):
                successful.add(str(item["case_id"]))
    return successful


def has_successful_replay(results_dir: Path, case_ids: Iterable[str]) -> bool:
    required = {str(item).strip() for item in case_ids if str(item).strip()}
    if not required:
        return False
    return required.issubset(successful_replay_case_ids(results_dir))


def read_replay_results(results_dir: Path) -> List[Dict[str, Any]]:
    if not results_dir.exists():
        return []
    payloads: List[Dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def compact_replay_result(result: RegressionReplayResult) -> Dict[str, Any]:
    return jsonable(result.to_dict())
