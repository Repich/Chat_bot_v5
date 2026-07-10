from __future__ import annotations

from typing import Any, Dict, List, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact
from wiicon5.execution.runtime import SkillRunResult, SkillRunner
from wiicon5.knowledge.bindings import BindingError
from wiicon5.knowledge.metadata import MetadataProvider
from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpQueryRequest, normalize_mcp_rows
from wiicon5.models import SkillContract
from wiicon5.query.list_params import expand_in_list_parameters
from wiicon5.query.one_c_query_review import OneCQueryReviewer, QuerySourceRef, expected_fields_for_source
from wiicon5.query.one_c_query_safety import validate_read_only_query
from wiicon5.query.query_builder import QueryBuildError, QueryBuilder
from wiicon5.query.query_draft import QueryDraft
from wiicon5.query.reference_value_resolver import ReferenceValueResolver


class DataSkillRunner(SkillRunner):
    def __init__(
        self,
        *,
        query_builder: QueryBuilder,
        mcp_client: McpClient,
        query_reviewer: Optional[OneCQueryReviewer] = None,
        metadata_provider: Optional[MetadataProvider] = None,
    ) -> None:
        self.query_builder = query_builder
        self.mcp_client = mcp_client
        self.query_reviewer = query_reviewer
        self.metadata_provider = metadata_provider

    def run(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> SkillRunResult:
        try:
            draft = self.query_builder.build(skill, inputs, context)
        except (BindingError, QueryBuildError) as exc:
            return SkillRunResult(
                ok=False,
                skill_id=skill.skill_id,
                error=str(exc),
                trace={"query_build_error": str(exc)},
            )
        validation = validate_read_only_query(draft.query, draft.params)
        if not validation.ok:
            return SkillRunResult(
                ok=False,
                skill_id=skill.skill_id,
                error="Query safety validation failed.",
                trace={"query_draft": draft.to_dict(), "validation": validation.to_dict()},
            )
        query_review_payload = None
        reference_resolution_payload = None
        metadata_dependencies = self._metadata_dependencies(draft.metadata_dependencies)
        metadata_contract_error = ""
        if self.metadata_provider is not None:
            metadata_contract_error = metadata_dependency_contract_error(skill, metadata_dependencies)
        if metadata_contract_error:
            return SkillRunResult(
                ok=False,
                skill_id=skill.skill_id,
                error=metadata_contract_error,
                trace={"query_draft": draft.to_dict(), "metadata_dependency_contract_error": metadata_contract_error},
            )
        if metadata_dependencies:
            reference_resolution = ReferenceValueResolver(self.mcp_client).resolve(
                query=draft.query,
                params=draft.params,
                metadata_objects=metadata_dependencies,
            )
            reference_resolution_payload = reference_resolution.to_dict()
            if reference_resolution.changed:
                draft = QueryDraft(
                    query=reference_resolution.query,
                    params=reference_resolution.params,
                    limit=draft.limit,
                    include_schema=draft.include_schema,
                    metadata_dependencies=draft.metadata_dependencies,
                    reasoning=draft.reasoning,
                )
                validation = validate_read_only_query(draft.query, draft.params)
                if not validation.ok:
                    return SkillRunResult(
                        ok=False,
                        skill_id=skill.skill_id,
                        error="Query safety validation failed after reference value resolution.",
                        trace={
                            "query_draft": draft.to_dict(),
                            "reference_value_resolution": reference_resolution_payload,
                            "validation": validation.to_dict(),
                        },
                    )
        if self.query_reviewer is not None:
            list_param_expansion = expand_in_list_parameters(draft.query, draft.params)
            if list_param_expansion.changed:
                draft = QueryDraft(
                    query=list_param_expansion.query,
                    params=list_param_expansion.params,
                    limit=draft.limit,
                    include_schema=draft.include_schema,
                    metadata_dependencies=draft.metadata_dependencies,
                    reasoning=draft.reasoning,
                )
                validation = validate_read_only_query(draft.query, draft.params)
                if not validation.ok:
                    return SkillRunResult(
                        ok=False,
                        skill_id=skill.skill_id,
                        error="Query safety validation failed after list parameter expansion.",
                        trace={
                            "query_draft": draft.to_dict(),
                            "reference_value_resolution": reference_resolution_payload,
                            "list_param_expansion": list_param_expansion.to_dict(),
                            "validation": validation.to_dict(),
                        },
                    )
            query_review = self.query_reviewer.review(
                query=draft.query,
                params=draft.params,
                metadata_objects=metadata_dependencies,
            )
            query_review_payload = query_review.to_dict()
            if not query_review.ok:
                return SkillRunResult(
                    ok=False,
                    skill_id=skill.skill_id,
                    error="Query review failed: " + query_review.error_text(),
                    trace={
                        "query_draft": draft.to_dict(),
                        "reference_value_resolution": reference_resolution_payload,
                        "list_param_expansion": list_param_expansion.to_dict(),
                        "query_review": query_review.to_dict(),
                    },
                )
        else:
            list_param_expansion = expand_in_list_parameters(draft.query, draft.params)
            if list_param_expansion.changed:
                draft = QueryDraft(
                    query=list_param_expansion.query,
                    params=list_param_expansion.params,
                    limit=draft.limit,
                    include_schema=draft.include_schema,
                    metadata_dependencies=draft.metadata_dependencies,
                    reasoning=draft.reasoning,
                )
                validation = validate_read_only_query(draft.query, draft.params)
                if not validation.ok:
                    return SkillRunResult(
                        ok=False,
                        skill_id=skill.skill_id,
                        error="Query safety validation failed after list parameter expansion.",
                        trace={
                            "query_draft": draft.to_dict(),
                            "reference_value_resolution": reference_resolution_payload,
                            "list_param_expansion": list_param_expansion.to_dict(),
                            "validation": validation.to_dict(),
                        },
                    )
        response = self.mcp_client.execute_query(
            McpQueryRequest(
                query=draft.query,
                params=draft.params,
                limit=draft.limit,
                include_schema=draft.include_schema,
            )
        )
        rows = normalize_mcp_rows(response)
        if not response.success:
            return SkillRunResult(
                ok=False,
                skill_id=skill.skill_id,
                error=response.error or "MCP query failed.",
                trace={
                    "query_draft": draft.to_dict(),
                    "reference_value_resolution": reference_resolution_payload,
                    "list_param_expansion": list_param_expansion.to_dict(),
                    "mcp_response": response.raw,
                },
            )
        return SkillRunResult(
            ok=True,
            skill_id=skill.skill_id,
            artifacts=_artifacts_from_rows(skill, rows, draft.metadata_dependencies, schema_columns=schema_columns(response.schema)),
            trace={
                "query_draft": draft.to_dict(),
                "reference_value_resolution": reference_resolution_payload,
                "list_param_expansion": list_param_expansion.to_dict(),
                "query_review": query_review_payload,
                "row_count": len(rows),
                "mcp_response": response.raw,
            },
        )

    def _metadata_dependencies(self, full_names: List[str]):
        if self.metadata_provider is None:
            return []
        result = []
        for full_name in full_names:
            if full_name:
                result.append(self.metadata_provider.get_object(full_name))
        return result


def _artifacts_from_rows(
    skill: SkillContract,
    rows: List[Dict[str, Any]],
    provenance: List[str],
    *,
    schema_columns: Optional[List[str]] = None,
) -> List[Artifact]:
    if not skill.outputs:
        return []
    output = skill.outputs[0]
    columns = _columns_from_rows(rows) or list(schema_columns or [])
    if output.type.endswith("Table"):
        value: Any = {"columns": columns, "rows": rows}
    else:
        value = rows
    return [
        Artifact(
            name=output.name,
            type=output.type,
            value=value,
            provenance=list(provenance) + [skill.skill_id],
        )
    ]


def _columns_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def schema_columns(schema: Dict[str, Any]) -> List[str]:
    raw_columns = schema.get("columns") if isinstance(schema, dict) else None
    if not isinstance(raw_columns, list):
        return []
    result: List[str] = []
    for item in raw_columns:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def metadata_dependency_contract_error(skill: SkillContract, metadata_objects) -> str:
    contract = skill.implementation.get("metadata_dependency_contract")
    if not isinstance(contract, list) or not contract:
        return ""
    by_name = {item.full_name: item for item in metadata_objects if item.full_name}
    for dependency in contract:
        if not isinstance(dependency, dict):
            continue
        object_name = str(dependency.get("object") or "")
        if not object_name:
            continue
        metadata_object = by_name.get(object_name)
        parent_object = str(dependency.get("parent_object") or "")
        if (metadata_object is None or not metadata_object.fields) and parent_object:
            metadata_object = by_name.get(parent_object)
        if metadata_object is None:
            return f"Learned skill {skill.skill_id} metadata dependency is not available: {object_name}."
        required_fields = dependency.get("required_fields")
        if not isinstance(required_fields, dict):
            continue
        source_ref = QuerySourceRef(
            source=str(dependency.get("source") or object_name),
            alias="Источник",
            object_full_name=parent_object or object_name,
            object_type=str(dependency.get("object_type") or (parent_object or object_name).split(".", 1)[0]),
            virtual_table=str(dependency.get("virtual_table") or ""),
            table_part=str(dependency.get("table_part") or ""),
        )
        available_fields = expected_fields_for_source(source_ref, metadata_object)
        missing = [field for field in required_fields if field not in available_fields]
        if missing:
            return (
                f"Learned skill {skill.skill_id} metadata dependency changed for {object_name}; "
                f"missing fields: {', '.join(missing)}."
            )
    return ""
