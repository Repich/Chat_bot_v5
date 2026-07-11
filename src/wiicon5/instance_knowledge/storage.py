from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from wiicon5.instance_knowledge.models import KnowledgeChunk, KnowledgePage, KnowledgeSnapshotManifest


class KnowledgeRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.snapshots_dir = root / "snapshots"
        self.current_file = root / "current.json"

    def current_snapshot_id(self) -> str:
        payload = read_json(self.current_file)
        return str(payload.get("snapshot_id") or "") if isinstance(payload, dict) else ""

    def current_manifest(self) -> Optional[KnowledgeSnapshotManifest]:
        snapshot_id = self.current_snapshot_id()
        return self.manifest(snapshot_id) if snapshot_id else None

    def manifest(self, snapshot_id: str) -> Optional[KnowledgeSnapshotManifest]:
        payload = read_json(self.snapshot_path(snapshot_id) / "manifest.json")
        return KnowledgeSnapshotManifest.from_dict(payload) if isinstance(payload, dict) else None

    def pages(self, snapshot_id: str = "") -> List[KnowledgePage]:
        effective_id = snapshot_id or self.current_snapshot_id()
        if not effective_id:
            return []
        return [KnowledgePage.from_dict(item) for item in read_json_lines(self.snapshot_path(effective_id) / "pages.jsonl")]

    def chunks(self, snapshot_id: str = "") -> List[KnowledgeChunk]:
        effective_id = snapshot_id or self.current_snapshot_id()
        if not effective_id:
            return []
        return [KnowledgeChunk.from_dict(item) for item in read_json_lines(self.snapshot_path(effective_id) / "index.jsonl")]

    def page(self, page_id: str, snapshot_id: str = "") -> Optional[KnowledgePage]:
        for page in self.pages(snapshot_id):
            if page.page_id == page_id:
                return page
        return None

    def list_manifests(self) -> List[KnowledgeSnapshotManifest]:
        if not self.snapshots_dir.exists():
            return []
        manifests = []
        for path in self.snapshots_dir.iterdir():
            if not path.is_dir() or path.name.startswith("."):
                continue
            manifest = self.manifest(path.name)
            if manifest is not None:
                manifests.append(manifest)
        return sorted(manifests, key=lambda item: item.created_at, reverse=True)

    def save_snapshot(
        self,
        *,
        manifest: KnowledgeSnapshotManifest,
        pages: Iterable[KnowledgePage],
        chunks: Iterable[KnowledgeChunk],
        activate: bool = True,
    ) -> Path:
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        target = self.snapshot_path(manifest.snapshot_id)
        if target.exists():
            raise FileExistsError(f"Knowledge snapshot already exists: {manifest.snapshot_id}")
        temporary = self.snapshots_dir / f".{manifest.snapshot_id}.{uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        try:
            write_json_lines(temporary / "pages.jsonl", [item.to_dict() for item in pages])
            write_json_lines(temporary / "index.jsonl", [item.to_dict() for item in chunks])
            atomic_write_json(temporary / "manifest.json", manifest.to_dict())
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        if activate:
            self.activate(manifest.snapshot_id)
        return target

    def activate(self, snapshot_id: str) -> KnowledgeSnapshotManifest:
        manifest = self.manifest(snapshot_id)
        if manifest is None:
            raise FileNotFoundError(f"Knowledge snapshot not found: {snapshot_id}")
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.current_file, {"snapshot_id": snapshot_id, "activated_at": manifest.created_at})
        return manifest

    def snapshot_path(self, snapshot_id: str) -> Path:
        safe_id = safe_snapshot_id(snapshot_id)
        return self.snapshots_dir / safe_id


def safe_snapshot_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("Invalid knowledge snapshot id.")
    return normalized


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_json_lines(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def write_json_lines(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
