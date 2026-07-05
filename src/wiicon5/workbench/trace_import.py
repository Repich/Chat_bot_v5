from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from wiicon5.workbench.models import (
    CalculationRecipe,
    DataSourceRef,
    DraftEvidence,
    FieldMapping,
    HumanSkillDraft,
    PresentationRecipe,
)


class TraceDraftImporter:
    def __init__(self, *, runs_root: Path) -> None:
        self.runs_root = runs_root

    def draft_from_trace(self, trace_path: Path) -> HumanSkillDraft:
        resolved = self._resolve_trace_path(trace_path)
        return draft_from_trace(resolved)

    def _resolve_trace_path(self, trace_path: Path) -> Path:
        path = trace_path.expanduser()
        if not path.is_absolute():
            path = self.runs_root / path
        resolved = path.resolve()
        runs_root = self.runs_root.resolve()
        try:
            resolved.relative_to(runs_root)
        except ValueError as exc:
            raise ValueError(f"Trace path must be inside runs root: {runs_root}") from exc
        return resolved


def draft_from_trace(trace_path: Path) -> HumanSkillDraft:
    user_message = read_json(trace_path / "input" / "user_message.json")
    goal = read_json(trace_path / "intent" / "goal_decomposition.json")
    result = read_json(trace_path / "result" / "result.json")
    synthesis_payload = read_json(trace_path / "query_synthesis" / "result.json")
    synthesis = synthesis_payload.get("synthesis") if isinstance(synthesis_payload.get("synthesis"), Mapping) else {}
    synthesis_trace = synthesis.get("trace") if isinstance(synthesis.get("trace"), Mapping) else {}
    final_query = synthesis_trace.get("final_query") if isinstance(synthesis_trace.get("final_query"), Mapping) else {}
    query = str(final_query.get("query") or "")
    params = final_query.get("params") if isinstance(final_query.get("params"), Mapping) else {}
    limit = int(final_query.get("limit") or 100)
    metadata_objects = [item for item in synthesis_trace.get("metadata_objects", []) if isinstance(item, Mapping)]
    sources = query_sources(query)
    if not sources:
        sources = sources_from_metadata(metadata_objects)
    data_sources = [
        DataSourceRef(
            alias=source["alias"],
            object_name=source["source"],
            object_kind=object_kind(source["source"]),
            purpose="imported_from_trace",
            trust=source_trust(source["source"], metadata_objects),
            evidence=[DraftEvidence(source="trace", reference=str(trace_path), trust="hint")],
        )
        for source in sources
    ]
    field_mappings = query_field_mappings(query=query, sources=sources, metadata_objects=metadata_objects, trace_path=trace_path)
    columns = artifact_columns(synthesis.get("final_artifact") if isinstance(synthesis, Mapping) else None)
    if not columns:
        columns = artifact_columns(result.get("final_artifact") if isinstance(result.get("final_artifact"), Mapping) else None)
    question = str(user_message.get("message") or "")
    business_entities = business_entities_from_goal(goal)
    return HumanSkillDraft(
        title=question[:120] or "Черновик навыка из trace",
        description=description_from_trace(result=result, synthesis=synthesis),
        example_questions=[question] if question else [],
        business_entities=business_entities,
        data_sources=data_sources,
        field_mappings=field_mappings,
        calculation=CalculationRecipe(
            kind="trace_query",
            source_alias=sources[0]["alias"] if sources else "",
            limit=limit,
            notes="Imported from runtime trace. Human review and validation are required before publishing.",
            raw={"query": query, "params": dict(params), "trace_path": str(trace_path)},
        ),
        presentation=PresentationRecipe(columns=columns),
        tags=["trace_import"],
        notes="Черновик создан из runtime trace. Это не подтвержденный runtime-навык.",
        source_kind="trace",
        source_trace=str(trace_path),
    )


