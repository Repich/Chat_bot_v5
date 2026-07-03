from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from wiicon5.conversation.context import ConversationContext
from wiicon5.knowledge.bindings import BindingResolver, JsonBindingStore
from wiicon5.knowledge.discovery import MetadataBindingDiscoverer
from wiicon5.knowledge.metadata import McpMetadataProvider
from wiicon5.mcp.client import HttpMcpClient
from wiicon5.query.document_list_query_builder import DocumentListQueryBuilder
from wiicon5.query.semantic_query_builder import SemanticQueryBuilder
from wiicon5.skills.registry import SkillRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="WIICON5 MCP metadata/query smoke diagnostic.")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:6003", help="MCP proxy base URL.")
    parser.add_argument("--skills-dir", default="skills", help="Skill contracts directory.")
    parser.add_argument("--bindings-dir", default="skills/bindings", help="Binding cache directory.")
    parser.add_argument("--skill-id", default="get_warehouses", help="Skill id to discover/build.")
    parser.add_argument("--config", default="local", help="Config fingerprint for binding cache.")
    parser.add_argument("--limit", type=int, default=10, help="Query limit for draft.")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout for MCP requests.")
    parser.add_argument("--metadata-limit", type=int, default=20, help="MCP metadata search limit.")
    parser.add_argument("--max-search-terms", type=int, default=2, help="Maximum semantic search terms for smoke.")
    parser.add_argument("--document-type", default="Заказ клиента", help="Document type/name for document list smoke.")
    parser.add_argument("--year", default="2024", help="Year for document list smoke.")
    args = parser.parse_args()

    registry = SkillRegistry.load_from_dir(Path(args.skills_dir))
    skill = registry.get(args.skill_id)
    if skill is None:
        print(json.dumps({"ok": False, "error": f"Unknown skill: {args.skill_id}"}, ensure_ascii=False, indent=2))
        return 2

    mcp = HttpMcpClient(base_url=args.mcp_url, timeout_seconds=args.timeout)
    metadata_provider = McpMetadataProvider(mcp, search_limit=args.metadata_limit)
    binding_store = JsonBindingStore(Path(args.bindings_dir))
    discoverer = MetadataBindingDiscoverer(metadata_provider, max_search_terms=args.max_search_terms)
    resolver = BindingResolver(binding_store, discoverer)
    context = ConversationContext(session_id="mcp-smoke", config_fingerprint=args.config)
    builder = query_builder_for_skill(skill, resolver, metadata_provider)
    inputs = default_inputs_for_skill(args.skill_id, args.limit, document_type=args.document_type, year=args.year)

    try:
        binding = None if skill.implementation_strategy == "semantic_document_list_query" else resolver.resolve(skill, context)
        draft = builder.build(skill, inputs, context)
    except Exception as exc:  # Diagnostic CLI must report full controlled failure.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "skill_id": args.skill_id,
                    "discovery": discoverer.last_diagnostics,
                    "metadata_requests": metadata_provider.last_requests,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "skill_id": args.skill_id,
                "binding": binding.to_dict() if binding is not None else None,
                "query_draft": draft.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def query_builder_for_skill(skill, resolver, metadata_provider):  # type: ignore[no-untyped-def]
    if skill.implementation_strategy == "semantic_document_list_query":
        return DocumentListQueryBuilder(metadata_provider)
    return SemanticQueryBuilder(resolver)


def default_inputs_for_skill(skill_id: str, limit: int, *, document_type: str = "", year: str = "") -> Dict[str, Any]:
    if skill_id == "get_warehouses":
        return {"filters": [], "limit": limit}
    if skill_id == "get_stock_balances":
        return {
            "product": {"ref": "diagnostic-product-ref"},
            "warehouses": [{"ref": "diagnostic-warehouse-ref"}],
            "limit": limit,
        }
    if skill_id == "count_transfer_documents_by_day":
        return {"filters": [], "period_granularity": "day", "limit": limit}
    if skill_id == "get_documents_by_type_and_period":
        return {
            "filters": [
                {"semantic_field": "document_type", "operator": "equals", "value": document_type},
                {"semantic_field": "year", "operator": "equals", "value": year},
            ],
            "limit": limit,
        }
    return {"limit": limit}


if __name__ == "__main__":
    raise SystemExit(main())
