from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from wiicon5.workbench.models import HumanSkillDraft, jsonable


DRAFT_VOLATILE_KEYS = {"created_at", "created_by", "updated_at", "updated_by"}


def stable_hash(payload: Any) -> str:
    body = json.dumps(jsonable(payload), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def draft_hash(draft: HumanSkillDraft) -> str:
    payload = {
        key: value
        for key, value in draft.to_dict().items()
        if key not in DRAFT_VOLATILE_KEYS
    }
    return stable_hash(payload)


def query_hash(query: str) -> str:
    return stable_hash({"query": query.strip()})


def preview_hash(payload: Mapping[str, Any]) -> str:
    params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}
    return stable_hash(
        {
            "ok": bool(payload.get("ok")),
            "query": str(payload.get("query") or "").strip(),
            "param_names": sorted(str(key) for key in params.keys()),
            "limit": int(payload.get("limit") or 0),
        }
    )


def metadata_dependency_hash(payload: Mapping[str, Any]) -> str:
    review = payload.get("review") if isinstance(payload.get("review"), Mapping) else {}
    sources = review.get("sources") if isinstance(review.get("sources"), list) else []
    normalized = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        normalized.append(
            {
                "object_full_name": str(source.get("object_full_name") or ""),
                "source": str(source.get("source") or ""),
                "virtual_table": str(source.get("virtual_table") or ""),
                "table_part": str(source.get("table_part") or ""),
            }
        )
    return stable_hash({"sources": normalized})


def preview_fingerprint_payload(preview: Any) -> Dict[str, str]:
    payload = preview.to_dict() if hasattr(preview, "to_dict") else dict(preview or {})
    query = str(payload.get("query") or "")
    return {
        "preview_hash": preview_hash(payload),
        "query_hash": query_hash(query),
        "metadata_dependency_hash": metadata_dependency_hash(payload),
    }