def query_sources(query: str) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    pattern = re.compile(
        r"\b(?:ИЗ|СОЕДИНЕНИЕ)\s+(?P<source>[A-Za-zА-Яа-яЁё0-9_.]+(?:\s*\([^)]*\))?)\s+КАК\s+(?P<alias>[A-Za-zА-Яа-яЁё0-9_]+)",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(query):
        add_source(result, source=match.group("source").strip(), alias=match.group("alias").strip())
    return result


def sources_from_metadata(metadata_objects: List[Mapping[str, Any]]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in metadata_objects:
        full_name = str(item.get("full_name") or "")
        if not full_name:
            continue
        add_source(result, source=full_name, alias=full_name.rsplit(".", 1)[-1])
    return result


def add_source(result: List[Dict[str, str]], *, source: str, alias: str) -> None:
    if not source or not alias:
        return
    if any(item["alias"] == alias and item["source"] == source for item in result):
        return
    result.append({"source": source, "alias": alias})


def query_field_mappings(
    *,
    query: str,
    sources: List[Dict[str, str]],
    metadata_objects: List[Mapping[str, Any]],
    trace_path: Path,
) -> List[FieldMapping]:
    result: List[FieldMapping] = []
    seen = set()
    for source in sources:
        alias = source["alias"]
        for field_name in sorted(set(re.findall(rf"\b{re.escape(alias)}\.([A-Za-zА-Яа-яЁё0-9_]+)\b", query))):
            key = (alias, field_name)
            if key in seen:
                continue
            seen.add(key)
            confirmed = field_confirmed(source["source"], field_name, metadata_objects)
            result.append(
                FieldMapping(
                    role=field_name,
                    source_alias=alias,
                    field_name=field_name,
                    path=f"{source['source']}.{field_name}",
                    required=True,
                    confirmed=confirmed,
                    evidence=[
                        DraftEvidence(
                            source="trace_query",
                            reference=str(trace_path),
                            trust="verified" if confirmed else "hint",
                        )
                    ],
                )
            )
    return result


def field_confirmed(source: str, field_name: str, metadata_objects: List[Mapping[str, Any]]) -> bool:
    metadata = source_metadata(source, metadata_objects)
    if metadata is None:
        return False
    return field_name in [str(item) for item in metadata.get("fields", [])]


def source_metadata(source: str, metadata_objects: List[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    normalized_source = normalize_source_name(source)
    for item in metadata_objects:
        full_name = str(item.get("full_name") or "")
        if full_name and (normalized_source == full_name or normalized_source.startswith(full_name)):
            return item
    return None


def source_trust(source: str, metadata_objects: List[Mapping[str, Any]]) -> str:
    metadata = source_metadata(source, metadata_objects)
    return str(metadata.get("trust") or "hint") if metadata is not None else "hint"


def normalize_source_name(source: str) -> str:
    compact = re.sub(r"\s+", "", source)
    compact = re.sub(r"\.(ОстаткиИОбороты|Остатки|Обороты)\(.*$", "", compact)
    return compact


def artifact_columns(artifact: Any) -> List[str]:
    if not isinstance(artifact, Mapping):
        return []
    value = artifact.get("value")
    if isinstance(value, Mapping):
        columns = value.get("columns")
        if isinstance(columns, list):
            return [str(item) for item in columns]
        rows = value.get("rows")
        if isinstance(rows, list) and rows and isinstance(rows[0], Mapping):
            return [str(key) for key in rows[0].keys()]
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return [str(key) for key in value[0].keys()]
    return []


def business_entities_from_goal(goal: Mapping[str, Any]) -> List[str]:
    result: List[str] = []
    for key in ("business_goal", "final_artifact_type", "expected_answer_type"):
        value = str(goal.get(key) or "")
        if value and value not in result:
            result.append(value)
    artifacts = goal.get("required_artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                continue
            for key in ("name", "type"):
                value = str(artifact.get(key) or "")
                if value and value not in result:
                    result.append(value)
    return result


def description_from_trace(*, result: Mapping[str, Any], synthesis: Mapping[str, Any]) -> str:
    parts = ["Черновик навыка, импортированный из runtime trace."]
    source = str(result.get("source") or "")
    if source:
        parts.append(f"Источник результата: {source}.")
    if synthesis.get("ok") is not None:
        parts.append(f"Query synthesis ok: {bool(synthesis.get('ok'))}.")
    message = str(result.get("message") or "")
    if message:
        parts.append(f"Ответ агента: {message[:500]}")
    return " ".join(parts)


def object_kind(full_name: str) -> str:
    return full_name.split(".", 1)[0] if "." in full_name else ""


def read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
