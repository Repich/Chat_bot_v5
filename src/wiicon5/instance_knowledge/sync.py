from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from wiicon5.instance_knowledge.importers import ConfluenceClient, DirectoryKnowledgeImporter, JsonKnowledgeImporter
from wiicon5.instance_knowledge.index import build_chunks
from wiicon5.instance_knowledge.models import KnowledgePage, KnowledgeSnapshotManifest, utc_now_iso
from wiicon5.instance_knowledge.storage import KnowledgeRepository


@dataclass(frozen=True)
class KnowledgeSyncResult:
    ok: bool
    manifest: Optional[KnowledgeSnapshotManifest] = None
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "manifest": self.manifest.to_dict() if self.manifest is not None else None,
            "error": self.error,
        }


class KnowledgeSyncService:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        source_kind: str,
        base_url: str,
        root_page_id: str,
        timeout_seconds: float = 30.0,
        max_pages: int = 5000,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.repository = repository
        self.source_kind = source_kind.strip().lower() or "confluence"
        self.base_url = base_url.rstrip("/")
        self.root_page_id = root_page_id.strip()
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.env = dict(os.environ if env is None else env)

    def sync(self, *, input_json: Optional[Path] = None, input_dir: Optional[Path] = None) -> KnowledgeSyncResult:
        try:
            if input_json is not None:
                pages = JsonKnowledgeImporter().load(input_json, base_url=self.base_url)
                source_kind = "json_export"
                source_root = str(input_json)
            elif input_dir is not None:
                pages = DirectoryKnowledgeImporter().load(input_dir, base_url=self.base_url)
                source_kind = "directory_export"
                source_root = str(input_dir)
            else:
                pages = self._fetch_confluence()
                source_kind = self.source_kind
                source_root = self.base_url
            manifest = self._save(pages, source_kind=source_kind, source_root=source_root)
            return KnowledgeSyncResult(ok=True, manifest=manifest)
        except Exception as exc:
            return KnowledgeSyncResult(ok=False, error=str(exc))

    def activate(self, snapshot_id: str) -> KnowledgeSnapshotManifest:
        return self.repository.activate(snapshot_id)

    def _fetch_confluence(self) -> List[KnowledgePage]:
        if self.source_kind != "confluence":
            raise ValueError(f"Unsupported configured knowledge source: {self.source_kind}")
        if not self.base_url or not self.root_page_id:
            raise ValueError("Knowledge source requires base_url and root_page_id.")
        client = ConfluenceClient(
            base_url=self.base_url,
            headers=knowledge_auth_headers(self.env),
            timeout_seconds=self.timeout_seconds,
        )
        return client.fetch_tree(self.root_page_id, max_pages=self.max_pages)

    def _save(self, pages: List[KnowledgePage], *, source_kind: str, source_root: str) -> KnowledgeSnapshotManifest:
        normalized_pages = sorted((page.normalized() for page in pages), key=lambda item: item.page_id)
        chunks = build_chunks(normalized_pages)
        previous = self.repository.current_manifest()
        previous_pages = {page.page_id: page for page in self.repository.pages()}
        current_pages = {page.page_id: page for page in normalized_pages}
        added = sum(1 for page_id in current_pages if page_id not in previous_pages)
        updated = sum(
            1
            for page_id, page in current_pages.items()
            if page_id in previous_pages and page.content_hash != previous_pages[page_id].content_hash
        )
        unchanged = sum(
            1
            for page_id, page in current_pages.items()
            if page_id in previous_pages and page.content_hash == previous_pages[page_id].content_hash
        )
        removed = sum(1 for page_id in previous_pages if page_id not in current_pages)
        digest = hashlib.sha256(
            "\n".join(f"{page.page_id}:{page.content_hash}" for page in normalized_pages).encode("utf-8")
        ).hexdigest()
        created_at = utc_now_iso()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_id = f"snapshot_{stamp}_{digest[:10]}"
        manifest = KnowledgeSnapshotManifest(
            snapshot_id=snapshot_id,
            source_kind=source_kind,
            source_root=source_root,
            root_page_id=self.root_page_id,
            created_at=created_at,
            page_count=len(normalized_pages),
            chunk_count=len(chunks),
            added=added,
            updated=updated,
            unchanged=unchanged,
            removed=removed,
            previous_snapshot_id=previous.snapshot_id if previous is not None else "",
            content_hash=digest,
        )
        self.repository.save_snapshot(manifest=manifest, pages=normalized_pages, chunks=chunks, activate=True)
        return manifest


def knowledge_auth_headers(env: Mapping[str, str]) -> Dict[str, str]:
    bearer = str(env.get("WIICON5_KNOWLEDGE_BEARER_TOKEN") or "").strip()
    cookie = str(env.get("WIICON5_KNOWLEDGE_COOKIE") or "").strip()
    if bearer:
        return {"Authorization": f"Bearer {bearer}"}
    if cookie:
        return {"Cookie": cookie}
    return {}
