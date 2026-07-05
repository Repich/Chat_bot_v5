from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional


class DraftStatus(str, Enum):
    DRAFT = "draft"
    READY_FOR_VALIDATION = "ready_for_validation"
    VALIDATED = "validated"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DraftEvidence:
    source: str
    reference: str
    trust: str = "hint"
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DraftEvidence":
        return cls(
            source=str(data.get("source") or ""),
            reference=str(data.get("reference") or ""),
            trust=str(data.get("trust") or "hint"),
            details=dict(data.get("details", {})) if isinstance(data.get("details"), Mapping) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "source": self.source,
            "reference": self.reference,
            "trust": self.trust,
        }
        if self.details:
            payload["details"] = jsonable(self.details)
        return payload


@dataclass(frozen=True)
class DataSourceRef:
    alias: str
    object_name: str
    object_kind: str = ""
    purpose: str = ""
    trust: str = "hint"
    evidence: List[DraftEvidence] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DataSourceRef":
        return cls(
            alias=str(data.get("alias") or ""),
            object_name=str(data.get("object_name") or data.get("object") or ""),
            object_kind=str(data.get("object_kind") or data.get("kind") or ""),
            purpose=str(data.get("purpose") or ""),
            trust=str(data.get("trust") or "hint"),
            evidence=evidence_list(data.get("evidence")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alias": self.alias,
            "object_name": self.object_name,
            "object_kind": self.object_kind,
            "purpose": self.purpose,
            "trust": self.trust,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class FieldMapping:
    role: str
    source_alias: str
    field_name: str
    path: str = ""
    required: bool = True
    confirmed: bool = False
    evidence: List[DraftEvidence] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldMapping":
        return cls(
            role=str(data.get("role") or ""),
            source_alias=str(data.get("source_alias") or data.get("source") or ""),
            field_name=str(data.get("field_name") or data.get("field") or ""),
            path=str(data.get("path") or ""),
            required=bool(data.get("required", True)),
            confirmed=bool(data.get("confirmed", False)),
            evidence=evidence_list(data.get("evidence")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "source_alias": self.source_alias,
            "field_name": self.field_name,
            "path": self.path,
            "required": self.required,
            "confirmed": self.confirmed,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class FilterRecipe:
    role: str
    operator: str = "equals"
    value_source: str = "input"
    parameter: str = ""
    required: bool = False
    description: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FilterRecipe":
        return cls(
            role=str(data.get("role") or ""),
            operator=str(data.get("operator") or "equals"),
            value_source=str(data.get("value_source") or "input"),
            parameter=str(data.get("parameter") or ""),
            required=bool(data.get("required", False)),
            description=str(data.get("description") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "operator": self.operator,
            "value_source": self.value_source,
            "parameter": self.parameter,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class MeasureRecipe:
    role: str
    expression: str
    aggregate: str = "sum"
    label: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeasureRecipe":
        return cls(
            role=str(data.get("role") or ""),
            expression=str(data.get("expression") or ""),
            aggregate=str(data.get("aggregate") or "sum"),
            label=str(data.get("label") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "expression": self.expression,
            "aggregate": self.aggregate,
            "label": self.label,
        }


@dataclass(frozen=True)
class SortRecipe:
    role: str = ""
    field: str = ""
    direction: str = "desc"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SortRecipe":
        return cls(
            role=str(data.get("role") or ""),
            field=str(data.get("field") or ""),
            direction=str(data.get("direction") or "desc"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "field": self.field, "direction": self.direction}


@dataclass(frozen=True)
class CalculationRecipe:
    kind: str = "manual"
    source_alias: str = ""
    filters: List[FilterRecipe] = field(default_factory=list)
    group_by: List[str] = field(default_factory=list)
    measures: List[MeasureRecipe] = field(default_factory=list)
    sort: List[SortRecipe] = field(default_factory=list)
    limit: Optional[int] = None
    notes: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalculationRecipe":
        return cls(
            kind=str(data.get("kind") or "manual"),
            source_alias=str(data.get("source_alias") or data.get("source") or ""),
            filters=[FilterRecipe.from_dict(item) for item in mapping_list(data.get("filters"))],
            group_by=[str(item) for item in list_value(data.get("group_by"))],
            measures=[MeasureRecipe.from_dict(item) for item in mapping_list(data.get("measures"))],
            sort=[SortRecipe.from_dict(item) for item in mapping_list(data.get("sort"))],
            limit=int(data["limit"]) if data.get("limit") is not None else None,
            notes=str(data.get("notes") or ""),
            raw=dict(data.get("raw", {})) if isinstance(data.get("raw"), Mapping) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "kind": self.kind,
            "source_alias": self.source_alias,
            "filters": [item.to_dict() for item in self.filters],
            "group_by": list(self.group_by),
            "measures": [item.to_dict() for item in self.measures],
            "sort": [item.to_dict() for item in self.sort],
            "notes": self.notes,
        }
        if self.limit is not None:
            payload["limit"] = self.limit
        if self.raw:
            payload["raw"] = jsonable(self.raw)
        return payload


@dataclass(frozen=True)
class PresentationRecipe:
    columns: List[str] = field(default_factory=list)
    answer_template: str = ""
    empty_result_text: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PresentationRecipe":
        return cls(
            columns=[str(item) for item in list_value(data.get("columns"))],
            answer_template=str(data.get("answer_template") or ""),
            empty_result_text=str(data.get("empty_result_text") or ""),
            notes=str(data.get("notes") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "columns": list(self.columns),
            "answer_template": self.answer_template,
            "empty_result_text": self.empty_result_text,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class HumanSkillDraft:
    draft_id: str = ""
    title: str = ""
    description: str = ""
    status: DraftStatus = DraftStatus.DRAFT
    example_questions: List[str] = field(default_factory=list)
    business_entities: List[str] = field(default_factory=list)
    data_sources: List[DataSourceRef] = field(default_factory=list)
    field_mappings: List[FieldMapping] = field(default_factory=list)
    calculation: CalculationRecipe = field(default_factory=CalculationRecipe)
    presentation: PresentationRecipe = field(default_factory=PresentationRecipe)
    output_artifact_type: str = ""
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    source_kind: str = "manual"
    source_trace: str = ""
    created_at: str = ""
    created_by: str = ""
    updated_at: str = ""
    updated_by: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HumanSkillDraft":
        known = {
            "draft_id",
            "title",
            "description",
            "status",
            "example_questions",
            "business_entities",
            "data_sources",
            "field_mappings",
            "calculation",
            "presentation",
            "output_artifact_type",
            "tags",
            "notes",
            "source_kind",
            "source_trace",
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
        }
        return cls(
            draft_id=str(data.get("draft_id") or data.get("id") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            status=draft_status(data.get("status")),
            example_questions=[str(item) for item in list_value(data.get("example_questions"))],
            business_entities=[str(item) for item in list_value(data.get("business_entities"))],
            data_sources=[DataSourceRef.from_dict(item) for item in mapping_list(data.get("data_sources"))],
            field_mappings=[FieldMapping.from_dict(item) for item in mapping_list(data.get("field_mappings"))],
            calculation=CalculationRecipe.from_dict(
                data.get("calculation") if isinstance(data.get("calculation"), Mapping) else {}
            ),
            presentation=PresentationRecipe.from_dict(
                data.get("presentation") if isinstance(data.get("presentation"), Mapping) else {}
            ),
            output_artifact_type=str(data.get("output_artifact_type") or ""),
            tags=[str(item) for item in list_value(data.get("tags"))],
            notes=str(data.get("notes") or ""),
            source_kind=str(data.get("source_kind") or "manual"),
            source_trace=str(data.get("source_trace") or ""),
            created_at=str(data.get("created_at") or ""),
            created_by=str(data.get("created_by") or ""),
            updated_at=str(data.get("updated_at") or ""),
            updated_by=str(data.get("updated_by") or ""),
            extras={str(key): jsonable(value) for key, value in data.items() if key not in known},
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.extras)
        payload.update(
            {
                "draft_id": self.draft_id,
                "title": self.title,
                "description": self.description,
                "status": self.status.value,
                "example_questions": list(self.example_questions),
                "business_entities": list(self.business_entities),
                "data_sources": [item.to_dict() for item in self.data_sources],
                "field_mappings": [item.to_dict() for item in self.field_mappings],
                "calculation": self.calculation.to_dict(),
                "presentation": self.presentation.to_dict(),
                "output_artifact_type": self.output_artifact_type,
                "tags": list(self.tags),
                "notes": self.notes,
                "source_kind": self.source_kind,
                "source_trace": self.source_trace,
                "created_at": self.created_at,
                "created_by": self.created_by,
                "updated_at": self.updated_at,
                "updated_by": self.updated_by,
            }
        )
        return jsonable(payload)


def draft_status(value: Any) -> DraftStatus:
    try:
        return DraftStatus(str(value or DraftStatus.DRAFT.value))
    except ValueError:
        return DraftStatus.DRAFT


def evidence_list(value: Any) -> List[DraftEvidence]:
    return [DraftEvidence.from_dict(item) for item in mapping_list(value)]


def mapping_list(value: Any) -> List[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def list_value(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
