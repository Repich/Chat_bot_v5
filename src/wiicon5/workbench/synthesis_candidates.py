from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from wiicon5.execution.artifacts import Artifact
from wiicon5.intent.models import IntentResult
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query_synthesis import QuerySynthesisResult
from wiicon5.workbench.audit import WorkbenchAuditLog, utc_now
from wiicon5.workbench.models import CalculationRecipe, DataSourceRef, DraftEvidence, HumanSkillDraft, jsonable
from wiicon5.workbench.store import HumanSkillDraftStore, atomic_write_text, safe_file_stem


@dataclass(frozen=True)
class SynthesisCandidate:
    candidate_id: str
    question: str
    status: str
    trace_path: str
    query: str
    params: Dict[str, Any] = field(default_factory=dict)
    limit: Optional[int] = None
    answer: str = ""
    row_count: int = 0
    final_artifact_type: str = ""
    metadata_objects: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    seen_count: int = 1
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SynthesisCandidate":
        return cls(
            candidate_id=str(data.get("candidate_id") or ""),
            question=str(data.get("question") or ""),
            status=str(data.get("status") or "candidate"),
            trace_path=str(data.get("trace_path") or ""),
            query=str(data.get("query") or ""),
            params=dict(data.get("params", {})) if isinstance(data.get("params"), Mapping) else {},
            limit=int(data["limit"]) if data.get("limit") is not None else None,
            answer=str(data.get("answer") or ""),
            row_count=int(data.get("row_count") or 0),
            final_artifact_type=str(data.get("final_artifact_type") or ""),
            metadata_objects=[dict(item) for item in data.get("metadata_objects", []) if isinstance(item, Mapping)],
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            seen_count=int(data.get("seen_count") or 1),
            payload=dict(data.get("payload", {})) if isinstance(data.get("payload"), Mapping) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "question": self.question,
            "status": self.status,
            "trace_path": self.trace_path,
            "query": self.query,
            "params": jsonable(self.params),
            "limit": self.limit,
            "answer": self.answer,
            "row_count": self.row_count,
            "final_artifact_type": self.final_artifact_type,
            "metadata_objects": jsonable(self.metadata_objects),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "seen_count": self.seen_count,
            "payload": jsonable(self.payload),
        }


