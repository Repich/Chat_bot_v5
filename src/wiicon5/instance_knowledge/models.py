from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgePage:
    page_id: str
    title: str
    content: str
    source_url: str
    parent_id: str = ""
    ancestor_ids: List[str] = field(default_factory=list)
    ancestor_titles: List[str] = field(default_factory=list)
    source_kind: str = "confluence"
    space_key: str = ""
    version: int = 0
    created_at: str = ""
    updated_at: str = ""
    retrieved_at: str = ""
    labels: List[str] = field(default_factory=list)
    content_hash: str = ""

    def normalized(self) -> "KnowledgePage":
        content = self.content.strip()
        return KnowledgePage(
            page_id=self.page_id.strip(),
            title=self.title.strip() or self.page_id.strip(),
            content=content,
            source_url=self.source_url.strip(),
            parent_id=self.parent_id.strip(),
            ancestor_ids=[str(item).strip() for item in self.ancestor_ids if str(item).strip()],
            ancestor_titles=[str(item).strip() for item in self.ancestor_titles if str(item).strip()],
            source_kind=self.source_kind.strip() or "unknown",
            space_key=self.space_key.strip(),
            version=max(0, int(self.version or 0)),
            created_at=self.created_at.strip(),
            updated_at=self.updated_at.strip(),
            retrieved_at=self.retrieved_at.strip() or utc_now_iso(),
            labels=sorted({str(item).strip() for item in self.labels if str(item).strip()}),
            content_hash=self.content_hash.strip() or content_digest(content),
        )

    def to_dict(self) -> Dict[str, Any]:
        page = self.normalized()
        return {
            "page_id": page.page_id,
            "title": page.title,
            "content": page.content,
            "source_url": page.source_url,
            "parent_id": page.parent_id,
            "ancestor_ids": list(page.ancestor_ids),
            "ancestor_titles": list(page.ancestor_titles),
            "source_kind": page.source_kind,
            "space_key": page.space_key,
            "version": page.version,
            "created_at": page.created_at,
            "updated_at": page.updated_at,
            "retrieved_at": page.retrieved_at,
            "labels": list(page.labels),
            "content_hash": page.content_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "KnowledgePage":
        return cls(
            page_id=str(payload.get("page_id") or payload.get("id") or ""),
            title=str(payload.get("title") or ""),
            content=str(payload.get("content") or ""),
            source_url=str(payload.get("source_url") or payload.get("url") or ""),
            parent_id=str(payload.get("parent_id") or ""),
            ancestor_ids=[str(item) for item in payload.get("ancestor_ids", []) or []],
            ancestor_titles=[str(item) for item in payload.get("ancestor_titles", []) or []],
            source_kind=str(payload.get("source_kind") or "confluence"),
            space_key=str(payload.get("space_key") or ""),
            version=int(payload.get("version") or 0),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            retrieved_at=str(payload.get("retrieved_at") or ""),
            labels=[str(item) for item in payload.get("labels", []) or []],
            content_hash=str(payload.get("content_hash") or ""),
        ).normalized()


@dataclass(frozen=True)
class KnowledgeSnapshotManifest:
    snapshot_id: str
    source_kind: str
    source_root: str
    root_page_id: str
    created_at: str
    page_count: int
    chunk_count: int
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    previous_snapshot_id: str = ""
    content_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "source_kind": self.source_kind,
            "source_root": self.source_root,
            "root_page_id": self.root_page_id,
            "created_at": self.created_at,
            "page_count": self.page_count,
            "chunk_count": self.chunk_count,
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "previous_snapshot_id": self.previous_snapshot_id,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "KnowledgeSnapshotManifest":
        return cls(
            snapshot_id=str(payload.get("snapshot_id") or ""),
            source_kind=str(payload.get("source_kind") or ""),
            source_root=str(payload.get("source_root") or ""),
            root_page_id=str(payload.get("root_page_id") or ""),
            created_at=str(payload.get("created_at") or ""),
            page_count=int(payload.get("page_count") or 0),
            chunk_count=int(payload.get("chunk_count") or 0),
            added=int(payload.get("added") or 0),
            updated=int(payload.get("updated") or 0),
            unchanged=int(payload.get("unchanged") or 0),
            removed=int(payload.get("removed") or 0),
            previous_snapshot_id=str(payload.get("previous_snapshot_id") or ""),
            content_hash=str(payload.get("content_hash") or ""),
        )


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    page_id: str
    title: str
    heading: str
    content: str
    source_url: str
    ancestor_titles: List[str]
    updated_at: str
    version: int
    content_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "page_id": self.page_id,
            "title": self.title,
            "heading": self.heading,
            "content": self.content,
            "source_url": self.source_url,
            "ancestor_titles": list(self.ancestor_titles),
            "updated_at": self.updated_at,
            "version": self.version,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "KnowledgeChunk":
        return cls(
            chunk_id=str(payload.get("chunk_id") or ""),
            page_id=str(payload.get("page_id") or ""),
            title=str(payload.get("title") or ""),
            heading=str(payload.get("heading") or ""),
            content=str(payload.get("content") or ""),
            source_url=str(payload.get("source_url") or ""),
            ancestor_titles=[str(item) for item in payload.get("ancestor_titles", []) or []],
            updated_at=str(payload.get("updated_at") or ""),
            version=int(payload.get("version") or 0),
            content_hash=str(payload.get("content_hash") or ""),
        )
