from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

from wiicon5.workbench.audit import WorkbenchAuditLog, utc_now
from wiicon5.workbench.models import HumanSkillDraft, jsonable


class HumanSkillDraftStore:
    def __init__(self, *, bot_instance_root: Path, bot_id: str = "local") -> None:
        self.bot_instance_root = bot_instance_root
        self.bot_id = bot_id
        self.root = bot_instance_root / "workbench"
        self.drafts_dir = self.root / "drafts"
        self.audit = WorkbenchAuditLog(self.root / "audit" / "events.jsonl", bot_id=bot_id)

    def new_draft(
        self,
        *,
        title: str,
        description: str = "",
        example_questions: Optional[List[str]] = None,
        actor: str = "system",
    ) -> HumanSkillDraft:
        return self.create_draft(
            HumanSkillDraft(
                title=title,
                description=description,
                example_questions=list(example_questions or []),
            ),
            actor=actor,
        )

    def create_draft(self, draft: HumanSkillDraft, *, actor: str = "system") -> HumanSkillDraft:
        now = utc_now()
        draft_id = draft.draft_id.strip()
        if not draft_id or self._draft_path(draft_id).exists():
            draft_id = self._new_draft_id(draft.title)
        created = replace(
            draft,
            draft_id=draft_id,
            created_at=draft.created_at or now,
            created_by=draft.created_by or actor,
            updated_at=now,
            updated_by=actor,
        )
        self._write_draft(created)
        self.audit.append(
            event_type="workbench.draft.created",
            actor=actor,
            object_type="human_skill_draft",
            object_id=created.draft_id,
            after=created.to_dict(),
            payload={"title": created.title, "status": created.status.value},
        )
        return created

    def get_draft(self, draft_id: str) -> Optional[HumanSkillDraft]:
        path = self._draft_path(draft_id)
        if not path.exists():
            return None
        return self._read_draft(path)

    def require_draft(self, draft_id: str) -> HumanSkillDraft:
        draft = self.get_draft(draft_id)
        if draft is None:
            raise KeyError(f"Human skill draft not found: {draft_id}")
        return draft

    def list_drafts(self) -> List[HumanSkillDraft]:
        if not self.drafts_dir.exists():
            return []
        drafts: List[HumanSkillDraft] = []
        for path in sorted(self.drafts_dir.glob("*.json")):
            draft = self._read_draft(path)
            if draft is not None:
                drafts.append(draft)
        return sorted(drafts, key=lambda item: (item.updated_at, item.draft_id), reverse=True)

    def update_draft(self, draft_id: str, changes: Mapping[str, Any], *, actor: str = "system") -> HumanSkillDraft:
        current = self.require_draft(draft_id)
        before = current.to_dict()
        payload = current.to_dict()
        payload.update(jsonable(dict(changes)))
        payload["draft_id"] = current.draft_id
        payload["created_at"] = current.created_at
        payload["created_by"] = current.created_by
        payload["updated_at"] = utc_now()
        payload["updated_by"] = actor
        updated = HumanSkillDraft.from_dict(payload)
        self._write_draft(updated)
        self.audit.append(
            event_type="workbench.draft.updated",
            actor=actor,
            object_type="human_skill_draft",
            object_id=updated.draft_id,
            before=before,
            after=updated.to_dict(),
            payload={"changed_fields": sorted(str(key) for key in changes.keys())},
        )
        return updated

    def replace_draft(self, draft: HumanSkillDraft, *, actor: str = "system") -> HumanSkillDraft:
        current = self.require_draft(draft.draft_id)
        return self.update_draft(draft.draft_id, draft.to_dict(), actor=actor)

    def delete_draft(self, draft_id: str, *, actor: str = "system") -> bool:
        draft = self.get_draft(draft_id)
        path = self._draft_path(draft_id)
        if draft is None or not path.exists():
            return False
        before = draft.to_dict()
        path.unlink()
        self.audit.append(
            event_type="workbench.draft.deleted",
            actor=actor,
            object_type="human_skill_draft",
            object_id=draft_id,
            before=before,
            payload={"title": draft.title},
        )
        return True

    def _draft_path(self, draft_id: str) -> Path:
        return self.drafts_dir / f"{safe_file_stem(draft_id)}.json"

    def _new_draft_id(self, title: str) -> str:
        stem = safe_file_stem(title)[:40].strip("_") or "draft"
        return f"{stem}_{uuid4().hex[:10]}"

    def _read_draft(self, path: Path) -> Optional[HumanSkillDraft]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(data, Mapping):
            return None
        draft = HumanSkillDraft.from_dict(data)
        if not draft.draft_id:
            return None
        return draft

    def _write_draft(self, draft: HumanSkillDraft) -> None:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(draft.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        atomic_write_text(self._draft_path(draft.draft_id), payload)


def safe_file_stem(value: str) -> str:
    stem = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "_", value.strip())
    stem = re.sub(r"_+", "_", stem).strip("._-")
    return stem or "draft"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
