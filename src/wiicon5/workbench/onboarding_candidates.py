from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from wiicon5.workbench.audit import utc_now
from wiicon5.workbench.models import CalculationRecipe, DataSourceRef, DraftEvidence, HumanSkillDraft, jsonable
from wiicon5.workbench.store import HumanSkillDraftStore, atomic_write_text


@dataclass(frozen=True)
class OnboardingCandidate:
    candidate_id: str
    type: str
    title: str
    semantic_role: str = ""
    object_name: str = ""
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)
    status: str = "candidate"
    source_file: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "type": self.type,
            "title": self.title,
            "semantic_role": self.semantic_role,
            "object": self.object_name,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "status": self.status,
            "source_file": self.source_file,
            "payload": jsonable(self.payload),
        }


class OnboardingCandidateService:
    def __init__(self, *, bot_instance_root: Path, draft_store: Optional[HumanSkillDraftStore] = None) -> None:
        self.bot_instance_root = bot_instance_root
        self.onboarding_dir = bot_instance_root / "onboarding"
        self.workbench_dir = bot_instance_root / "workbench"
        self.rejections_path = self.workbench_dir / "onboarding_candidate_rejections.json"
        self.draft_store = draft_store or HumanSkillDraftStore(
            bot_instance_root=bot_instance_root,
            bot_id=bot_instance_root.name or "local",
        )

    def list_candidates(
        self,
        *,
        limit: int = 200,
        type_filter: str = "",
        term: str = "",
    ) -> List[OnboardingCandidate]:
        rejected = self.rejected_ids()
        candidates = self._read_all_candidates()
        if type_filter:
            candidates = [item for item in candidates if item.type == type_filter]
        if term:
            lowered = term.lower()
            candidates = [
                item
                for item in candidates
                if lowered in item.title.lower()
                or lowered in item.object_name.lower()
                or lowered in item.semantic_role.lower()
                or lowered in " ".join(item.evidence).lower()
            ]
        result = [replace(item, status="rejected" if item.candidate_id in rejected else item.status) for item in candidates]
        return result[: max(0, limit)]

    def get_candidate(self, candidate_id: str) -> Optional[OnboardingCandidate]:
        for candidate in self.list_candidates(limit=10000):
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def reject_candidate(self, candidate_id: str, *, actor: str = "admin", comment: str = "") -> Dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        payload = self._read_rejections()
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        record = {
            "candidate_id": candidate_id,
            "actor": actor,
            "comment": comment,
            "ts": utc_now(),
            "candidate": candidate.to_dict(),
        }
        items.append(record)
        atomic_write_text(
            self.rejections_path,
            json.dumps({"items": items}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        self.draft_store.audit.append(
            event_type="workbench.onboarding_candidate.rejected",
            actor=actor,
            object_type="onboarding_candidate",
            object_id=candidate_id,
            after=record,
            payload={"candidate_type": candidate.type, "object": candidate.object_name},
        )
        return record

    def create_draft(self, candidate_id: str, *, actor: str = "admin") -> HumanSkillDraft:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        draft = draft_from_onboarding_candidate(candidate)
        created = self.draft_store.create_draft(draft, actor=actor)
        self.draft_store.audit.append(
            event_type="workbench.onboarding_candidate.draft_created",
            actor=actor,
            object_type="onboarding_candidate",
            object_id=candidate_id,
            payload={"draft_id": created.draft_id, "candidate_type": candidate.type, "object": candidate.object_name},
        )
        return created

    def rejected_ids(self) -> set[str]:
        return {
            str(item.get("candidate_id") or "")
            for item in self._read_rejections().get("items", [])
            if isinstance(item, Mapping)
        }

    def _read_all_candidates(self) -> List[OnboardingCandidate]:
        candidates: List[OnboardingCandidate] = []
        candidates.extend(self._binding_candidates())
        candidates.extend(self._register_usage_candidates())
        candidates.extend(self._query_pattern_candidates())
        candidates.extend(self._semantic_dictionary_candidates())
        return sorted(candidates, key=lambda item: (-item.confidence, item.type, item.title, item.candidate_id))

    def _binding_candidates(self) -> List[OnboardingCandidate]:
        payload = read_json(self.onboarding_dir / "candidate_bindings.json")
        verified_by_object = verified_candidate_status(self.onboarding_dir / "verified_binding_candidates.json")
        items = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        result: List[OnboardingCandidate] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            semantic_role = str(item.get("semantic_role") or "")
            object_name = str(item.get("object") or "")
            status = verified_by_object.get((semantic_role, object_name), str(item.get("status") or "candidate"))
            evidence = [str(value) for value in item.get("evidence", []) if value]
            if status == "verified_by_mcp":
                evidence.append("verified_by_mcp")
            result.append(
                OnboardingCandidate(
                    candidate_id=candidate_id("binding", semantic_role, object_name),
                    type="binding",
                    title=f"{semantic_role} -> {object_name}",
                    semantic_role=semantic_role,
                    object_name=object_name,
                    confidence=float_or_default(item.get("confidence"), 0.0),
                    evidence=evidence,
                    status=status,
                    payload=dict(item),
                )
            )
        return result

    def _register_usage_candidates(self) -> List[OnboardingCandidate]:
        payload = read_json(self.onboarding_dir / "register_usage_map.json")
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        result: List[OnboardingCandidate] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            document = str(item.get("document") or "")
            registers = [str(value) for value in item.get("registers", []) if value]
            source_file = str(item.get("source_file") or "")
            result.append(
                OnboardingCandidate(
                    candidate_id=candidate_id("register_usage", document, ",".join(registers), source_file),
                    type="register_usage",
                    title=f"{document} writes {len(registers)} register(s)",
                    object_name=document,
                    confidence=0.55 if registers else 0.25,
                    evidence=[f"register:{register}" for register in registers],
                    source_file=source_file,
                    payload=dict(item),
                )
            )
        return result

    def _query_pattern_candidates(self) -> List[OnboardingCandidate]:
        result: List[OnboardingCandidate] = []
        for item in read_jsonl(self.onboarding_dir / "candidate_query_patterns.jsonl"):
            pattern_id = str(item.get("pattern_id") or "")
            source_file = str(item.get("source_file") or "")
            query = str(item.get("query") or "")
            result.append(
                OnboardingCandidate(
                    candidate_id=candidate_id("query_pattern", pattern_id, source_file),
                    type="query_pattern",
                    title=f"Query pattern {pattern_id}",
                    confidence=0.4,
                    evidence=[f"source_file:{source_file}", f"query_length:{len(query)}"],
                    source_file=source_file,
                    payload=dict(item),
                )
            )
        return result

    def _semantic_dictionary_candidates(self) -> List[OnboardingCandidate]:
        payload = read_json(self.onboarding_dir / "candidate_semantic_roles.json")
        dictionary = payload.get("dictionary") if isinstance(payload.get("dictionary"), Mapping) else {}
        result: List[OnboardingCandidate] = []
        for token, objects in dictionary.items():
            object_list = [str(value) for value in objects if value] if isinstance(objects, list) else []
            if not object_list:
                continue
            result.append(
                OnboardingCandidate(
                    candidate_id=candidate_id("semantic_dictionary", str(token), ",".join(object_list[:20])),
                    type="semantic_dictionary",
                    title=f"Semantic token: {token}",
                    semantic_role=str(token),
                    confidence=0.25,
                    evidence=[f"objects:{len(object_list)}", *object_list[:5]],
                    payload={"token": str(token), "objects": object_list},
                )
            )
        return result

    def _read_rejections(self) -> Dict[str, Any]:
        payload = read_json(self.rejections_path)
        return payload if isinstance(payload, dict) else {}


def draft_from_onboarding_candidate(candidate: OnboardingCandidate) -> HumanSkillDraft:
    evidence = DraftEvidence(
        source=f"onboarding_{candidate.type}",
        reference=candidate.candidate_id,
        trust="hint",
        details={"confidence": candidate.confidence, "evidence": candidate.evidence},
    )
    data_sources: List[DataSourceRef] = []
    if candidate.object_name:
        data_sources.append(
            DataSourceRef(
                alias=alias_from_object(candidate.object_name),
                object_name=candidate.object_name,
                purpose=candidate.semantic_role,
                trust="hint",
                evidence=[evidence],
            )
        )
    if candidate.type == "register_usage":
        for register in candidate.payload.get("registers", []):
            data_sources.append(
                DataSourceRef(
                    alias=alias_from_object(str(register)),
                    object_name=str(register),
                    purpose="register_written_by_document",
                    trust="hint",
                    evidence=[evidence],
                )
            )
    calculation = CalculationRecipe(kind=f"onboarding_{candidate.type}", raw=candidate.payload)
    return HumanSkillDraft.from_dict(
        {
            "title": f"Проверить onboarding candidate: {candidate.title}",
            "description": "Черновик создан из результатов первоначального обучения. Его нужно проверить, дополнить и прогнать через validation/smoke/approval.",
            "example_questions": [],
            "business_entities": [candidate.semantic_role] if candidate.semantic_role else [],
            "data_sources": [item.to_dict() for item in data_sources],
            "calculation": calculation.to_dict(),
            "tags": ["workbench", "onboarding", candidate.type],
            "source_kind": "onboarding_candidate",
            "notes": "\n".join(candidate.evidence),
            "onboarding_candidate": candidate.to_dict(),
        }
    )


def verified_candidate_status(path: Path) -> Dict[tuple[str, str], str]:
    payload = read_json(path)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    result: Dict[tuple[str, str], str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        candidate = item.get("candidate") if isinstance(item.get("candidate"), Mapping) else {}
        key = (str(candidate.get("semantic_role") or ""), str(candidate.get("object") or ""))
        if key[0] or key[1]:
            result[key] = str(item.get("status") or "")
    return result


def candidate_id(*parts: str) -> str:
    digest = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"onb_{digest}"


def alias_from_object(object_name: str) -> str:
    return object_name.rsplit(".", 1)[-1] if object_name else "Источник"


def read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    result = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
