from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


SEVERITY_ERROR = "error"
SEVERITY_REPAIR_REQUIRED = "repair_required"
SEVERITY_CLARIFICATION = "clarification"
SEVERITY_WARNING = "warning"
SEVERITY_LEARN_ONLY_BLOCKER = "learn_only_blocker"

BLOCKING_SEVERITIES = {SEVERITY_ERROR, SEVERITY_REPAIR_REQUIRED, SEVERITY_CLARIFICATION}
REPAIR_SEVERITIES = {SEVERITY_ERROR, SEVERITY_REPAIR_REQUIRED}


def semantic_issue(
    *,
    code: str,
    message: str,
    severity: str = SEVERITY_REPAIR_REQUIRED,
    repair_hint: str = "",
    clarification_question: str = "",
    clarification_options: Optional[List[str]] = None,
    allowed_actions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if repair_hint:
        payload["repair_hint"] = repair_hint
    if clarification_question:
        payload["clarification_question"] = clarification_question
    if clarification_options:
        payload["clarification_options"] = list(clarification_options)
    if allowed_actions:
        payload["allowed_actions"] = list(allowed_actions)
    return payload


def issue_severity(issue: Dict[str, Any]) -> str:
    return str(issue.get("severity") or SEVERITY_REPAIR_REQUIRED)


def blocking_issues(issues: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [issue for issue in issues if issue_severity(issue) in BLOCKING_SEVERITIES]


def repair_required_issues(issues: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [issue for issue in issues if issue_severity(issue) in REPAIR_SEVERITIES]


def clarification_issue(issues: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for issue in issues:
        if issue_severity(issue) == SEVERITY_CLARIFICATION:
            return issue
    return None


def semantic_review_ok(issues: Iterable[Dict[str, Any]]) -> bool:
    return not blocking_issues(issues)


def semantic_review_error(prefix: str, issues: Iterable[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for issue in issues:
        message = str(issue.get("message") or "").strip()
        repair_hint = str(issue.get("repair_hint") or "").strip()
        if repair_hint and repair_hint not in message:
            message = f"{message} Repair hint: {repair_hint}" if message else repair_hint
        if message:
            parts.append(message)
    return prefix + "; ".join(parts)
