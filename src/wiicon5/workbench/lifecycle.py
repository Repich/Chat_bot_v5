from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from wiicon5.models import SkillContract, SkillStatus, ValidationIssue
from wiicon5.skills.registry import is_skill_contract_payload
from wiicon5.workbench.audit import WorkbenchAuditLog, utc_now
from wiicon5.workbench.models import jsonable
from wiicon5.workbench.store import atomic_write_text, safe_file_stem


TERMINAL_REVIEW_STATUSES = {SkillStatus.DEPRECATED, SkillStatus.BLOCKED}


@dataclass(frozen=True)
class SkillLifecycleEvent:
    event_type: str
    skill_id: str
    actor: str
    from_status: str
    to_status: str
    ts: str
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "skill_id": self.skill_id,
            "actor": self.actor,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "ts": self.ts,
            "reason": self.reason,
            "payload": jsonable(self.payload),
        }


@dataclass(frozen=True)
class SkillLifecycleResult:
    ok: bool
    skill: Optional[SkillContract] = None
    before_status: str = ""
    after_status: str = ""
    path: str = ""
    previous_path: str = ""
    event: Optional[SkillLifecycleEvent] = None
    issues: List[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "skill": self.skill.to_dict() if self.skill else None,
            "before_status": self.before_status,
            "after_status": self.after_status,
            "path": self.path,
            "previous_path": self.previous_path,
            "event": self.event.to_dict() if self.event else None,
            "issues": [item.to_dict() for item in self.issues],
        }


