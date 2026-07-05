from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class RegressionCase:
    question: str
    expected_behavior: str
    case_id: str = ""
    expected_source: str = ""
    expected_artifact_type: str = ""
    expected_columns_any_of: List[List[str]] = field(default_factory=list)
    requires_clarification: bool = False
    must_not_use_objects: List[str] = field(default_factory=list)
    trace_path: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "case_id": self.case_id or case_id_for_question(self.question),
            "question": self.question,
            "expected_behavior": self.expected_behavior,
            "expected_source": self.expected_source,
            "expected_artifact_type": self.expected_artifact_type,
            "expected_columns_any_of": [list(item) for item in self.expected_columns_any_of],
            "requires_clarification": self.requires_clarification,
            "must_not_use_objects": list(self.must_not_use_objects),
            "trace_path": self.trace_path,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "RegressionCase":
        question = str(payload.get("question") or "")
        return cls(
            question=question,
            expected_behavior=str(payload.get("expected_behavior") or "uses_skills_or_synthesis"),
            case_id=str(payload.get("case_id") or case_id_for_question(question)),
            expected_source=str(payload.get("expected_source") or ""),
            expected_artifact_type=str(payload.get("expected_artifact_type") or ""),
            expected_columns_any_of=[
                [str(value) for value in item]
                for item in payload.get("expected_columns_any_of", []) or []
                if isinstance(item, list)
            ],
            requires_clarification=bool(payload.get("requires_clarification")),
            must_not_use_objects=[str(item) for item in payload.get("must_not_use_objects", []) or []],
            trace_path=str(payload.get("trace_path") or ""),
        )


def case_from_trace(trace_path: Path, *, expected_ok: bool = False) -> RegressionCase:
    user_message = read_json(trace_path / "input" / "user_message.json")
    result = read_json(trace_path / "result" / "result.json")
    final_artifact = result.get("final_artifact") if isinstance(result.get("final_artifact"), dict) else {}
    question = str(user_message.get("message") or "")
    return RegressionCase(
        case_id=case_id_for_question(question),
        question=question,
        expected_behavior="ok" if expected_ok else "uses_skills_or_synthesis",
        expected_source=str(result.get("source") or ""),
        expected_artifact_type=str(final_artifact.get("type") or ""),
        requires_clarification=str(result.get("source") or "") == "needs_clarification",
        trace_path=str(trace_path),
    )


def save_case(case: RegressionCase, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_cases(cases_path: Path) -> List[RegressionCase]:
    paths = [cases_path] if cases_path.is_file() else sorted(cases_path.glob("*.json"))
    return [RegressionCase.from_dict(read_json(path)) for path in paths]


def run_regression_cases(cases: List[RegressionCase]) -> Dict[str, object]:
    failures = []
    for index, case in enumerate(cases, start=1):
        issues = validate_case(case)
        if issues:
            failures.append({"index": index, "question": case.question, "issues": issues})
    return {"ok": not failures, "count": len(cases), "failures": failures}


def validate_case(case: RegressionCase) -> List[str]:
    issues = []
    if not case.question:
        issues.append("missing question")
    if case.expected_behavior not in {"ok", "uses_skills_or_synthesis", "needs_clarification", "skill_gap"}:
        issues.append("unsupported expected_behavior")
    if case.expected_behavior == "ok" and case.expected_source in {"", "skill_gap", "skill_execution_failed"}:
        issues.append("expected ok case must have successful expected_source")
    return issues


def read_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def case_filename(question: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in question).strip("_")
    while "__" in safe:
        safe = safe.replace("__", "_")
    return (safe[:80] or "regression_case") + ".json"


def case_id_for_question(question: str) -> str:
    return case_filename(question).removesuffix(".json")
