from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from wiicon5.models import Port, SkillContract, SkillKind, SkillStatus, ValidationIssue
from wiicon5.workbench.approval import APPROVED, ApprovalRecord, ApprovalStore, skill_id_for_draft
from wiicon5.workbench.models import HumanSkillDraft
from wiicon5.workbench.preview import QueryPreviewResult, QueryPreviewService
from wiicon5.workbench.store import atomic_write_text


APPROVAL_GATE_CODES = {"missing_human_approval", "approval_rejected", "wrong_approval_level"}


@dataclass(frozen=True)
class PublishCandidateResult:
    ok: bool
    skill: Optional[SkillContract] = None
    path: str = ""
    evidence_path: str = ""
    issues: List[ValidationIssue] = field(default_factory=list)
    preview: Optional[QueryPreviewResult] = None
    approval: Optional[ApprovalRecord] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "skill": self.skill.to_dict() if self.skill else None,
            "path": self.path,
            "evidence_path": self.evidence_path,
            "issues": [item.to_dict() for item in self.issues],
            "preview": self.preview.to_dict() if self.preview else None,
            "approval": self.approval.to_dict() if self.approval else None,
        }


class CandidatePublisher:
    def __init__(
        self,
        *,
        bot_instance_root: Path,
        preview_service: Optional[QueryPreviewService] = None,
        approval_store: Optional[ApprovalStore] = None,
    ) -> None:
        self.bot_instance_root = bot_instance_root
        self.preview_service = preview_service or QueryPreviewService()
        self.approval_store = approval_store
        self.candidates_dir = bot_instance_root / "skills" / "candidates"
        self.evidence_dir = bot_instance_root / "skills" / "evidence"
        self.smoke_root = bot_instance_root / "workbench" / "smoke"

    def validate(self, draft: HumanSkillDraft) -> PublishCandidateResult:
        issues = basic_gate_issues(draft)
        preview = self.preview_service.preview(draft)
        approval = self._latest_approval(draft)
        if not preview.ok:
            issues.extend(preview.issues)
        if not latest_smoke_ok(self.smoke_root / draft.draft_id):
            issues.append(
                ValidationIssue(
                    "missing_successful_smoke",
                    "A successful MCP smoke test is required before publishing a candidate skill.",
                    "workbench.smoke",
                )
            )
        if approval is None:
            issues.append(
                ValidationIssue(
                    "missing_human_approval",
                    "Human approval is required before publishing a candidate skill.",
                    "workbench.approval",
                )
            )
        elif approval.decision != APPROVED:
            issues.append(
                ValidationIssue(
                    "approval_rejected",
                    "The latest human approval decision rejects this draft.",
                    "workbench.approval",
                )
            )
        elif approval.approval_level != "candidate":
            issues.append(
                ValidationIssue(
                    "wrong_approval_level",
                    "Candidate publication requires approval_level=candidate.",
                    "workbench.approval",
                )
            )
        if issues:
            return PublishCandidateResult(ok=False, issues=issues, preview=preview, approval=approval)
        return PublishCandidateResult(ok=True, preview=preview, approval=approval)

    def publish(self, draft: HumanSkillDraft) -> PublishCandidateResult:
        validation = self.validate(draft)
        if not validation.ok:
            return validation
        preview = validation.preview
        approval = validation.approval
        if preview is None:
            return PublishCandidateResult(
                ok=False,
                issues=[
                    ValidationIssue(
                        "missing_query_preview",
                        "Query preview is required before publishing a candidate skill.",
                        "workbench.preview",
                    )
                ],
                approval=approval,
            )
        skill = skill_from_draft(draft, preview)
        skill_path = self.candidates_dir / f"{skill.skill_id}.json"
        evidence_path = self.evidence_dir / skill.skill_id / "workbench_publication.json"
        atomic_write_text(skill_path, json.dumps(skill.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        atomic_write_text(
            evidence_path,
            json.dumps(
                {
                    "draft": draft.to_dict(),
                    "preview": preview.to_dict(),
                    "latest_smoke_ok": True,
                    "approval": approval.to_dict() if approval else None,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return PublishCandidateResult(
            ok=True,
            skill=skill,
            path=str(skill_path),
            evidence_path=str(evidence_path),
            preview=preview,
            approval=approval,
        )

    def _latest_approval(self, draft: HumanSkillDraft) -> Optional[ApprovalRecord]:
        if self.approval_store is None or not draft.draft_id:
            return None
        return self.approval_store.latest_for_draft(draft.draft_id)


def basic_gate_issues(draft: HumanSkillDraft) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not draft.title.strip():
        issues.append(ValidationIssue("missing_title", "Draft title is required.", "title"))
    if not draft.example_questions:
        issues.append(ValidationIssue("missing_example_question", "At least one example question is required.", "example_questions"))
    if not draft.draft_id:
        issues.append(ValidationIssue("missing_draft_id", "Draft must be saved before publishing.", "draft_id"))
    return issues


def skill_from_draft(draft: HumanSkillDraft, preview: QueryPreviewResult) -> SkillContract:
    output_columns = draft.presentation.columns or output_columns_from_query(preview.query)
    return SkillContract(
        skill_id=skill_id_for_draft(draft.draft_id),
        version="0.1.0",
        kind=SkillKind.DATA,
        status=SkillStatus.CANDIDATE,
        description=draft.description or draft.title,
        capabilities=unique([draft.title, *draft.example_questions, *draft.tags]),
        inputs=[],
        outputs=[Port(name="rows", type="TypedTable", description=", ".join(output_columns))],
        tags=unique(["workbench", *draft.tags]),
        implementation_strategy="workbench_preview_query",
        implementation={
            "query": preview.query,
            "params": preview.params,
            "limit": preview.limit,
            "draft_id": draft.draft_id,
            "source_trace": draft.source_trace,
        },
    )


def latest_smoke_ok(path: Path) -> bool:
    if not path.exists():
        return False
    files = sorted(path.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for file_path in files:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        return bool(result.get("ok"))
    return False


def output_columns_from_query(query: str) -> List[str]:
    columns: List[str] = []
    for line in query.splitlines():
        if " КАК " not in line:
            continue
        alias = line.rsplit(" КАК ", 1)[-1].strip().strip(",")
        if alias and alias not in columns:
            columns.append(alias)
    return columns


def unique(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
