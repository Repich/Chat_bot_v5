from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from wiicon5.workbench.audit import WorkbenchAuditLog, utc_now
from wiicon5.workbench.models import jsonable
from wiicon5.workbench.store import atomic_write_text, safe_file_stem


APPROVED = "approved"
REJECTED = "rejected"


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    draft_id: str
    skill_id: str
    decision: str
    approval_level: str = "candidate"
    actor: str = "admin"
    ts: str = ""
    comment: str = ""
    smoke_id: str = ""
    draft_hash: str = ""
    preview_hash: str = ""
    query_hash: str = ""
    regression_case_id: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        draft_id: str,
        decision: str,
        actor: str,
        approval_level: str = "candidate",
        comment: str = "",
        smoke_id: str = "",
        draft_hash: str = "",
        preview_hash: str = "",
        query_hash: str = "",
        regression_case_id: str = "",
        evidence: Optional[Mapping[str, Any]] = None,
    ) -> "ApprovalRecord":
        return cls(
            approval_id=uuid4().hex,
            draft_id=draft_id,
            skill_id=skill_id_for_draft(draft_id),
            decision=decision,
            approval_level=approval_level,
            actor=actor,
            ts=utc_now(),
            comment=comment,
            smoke_id=smoke_id,
            draft_hash=draft_hash,
            preview_hash=preview_hash,
            query_hash=query_hash,
            regression_case_id=regression_case_id,
            evidence=dict(evidence or {}),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApprovalRecord":
        return cls(
            approval_id=str(data.get("approval_id") or ""),
            draft_id=str(data.get("draft_id") or ""),
            skill_id=str(data.get("skill_id") or skill_id_for_draft(str(data.get("draft_id") or ""))),
            decision=str(data.get("decision") or ""),
            approval_level=str(data.get("approval_level") or "candidate"),
            actor=str(data.get("actor") or "admin"),
            ts=str(data.get("ts") or ""),
            comment=str(data.get("comment") or ""),
            smoke_id=str(data.get("smoke_id") or ""),
            draft_hash=str(data.get("draft_hash") or ""),
            preview_hash=str(data.get("preview_hash") or ""),
            query_hash=str(data.get("query_hash") or ""),
            regression_case_id=str(data.get("regression_case_id") or ""),
            evidence=dict(data.get("evidence", {})) if isinstance(data.get("evidence"), Mapping) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "draft_id": self.draft_id,
            "skill_id": self.skill_id,
            "decision": self.decision,
            "approval_level": self.approval_level,
            "actor": self.actor,
            "ts": self.ts,
            "comment": self.comment,
            "smoke_id": self.smoke_id,
            "draft_hash": self.draft_hash,
            "preview_hash": self.preview_hash,
            "query_hash": self.query_hash,
            "regression_case_id": self.regression_case_id,
            "evidence": jsonable(self.evidence),
        }


class ApprovalStore:
    def __init__(
        self,
        *,
        bot_instance_root: Path,
        bot_id: str = "local",
        audit_log: Optional[WorkbenchAuditLog] = None,
    ) -> None:
        self.bot_instance_root = bot_instance_root
        self.bot_id = bot_id
        self.root = bot_instance_root / "workbench"
        self.approvals_dir = self.root / "approvals"
        self.audit = audit_log

    def approve(
        self,
        draft_id: str,
        *,
        actor: str,
        approval_level: str = "candidate",
        comment: str = "",
        smoke_id: str = "",
        draft_hash: str = "",
        preview_hash: str = "",
        query_hash: str = "",
        regression_case_id: str = "",
        evidence: Optional[Mapping[str, Any]] = None,
    ) -> ApprovalRecord:
        return self.record_decision(
            draft_id,
            decision=APPROVED,
            actor=actor,
            approval_level=approval_level,
            comment=comment,
            smoke_id=smoke_id,
            draft_hash=draft_hash,
            preview_hash=preview_hash,
            query_hash=query_hash,
            regression_case_id=regression_case_id,
            evidence=evidence,
        )

    def reject(
        self,
        draft_id: str,
        *,
        actor: str,
        approval_level: str = "candidate",
        comment: str = "",
        evidence: Optional[Mapping[str, Any]] = None,
    ) -> ApprovalRecord:
        return self.record_decision(
            draft_id,
            decision=REJECTED,
            actor=actor,
            approval_level=approval_level,
            comment=comment,
            evidence=evidence,
        )

    def record_decision(
        self,
        draft_id: str,
        *,
        decision: str,
        actor: str,
        approval_level: str = "candidate",
        comment: str = "",
        smoke_id: str = "",
        draft_hash: str = "",
        preview_hash: str = "",
        query_hash: str = "",
        regression_case_id: str = "",
        evidence: Optional[Mapping[str, Any]] = None,
    ) -> ApprovalRecord:
        normalized_draft_id = draft_id.strip()
        if not normalized_draft_id:
            raise ValueError("draft_id is required for approval.")
        normalized_actor = actor.strip()
        if not normalized_actor:
            raise ValueError("actor is required for approval.")
        if decision not in {APPROVED, REJECTED}:
            raise ValueError(f"Unsupported approval decision: {decision}")
        record = ApprovalRecord.create(
            draft_id=normalized_draft_id,
            decision=decision,
            actor=normalized_actor,
            approval_level=approval_level.strip() or "candidate",
            comment=comment,
            smoke_id=smoke_id,
            draft_hash=draft_hash,
            preview_hash=preview_hash,
            query_hash=query_hash,
            regression_case_id=regression_case_id,
            evidence=evidence,
        )
        records = self.history_for_draft(normalized_draft_id)
        records.append(record)
        self._write_records(normalized_draft_id, records)
        if self.audit is not None:
            self.audit.append(
                event_type="workbench.approval.recorded",
                actor=normalized_actor,
                object_type="human_skill_draft",
                object_id=normalized_draft_id,
                after=record.to_dict(),
                payload={
                    "skill_id": record.skill_id,
                    "decision": record.decision,
                    "approval_level": record.approval_level,
                    "smoke_id": record.smoke_id,
                    "draft_hash": record.draft_hash,
                    "preview_hash": record.preview_hash,
                },
            )
        return record

    def history_for_draft(self, draft_id: str) -> List[ApprovalRecord]:
        path = self._path_for_draft(draft_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return []
        items = payload.get("records") if isinstance(payload, Mapping) else None
        if not isinstance(items, list):
            return []
        return [ApprovalRecord.from_dict(item) for item in items if isinstance(item, Mapping)]

    def latest_for_draft(self, draft_id: str) -> Optional[ApprovalRecord]:
        history = self.history_for_draft(draft_id)
        return history[-1] if history else None

    def latest_candidate_approval(self, draft_id: str) -> Optional[ApprovalRecord]:
        latest = self.latest_for_draft(draft_id)
        if latest is None:
            return None
        if latest.decision != APPROVED or latest.approval_level != "candidate":
            return None
        return latest

    def _write_records(self, draft_id: str, records: List[ApprovalRecord]) -> None:
        payload = {
            "draft_id": draft_id,
            "skill_id": skill_id_for_draft(draft_id),
            "records": [item.to_dict() for item in records],
        }
        atomic_write_text(
            self._path_for_draft(draft_id),
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def _path_for_draft(self, draft_id: str) -> Path:
        return self.approvals_dir / f"{safe_file_stem(skill_id_for_draft(draft_id))}.json"


def skill_id_for_draft(draft_id: str) -> str:
    return f"workbench_{draft_id.strip()}"
