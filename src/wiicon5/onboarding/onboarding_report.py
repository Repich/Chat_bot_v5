from __future__ import annotations

from typing import Dict, List

from wiicon5.onboarding.metadata_index_builder import IndexedObject
from wiicon5.onboarding.query_pattern_extractor import QueryPattern
from wiicon5.onboarding.register_usage_analyzer import RegisterUsageCandidate


def render_onboarding_report(
    *,
    objects: List[IndexedObject],
    query_patterns: List[QueryPattern],
    register_usage: List[RegisterUsageCandidate],
    binding_candidates: List[Dict[str, object]],
) -> str:
    lines = [
        "# Onboarding Report",
        "",
        "This report contains candidates only. It does not approve skills or bindings automatically.",
        "",
        f"- Metadata objects found: {len(objects)}",
        f"- Query patterns found: {len(query_patterns)}",
        f"- Register usage candidates: {len(register_usage)}",
        f"- Binding candidates: {len(binding_candidates)}",
        "",
        "## Top Metadata Objects",
        "",
    ]
    for item in objects[:20]:
        lines.append(f"- `{item.full_name}` from {', '.join(item.source_files[:3])}")
    lines.extend(["", "## Binding Candidates", ""])
    for candidate in binding_candidates[:50]:
        lines.append(
            f"- `{candidate['semantic_role']}` -> `{candidate['object']}` "
            f"(confidence={candidate['confidence']})"
        )
    return "\n".join(lines) + "\n"