class SynthesisCandidateStore:
    def __init__(
        self,
        *,
        bot_instance_root: Path,
        draft_store: Optional[HumanSkillDraftStore] = None,
        audit_log: Optional[WorkbenchAuditLog] = None,
    ) -> None:
        self.bot_instance_root = bot_instance_root
        self.root = bot_instance_root / "workbench"
        self.candidates_dir = self.root / "candidates" / "synthesis"
        self.ignored_path = self.root / "candidates" / "synthesis_ignored.json"
        self.draft_store = draft_store or HumanSkillDraftStore(
            bot_instance_root=bot_instance_root,
            bot_id=bot_instance_root.name or "local",
        )
        self.audit = audit_log or self.draft_store.audit

    def record_from_synthesis(
        self,
        *,
        question: str,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        synthesis_result: QuerySynthesisResult,
        trace_path: str,
    ) -> Optional[SynthesisCandidate]:
        if not should_create_synthesis_candidate(question=question, intent=intent, synthesis_result=synthesis_result):
            return None
        if self._is_ignored(question):
            return None
        final_query = synthesis_result.trace.get("final_query")
        if not isinstance(final_query, Mapping):
            return None
        query = str(final_query.get("query") or "")
        candidate_id = synthesis_candidate_id(question, query)
        existing = self.get_candidate(candidate_id)
        now = utc_now()
        if existing is not None:
            candidate = replace(existing, updated_at=now, seen_count=existing.seen_count + 1, trace_path=trace_path)
        else:
            candidate = SynthesisCandidate(
                candidate_id=candidate_id,
                question=question,
                status="candidate",
                trace_path=trace_path,
                query=query,
                params=dict(final_query.get("params", {})) if isinstance(final_query.get("params"), Mapping) else {},
                limit=int(final_query["limit"]) if final_query.get("limit") is not None else None,
                answer=synthesis_result.message,
                row_count=int(synthesis_result.trace.get("row_count") or 0),
                final_artifact_type=synthesis_result.final_artifact.type if synthesis_result.final_artifact else "",
                metadata_objects=[dict(item) for item in synthesis_result.trace.get("metadata_objects", []) if isinstance(item, Mapping)],
                created_at=now,
                updated_at=now,
                payload={
                    "intent": intent.to_dict(),
                    "goal": goal.to_dict() if hasattr(goal, "to_dict") else goal_to_dict(goal),
                    "final_artifact": synthesis_result.final_artifact.to_dict() if synthesis_result.final_artifact else None,
                },
            )
        self._write_candidate(candidate)
        self.audit.append(
            event_type="workbench.synthesis_candidate.recorded",
            actor="agent",
            object_type="synthesis_candidate",
            object_id=candidate.candidate_id,
            after=candidate.to_dict(),
            payload={"question": question, "row_count": candidate.row_count, "seen_count": candidate.seen_count},
        )
        return candidate

    def list_candidates(self, *, limit: int = 200, status: str = "", term: str = "") -> List[SynthesisCandidate]:
        if not self.candidates_dir.exists():
            return []
        candidates: List[SynthesisCandidate] = []
        for path in sorted(self.candidates_dir.glob("*.json")):
            candidate = self._read_candidate(path)
            if candidate is not None:
                candidates.append(candidate)
        if status:
            candidates = [item for item in candidates if item.status == status]
        if term:
            lowered = term.lower()
            candidates = [
                item
                for item in candidates
                if lowered in item.question.lower()
                or lowered in item.answer.lower()
                or lowered in item.query.lower()
                or lowered in " ".join(str(obj.get("full_name") or "") for obj in item.metadata_objects).lower()
            ]
        candidates = sorted(candidates, key=lambda item: (item.updated_at, item.candidate_id), reverse=True)
        draft_links = self._draft_links_by_candidate()
        candidates = [self._with_existing_draft_link(item, draft_links.get(item.candidate_id)) for item in candidates]
        return candidates[: max(0, limit)]

    def get_candidate(self, candidate_id: str) -> Optional[SynthesisCandidate]:
        return self._read_candidate(self._path(candidate_id))

    def reject_candidate(self, candidate_id: str, *, actor: str = "admin", comment: str = "") -> SynthesisCandidate:
        candidate = self._require_candidate(candidate_id)
        updated = replace(
            candidate,
            status="rejected",
            updated_at=utc_now(),
            payload={**candidate.payload, "rejection": {"actor": actor, "comment": comment, "ts": utc_now()}},
        )
        self._write_candidate(updated)
        self.audit.append(
            event_type="workbench.synthesis_candidate.rejected",
            actor=actor,
            object_type="synthesis_candidate",
            object_id=candidate_id,
            payload={"comment": comment},
        )
        return updated

    def ignore_similar(self, candidate_id: str, *, actor: str = "admin", comment: str = "") -> SynthesisCandidate:
        candidate = self._require_candidate(candidate_id)
        ignored = self._read_ignored()
        record = {
            "normalized_question": normalize_question(candidate.question),
            "candidate_id": candidate.candidate_id,
            "actor": actor,
            "comment": comment,
            "ts": utc_now(),
        }
        ignored.append(record)
        atomic_write_text(
            self.ignored_path,
            json.dumps({"items": ignored}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        updated = replace(candidate, status="ignored_similar", updated_at=record["ts"])
        self._write_candidate(updated)
        self.audit.append(
            event_type="workbench.synthesis_candidate.ignored_similar",
            actor=actor,
            object_type="synthesis_candidate",
            object_id=candidate_id,
            payload={"comment": comment},
        )
        return updated

    def create_or_get_draft(self, candidate_id: str, *, actor: str = "admin") -> Tuple[HumanSkillDraft, bool]:
        candidate = self._require_candidate(candidate_id)
        existing = self._find_existing_draft(candidate)
        if existing is not None:
            self._link_candidate_to_draft(candidate, existing.draft_id, actor=actor)
            self.audit.append(
                event_type="workbench.synthesis_candidate.draft_reused",
                actor=actor,
                object_type="synthesis_candidate",
                object_id=candidate_id,
                payload={"draft_id": existing.draft_id},
            )
            return existing, True
        draft = draft_from_synthesis_candidate(candidate)
        created = self.draft_store.create_draft(draft, actor=actor)
        self._link_candidate_to_draft(candidate, created.draft_id, actor=actor)
        self.audit.append(
            event_type="workbench.synthesis_candidate.draft_created",
            actor=actor,
            object_type="synthesis_candidate",
            object_id=candidate_id,
            payload={"draft_id": created.draft_id},
        )
        return created, False

    def create_draft(self, candidate_id: str, *, actor: str = "admin") -> HumanSkillDraft:
        draft, _ = self.create_or_get_draft(candidate_id, actor=actor)
        return draft

    def _is_ignored(self, question: str) -> bool:
        normalized = normalize_question(question)
        return any(str(item.get("normalized_question") or "") == normalized for item in self._read_ignored())

    def _read_ignored(self) -> List[Dict[str, Any]]:
        payload = read_json(self.ignored_path)
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return [dict(item) for item in items if isinstance(item, Mapping)]

    def _require_candidate(self, candidate_id: str) -> SynthesisCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        return candidate

    def _read_candidate(self, path: Path) -> Optional[SynthesisCandidate]:
        payload = read_json(path)
        if not payload:
            return None
        candidate = SynthesisCandidate.from_dict(payload)
        return candidate if candidate.candidate_id else None

    def _write_candidate(self, candidate: SynthesisCandidate) -> None:
        atomic_write_text(
            self._path(candidate.candidate_id),
            json.dumps(candidate.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def _find_existing_draft(self, candidate: SynthesisCandidate) -> Optional[HumanSkillDraft]:
        linked_draft_id = candidate_payload_draft_id(candidate.payload)
        if linked_draft_id:
            linked = self.draft_store.get_draft(linked_draft_id)
            if linked is not None:
                return linked
        matches = [draft for draft in self.draft_store.list_drafts() if draft_matches_synthesis_candidate(draft, candidate.candidate_id)]
        if not matches:
            return None
        return sorted(matches, key=lambda item: (item.updated_at, item.created_at, item.draft_id), reverse=True)[0]

    def _link_candidate_to_draft(self, candidate: SynthesisCandidate, draft_id: str, *, actor: str) -> SynthesisCandidate:
        current_draft_id = candidate_payload_draft_id(candidate.payload)
        if current_draft_id == draft_id:
            return candidate
        updated = replace(
            candidate,
            updated_at=utc_now(),
            payload=payload_with_draft_link(candidate.payload, draft_id, actor=actor),
        )
        self._write_candidate(updated)
        return updated

    def _draft_links_by_candidate(self) -> Dict[str, HumanSkillDraft]:
        links: Dict[str, HumanSkillDraft] = {}
        for draft in self.draft_store.list_drafts():
            if draft.source_kind != "query_synthesis_candidate":
                continue
            candidate_id = draft_synthesis_candidate_id(draft)
            if not candidate_id:
                continue
            current = links.get(candidate_id)
            if current is None or (draft.updated_at, draft.created_at, draft.draft_id) > (
                current.updated_at,
                current.created_at,
                current.draft_id,
            ):
                links[candidate_id] = draft
        return links

    def _with_existing_draft_link(
        self,
        candidate: SynthesisCandidate,
        draft: Optional[HumanSkillDraft],
    ) -> SynthesisCandidate:
        if draft is None or candidate_payload_draft_id(candidate.payload):
            return candidate
        return replace(candidate, payload=payload_with_draft_link(candidate.payload, draft.draft_id, actor="workbench"))

    def _path(self, candidate_id: str) -> Path:
        return self.candidates_dir / f"{safe_file_stem(candidate_id)}.json"


def should_create_synthesis_candidate(
    *,
    question: str,
    intent: IntentResult,
    synthesis_result: QuerySynthesisResult,
) -> bool:
    if not synthesis_result.ok or synthesis_result.needs_clarification:
        return False
    final_query = synthesis_result.trace.get("final_query")
    if not isinstance(final_query, Mapping):
        return False
    query = str(final_query.get("query") or "")
    if not is_nontrivial_query(query):
        return False
    if not intent.requires_1c_data or not intent.relevant:
        return False
    if not artifact_has_rows(synthesis_result.final_artifact):
        return False
    if not question.strip():
        return False
    return True


def draft_from_synthesis_candidate(candidate: SynthesisCandidate) -> HumanSkillDraft:
    evidence = DraftEvidence(
        source="query_synthesis",
        reference=candidate.candidate_id,
        trust="hint",
        details={"trace_path": candidate.trace_path, "row_count": candidate.row_count},
    )
    data_sources = [
        DataSourceRef(
            alias=alias_from_object(str(item.get("full_name") or "")),
            object_name=str(item.get("full_name") or ""),
            trust="hint",
            evidence=[evidence],
        )
        for item in candidate.metadata_objects
        if item.get("full_name")
    ]
    return HumanSkillDraft.from_dict(
        {
            "title": f"Проверить query synthesis: {candidate.question}",
            "description": "Черновик создан из успешного query synthesis. Его нужно проверить, обобщить и прогнать через validation/smoke/approval.",
            "example_questions": [candidate.question],
            "data_sources": [item.to_dict() for item in data_sources],
            "calculation": CalculationRecipe(
                kind="trace_query",
                raw={"query": candidate.query, "params": candidate.params, "limit": candidate.limit},
            ).to_dict(),
            "presentation": {"columns": output_columns_from_artifact_type(candidate.final_artifact_type)},
            "tags": ["workbench", "query_synthesis"],
            "source_kind": "query_synthesis_candidate",
            "source_trace": candidate.trace_path,
            "notes": candidate.answer,
            "synthesis_candidate": candidate.to_dict(),
        }
    )


def candidate_payload_draft_id(payload: Mapping[str, Any]) -> str:
    draft_id = str(payload.get("draft_id") or "").strip()
    if draft_id:
        return draft_id
    draft = payload.get("draft")
    if isinstance(draft, Mapping):
        return str(draft.get("draft_id") or "").strip()
    return ""


def payload_with_draft_link(payload: Mapping[str, Any], draft_id: str, *, actor: str) -> Dict[str, Any]:
    now = utc_now()
    draft_payload = payload.get("draft")
    draft_link = dict(draft_payload) if isinstance(draft_payload, Mapping) else {}
    draft_link.update({"draft_id": draft_id, "linked_by": actor})
    draft_link.setdefault("linked_at", now)
    return {**payload, "draft_id": draft_id, "draft": draft_link}


def draft_matches_synthesis_candidate(draft: HumanSkillDraft, candidate_id: str) -> bool:
    return draft.source_kind == "query_synthesis_candidate" and draft_synthesis_candidate_id(draft) == candidate_id


def draft_synthesis_candidate_id(draft: HumanSkillDraft) -> str:
    candidate = draft.extras.get("synthesis_candidate")
    if isinstance(candidate, Mapping):
        return str(candidate.get("candidate_id") or "").strip()
    return ""


def synthesis_candidate_id(question: str, query: str) -> str:
    digest = hashlib.sha1(f"{normalize_question(question)}\n{normalize_query(query)}".encode("utf-8")).hexdigest()[:16]
    return f"syn_{digest}"


def normalize_question(value: str) -> str:
    return " ".join(value.lower().split())


def normalize_query(value: str) -> str:
    return " ".join(value.lower().split())


def is_nontrivial_query(query: str) -> bool:
    normalized = query.upper()
    return len(query.strip()) >= 40 and "ВЫБРАТЬ" in normalized and "ИЗ" in normalized


def artifact_has_rows(artifact: Optional[Artifact]) -> bool:
    if artifact is None:
        return False
    value = artifact.value
    if isinstance(value, Mapping):
        rows = value.get("rows")
        if isinstance(rows, list):
            return len(rows) > 0
    return bool(value)


def goal_to_dict(goal: Optional[GoalDecomposition]) -> Optional[Dict[str, Any]]:
    if goal is None:
        return None
    return {
        "business_goal": goal.business_goal,
        "final_artifact_type": goal.final_artifact_type,
        "expected_answer_type": goal.expected_answer_type,
        "required_artifacts": [item.to_dict() for item in goal.required_artifacts],
    }


def alias_from_object(object_name: str) -> str:
    return object_name.rsplit(".", 1)[-1] if object_name else "Источник"


def output_columns_from_artifact_type(artifact_type: str) -> List[str]:
    return ["rows"] if artifact_type else []


def read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