class SkillLifecycleService:
    def __init__(
        self,
        *,
        bot_instance_root: Path,
        audit_log: Optional[WorkbenchAuditLog] = None,
        stable_successful_runs_min: int = 3,
    ) -> None:
        self.bot_instance_root = bot_instance_root
        self.skills_root = bot_instance_root / "skills"
        self.evidence_root = self.skills_root / "evidence"
        self.audit = audit_log or WorkbenchAuditLog(
            bot_instance_root / "workbench" / "audit" / "events.jsonl",
            bot_id=bot_instance_root.name or "local",
        )
        self.stable_successful_runs_min = stable_successful_runs_min

    def promote(
        self,
        skill_id: str,
        *,
        actor: str,
        target_status: str = "",
        reason: str = "",
        regression_case_ids: Optional[Iterable[str]] = None,
        successful_runs: int = 0,
        admin_approval: bool = False,
    ) -> SkillLifecycleResult:
        loaded = self._load_bot_skill(skill_id)
        if loaded is None:
            return self._failure("skill_not_found", f"Bot-specific skill not found: {skill_id}", "skill_id")
        skill, path = loaded
        target = resolve_promotion_target(skill.status, target_status)
        issues = required_actor_issue(actor) + required_reason_issue(reason)
        if target is None:
            issues.append(
                ValidationIssue(
                    "unsupported_transition",
                    f"Cannot promote skill from {skill.status.value}.",
                    "status",
                )
            )
        elif not allowed_transition(skill.status, target):
            issues.append(
                ValidationIssue(
                    "unsupported_transition",
                    f"Transition {skill.status.value} -> {target.value} is not allowed.",
                    "status",
                )
            )
        elif target == SkillStatus.VERIFIED:
            issues.extend(
                self._candidate_to_verified_issues(
                    skill,
                    regression_case_ids=list(regression_case_ids or []),
                )
            )
        elif target == SkillStatus.STABLE:
            issues.extend(
                stable_gate_issues(
                    successful_runs=successful_runs,
                    admin_approval=admin_approval,
                    required_runs=self.stable_successful_runs_min,
                )
            )
        if issues:
            return SkillLifecycleResult(
                ok=False,
                skill=skill,
                before_status=skill.status.value,
                after_status=target.value if target else "",
                path=str(path),
                issues=issues,
            )
        assert target is not None
        return self._write_transition(
            skill,
            path,
            target,
            actor=actor,
            reason=reason,
            event_type="workbench.skill.promoted",
            payload={
                "regression_case_ids": list(regression_case_ids or []),
                "successful_runs": successful_runs,
                "admin_approval": admin_approval,
            },
        )

    def deprecate(self, skill_id: str, *, actor: str, reason: str = "") -> SkillLifecycleResult:
        return self._review_transition(
            skill_id,
            actor=actor,
            reason=reason,
            target=SkillStatus.DEPRECATED,
            event_type="workbench.skill.deprecated",
        )

    def block(self, skill_id: str, *, actor: str, reason: str = "") -> SkillLifecycleResult:
        return self._review_transition(
            skill_id,
            actor=actor,
            reason=reason,
            target=SkillStatus.BLOCKED,
            event_type="workbench.skill.blocked",
        )

    def rollback(
        self,
        skill_id: str,
        *,
        actor: str,
        reason: str = "",
        target_status: str = "",
        admin_approval: bool = False,
    ) -> SkillLifecycleResult:
        loaded = self._load_bot_skill(skill_id)
        if loaded is None:
            return self._failure("skill_not_found", f"Bot-specific skill not found: {skill_id}", "skill_id")
        skill, path = loaded
        target = parse_status(target_status) if target_status else self._previous_runtime_status(skill.skill_id)
        issues = required_actor_issue(actor) + required_reason_issue(reason)
        if skill.status not in TERMINAL_REVIEW_STATUSES:
            issues.append(
                ValidationIssue(
                    "unsupported_transition",
                    f"Rollback is only allowed from deprecated or blocked, got {skill.status.value}.",
                    "status",
                )
            )
        if target not in {SkillStatus.CANDIDATE, SkillStatus.VERIFIED, SkillStatus.STABLE}:
            issues.append(
                ValidationIssue(
                    "invalid_target_status",
                    "Rollback target must be candidate, verified, or stable.",
                    "target_status",
                )
            )
        if not admin_approval:
            issues.append(
                ValidationIssue(
                    "missing_admin_approval",
                    "Rollback requires explicit admin_approval=true.",
                    "admin_approval",
                )
            )
        if issues:
            return SkillLifecycleResult(
                ok=False,
                skill=skill,
                before_status=skill.status.value,
                after_status=target.value if isinstance(target, SkillStatus) else "",
                path=str(path),
                issues=issues,
            )
        assert isinstance(target, SkillStatus)
        return self._write_transition(
            skill,
            path,
            target,
            actor=actor,
            reason=reason,
            event_type="workbench.skill.rollback",
            payload={"admin_approval": admin_approval},
        )

    def _review_transition(
        self,
        skill_id: str,
        *,
        actor: str,
        reason: str,
        target: SkillStatus,
        event_type: str,
    ) -> SkillLifecycleResult:
        loaded = self._load_bot_skill(skill_id)
        if loaded is None:
            return self._failure("skill_not_found", f"Bot-specific skill not found: {skill_id}", "skill_id")
        skill, path = loaded
        issues = required_actor_issue(actor) + required_reason_issue(reason)
        if skill.status in {SkillStatus.DRAFT, target}:
            issues.append(
                ValidationIssue(
                    "unsupported_transition",
                    f"Transition {skill.status.value} -> {target.value} is not allowed.",
                    "status",
                )
            )
        if issues:
            return SkillLifecycleResult(
                ok=False,
                skill=skill,
                before_status=skill.status.value,
                after_status=target.value,
                path=str(path),
                issues=issues,
            )
        return self._write_transition(skill, path, target, actor=actor, reason=reason, event_type=event_type)

    def _candidate_to_verified_issues(
        self,
        skill: SkillContract,
        *,
        regression_case_ids: List[str],
    ) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        evidence = self._publication_evidence(skill.skill_id)
        approval = evidence.get("approval") if isinstance(evidence.get("approval"), Mapping) else {}
        if approval.get("decision") != "approved":
            issues.append(
                ValidationIssue(
                    "missing_human_approval",
                    "Candidate -> verified requires an approved publication record.",
                    "evidence.approval",
                )
            )
        regression_ids = [
            item
            for item in [
                *regression_case_ids,
                str(approval.get("regression_case_id") or ""),
                *list_value(evidence.get("regression_case_ids")),
            ]
            if str(item).strip()
        ]
        if not regression_ids:
            issues.append(
                ValidationIssue(
                    "missing_regression_case",
                    "Candidate -> verified requires at least one regression case id.",
                    "regression_case_ids",
                )
            )
        return issues

    def _write_transition(
        self,
        skill: SkillContract,
        current_path: Path,
        target: SkillStatus,
        *,
        actor: str,
        reason: str,
        event_type: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> SkillLifecycleResult:
        before = skill.to_dict()
        event = SkillLifecycleEvent(
            event_type=event_type,
            skill_id=skill.skill_id,
            actor=actor.strip(),
            from_status=skill.status.value,
            to_status=target.value,
            ts=utc_now(),
            reason=reason,
            payload=dict(payload or {}),
        )
        implementation = dict(skill.implementation)
        lifecycle_events = list_value(implementation.get("lifecycle_events"))
        lifecycle_events.append(event.to_dict())
        implementation["lifecycle_events"] = lifecycle_events[-20:]
        updated = replace(
            skill,
            status=target,
            version=bump_patch_version(skill.version),
            implementation=implementation,
        )
        new_path = self._path_for_status(updated.skill_id, target)
        atomic_write_text(
            new_path,
            json.dumps(updated.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        if current_path != new_path:
            try:
                current_path.unlink()
            except FileNotFoundError:
                pass
        self._append_lifecycle_evidence(event, previous_path=current_path, path=new_path)
        self.audit.append(
            event_type=event_type,
            actor=actor.strip(),
            object_type="skill",
            object_id=skill.skill_id,
            before=before,
            after=updated.to_dict(),
            payload={
                "from": skill.status.value,
                "to": target.value,
                "reason": reason,
                "path": str(new_path),
                "previous_path": str(current_path),
            },
        )
        return SkillLifecycleResult(
            ok=True,
            skill=updated,
            before_status=skill.status.value,
            after_status=target.value,
            path=str(new_path),
            previous_path=str(current_path),
            event=event,
        )

    def _append_lifecycle_evidence(self, event: SkillLifecycleEvent, *, previous_path: Path, path: Path) -> None:
        evidence_path = self.evidence_root / event.skill_id / "lifecycle.jsonl"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **event.to_dict(),
            "path": str(path),
            "previous_path": str(previous_path),
        }
        with evidence_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _publication_evidence(self, skill_id: str) -> Dict[str, Any]:
        path = self.evidence_root / skill_id / "workbench_publication.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _previous_runtime_status(self, skill_id: str) -> Optional[SkillStatus]:
        path = self.evidence_root / skill_id / "lifecycle.jsonl"
        if not path.exists():
            return None
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            from_status = parse_status(str(payload.get("from_status") or ""))
            to_status = parse_status(str(payload.get("to_status") or ""))
            if to_status in TERMINAL_REVIEW_STATUSES and from_status in {
                SkillStatus.CANDIDATE,
                SkillStatus.VERIFIED,
                SkillStatus.STABLE,
            }:
                return from_status
        return None

    def _load_bot_skill(self, skill_id: str) -> Optional[tuple[SkillContract, Path]]:
        normalized = safe_file_stem(skill_id)
        matches: List[tuple[SkillContract, Path]] = []
        if not self.skills_root.exists():
            return None
        for path in sorted(self.skills_root.rglob("*.json")):
            if "evidence" in path.parts:
                continue
            if path.stem != normalized and path.stem != skill_id:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not is_skill_contract_payload(payload):
                continue
            try:
                skill = SkillContract.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                continue
            if skill.skill_id == skill_id:
                matches.append((skill, path))
        if not matches:
            return None
        return sorted(matches, key=lambda item: (status_sort_rank(item[0].status), str(item[1])), reverse=True)[0]

    def _path_for_status(self, skill_id: str, status: SkillStatus) -> Path:
        directory = {
            SkillStatus.CANDIDATE: "candidates",
            SkillStatus.VERIFIED: "verified",
            SkillStatus.STABLE: "stable",
            SkillStatus.DEPRECATED: "deprecated",
            SkillStatus.BLOCKED: "blocked",
            SkillStatus.DRAFT: "drafts",
        }[status]
        return self.skills_root / directory / f"{safe_file_stem(skill_id)}.json"

    def _failure(self, code: str, message: str, path: str) -> SkillLifecycleResult:
        return SkillLifecycleResult(ok=False, issues=[ValidationIssue(code, message, path)])


def resolve_promotion_target(current: SkillStatus, requested: str) -> Optional[SkillStatus]:
    if requested:
        return parse_status(requested)
    if current == SkillStatus.CANDIDATE:
        return SkillStatus.VERIFIED
    if current == SkillStatus.VERIFIED:
        return SkillStatus.STABLE
    return None


def allowed_transition(current: SkillStatus, target: SkillStatus) -> bool:
    return (current, target) in {
        (SkillStatus.CANDIDATE, SkillStatus.VERIFIED),
        (SkillStatus.VERIFIED, SkillStatus.STABLE),
    }


def stable_gate_issues(*, successful_runs: int, admin_approval: bool, required_runs: int) -> List[ValidationIssue]:
    if admin_approval or successful_runs >= required_runs:
        return []
    return [
        ValidationIssue(
            "missing_stable_evidence",
            f"Verified -> stable requires admin_approval=true or at least {required_runs} successful runs.",
            "stable_evidence",
        )
    ]


def required_actor_issue(actor: str) -> List[ValidationIssue]:
    if actor.strip():
        return []
    return [ValidationIssue("missing_actor", "Actor is required for skill lifecycle changes.", "actor")]


def required_reason_issue(reason: str) -> List[ValidationIssue]:
    if reason.strip():
        return []
    return [ValidationIssue("missing_reason", "Reason is required for skill lifecycle changes.", "reason")]


def parse_status(value: str) -> Optional[SkillStatus]:
    try:
        return SkillStatus(value)
    except ValueError:
        return None


def status_sort_rank(status: SkillStatus) -> int:
    return {
        SkillStatus.STABLE: 6,
        SkillStatus.VERIFIED: 5,
        SkillStatus.CANDIDATE: 4,
        SkillStatus.DEPRECATED: 3,
        SkillStatus.BLOCKED: 2,
        SkillStatus.DRAFT: 1,
    }[status]


def bump_patch_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{version}.1" if version else "0.1.1"


def list_value(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []
