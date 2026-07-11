from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.instance_knowledge.storage import KnowledgeRepository
from wiicon5.instance_knowledge.sync import KnowledgeSyncService


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize instance documentation into an immutable local snapshot.")
    parser.add_argument("--root", default=".", help="Project root.")
    parser.add_argument("--input-json", default="", help="Optional Confluence/generic JSON export.")
    parser.add_argument("--input-dir", default="", help="Optional directory with Markdown, text, or HTML pages.")
    parser.add_argument("--activate", default="", help="Activate an existing snapshot instead of synchronizing.")
    parser.add_argument("--status", action="store_true", help="Print knowledge snapshot status without changes.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    settings = Settings.from_env(root=root)
    repository = KnowledgeRepository(settings.bot_context.root / "knowledge")
    if args.status:
        print(
            json.dumps(
                {
                    "current": repository.current_manifest().to_dict() if repository.current_manifest() else None,
                    "snapshots": [item.to_dict() for item in repository.list_manifests()],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    knowledge = settings.bot_instance.knowledge
    service = KnowledgeSyncService(
        repository=repository,
        source_kind=knowledge.source_kind,
        base_url=knowledge.base_url,
        root_page_id=knowledge.root_page_id,
        timeout_seconds=knowledge.sync_timeout_seconds,
        max_pages=knowledge.max_pages,
    )
    if args.activate:
        manifest = service.activate(args.activate)
        print(json.dumps({"ok": True, "manifest": manifest.to_dict()}, ensure_ascii=False, indent=2))
        return 0
    result = service.sync(
        input_json=Path(args.input_json).expanduser().resolve() if args.input_json else None,
        input_dir=Path(args.input_dir).expanduser().resolve() if args.input_dir else None,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
