from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


class SkillKind(str, Enum):
    TECHNICAL = "technical"
    DISCOVERY = "discovery"
    DATA = "data_acquisition"
    TRANSFORM = "transform"
    PRESENTATION = "presentation"
    COMPOSITE = "composite"


class SkillStatus(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    BLOCKED = "blocked"


class GapResolution(str, Enum):
    USE_EXISTING = "use_existing_skill"
    COMPOSE_EXISTING = "compose_existing_skills"
    ADD_BINDING = "add_binding_to_existing_skill"
    EXTEND_EXISTING = "extend_existing_skill"
    GENERALIZE_EXISTING = "generalize_existing_skill"
    CREATE_DERIVED = "create_derived_skill"
    CREATE_NEW = "create_new_atomic_skill"
    CLARIFY = "ask_clarification"
    CANNOT_SOLVE = "cannot_safely_solve"


@dataclass(frozen=True)
class Port:
    name: str
    type: str
    required: bool = True
    description: str = ""
    default: Any = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Port":
        return cls(
            name=str(data["name"]),
            type=str(data["type"]),
            required=bool(data.get("required", True)),
            description=str(data.get("description", "")),
            default=data.get("default"),
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
        }
        if self.default is not None:
            data["default"] = self.default
        return data


@dataclass(frozen=True)
class SemanticFilter:
    semantic_field: str
    operator: str
    value: Any
    raw_user_text: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticFilter":
        return cls(
            semantic_field=str(data["semantic_field"]),
            operator=str(data.get("operator", "equals")),
            value=data.get("value"),
            raw_user_text=str(data.get("raw_user_text", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "semantic_field": self.semantic_field,
            "operator": self.operator,
            "value": self.value,
            "raw_user_text": self.raw_user_text,
        }


@dataclass(frozen=True)
class ArtifactRequirement:
    name: str
    type: str
    source: str = "skill"
    required: bool = True
    constraints: List[SemanticFilter] = field(default_factory=list)
    required_columns: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRequirement":
        return cls(
            name=str(data["name"]),
            type=str(data["type"]),
            source=str(data.get("source", "skill")),
            required=bool(data.get("required", True)),
            constraints=[SemanticFilter.from_dict(item) for item in data.get("constraints", [])],
            required_columns=[str(item) for item in data.get("required_columns", [])],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "source": self.source,
            "required": self.required,
            "constraints": [item.to_dict() for item in self.constraints],
            "required_columns": list(self.required_columns),
        }


@dataclass(frozen=True)
class SkillContract:
    skill_id: str
    version: str
    kind: SkillKind
    status: SkillStatus
    description: str
    capabilities: List[str]
    inputs: List[Port]
    outputs: List[Port]
    tags: List[str] = field(default_factory=list)
    semantic_role: Optional[str] = None
    supported_filter_roles: List[str] = field(default_factory=list)
    implementation_strategy: str = ""
    implementation: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SkillContract":
        return cls(
            skill_id=str(data["skill_id"]),
            version=str(data.get("version", "0.1.0")),
            kind=SkillKind(str(data["kind"])),
            status=SkillStatus(str(data.get("status", SkillStatus.DRAFT.value))),
            description=str(data.get("description", "")),
            capabilities=[str(item) for item in data.get("capabilities", [])],
            inputs=[Port.from_dict(item) for item in data.get("inputs", [])],
            outputs=[Port.from_dict(item) for item in data.get("outputs", [])],
            tags=[str(item) for item in data.get("tags", [])],
            semantic_role=data.get("semantic_role"),
            supported_filter_roles=[str(item) for item in data.get("supported_filter_roles", [])],
            implementation_strategy=str(data.get("implementation_strategy", "")),
            implementation=dict(data.get("implementation", {})) if isinstance(data.get("implementation"), Mapping) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "skill_id": self.skill_id,
            "version": self.version,
            "kind": self.kind.value,
            "status": self.status.value,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
            "tags": list(self.tags),
            "supported_filter_roles": list(self.supported_filter_roles),
            "implementation_strategy": self.implementation_strategy,
        }
        if self.implementation:
            data["implementation"] = dict(self.implementation)
        if self.semantic_role:
            data["semantic_role"] = self.semantic_role
        return data

    def produces(self, artifact_type: str) -> bool:
        return any(output.type == artifact_type for output in self.outputs)

    def output_names_for_type(self, artifact_type: str) -> List[str]:
        return [output.name for output in self.outputs if output.type == artifact_type]

    def input_by_type(self, artifact_type: str) -> List[Port]:
        return [input_port for input_port in self.inputs if input_port.type == artifact_type]

    def has_required_input_type(self, artifact_type: str) -> bool:
        return any(port.required and port.type == artifact_type for port in self.inputs)


@dataclass(frozen=True)
class SkillBinding:
    skill_id: str
    config_fingerprint: str
    semantic_role: str
    one_c_object: Dict[str, str]
    fields: Dict[str, str]
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SkillBinding":
        return cls(
            skill_id=str(data["skill_id"]),
            config_fingerprint=str(data["config_fingerprint"]),
            semantic_role=str(data["semantic_role"]),
            one_c_object={str(key): str(value) for key, value in data.get("one_c_object", {}).items()},
            fields={str(key): str(value) for key, value in data.get("fields", {}).items()},
            confidence=float(data.get("confidence", 0.0)),
            evidence=[str(item) for item in data.get("evidence", [])],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "config_fingerprint": self.config_fingerprint,
            "semantic_role": self.semantic_role,
            "one_c_object": dict(self.one_c_object),
            "fields": dict(self.fields),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class SkillInvocation:
    invocation_id: str
    skill_id: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    expected_outputs: Dict[str, str] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "skill_id": self.skill_id,
            "inputs": _jsonable(self.inputs),
            "expected_outputs": dict(self.expected_outputs),
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class SkillPlan:
    plan_id: str
    business_goal: str
    expected_answer_type: str
    nodes: List[SkillInvocation]
    edges: List[List[str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "business_goal": self.business_goal,
            "expected_answer_type": self.expected_answer_type,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [list(edge) for edge in self.edges],
        }


@dataclass(frozen=True)
class SkillGap:
    required_capability: str
    required_output: str
    reason: str
    nearest_skill_ids: List[str]
    recommended_resolution: GapResolution
    missing: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_capability": self.required_capability,
            "required_output": self.required_output,
            "reason": self.reason,
            "nearest_skill_ids": list(self.nearest_skill_ids),
            "recommended_resolution": self.recommended_resolution.value,
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(ok=True, issues=[])

    @classmethod
    def failure(cls, issues: Iterable[ValidationIssue]) -> "ValidationResult":
        return cls(ok=False, issues=list(issues))

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "issues": [issue.to_dict() for issue in self.issues]}


def status_rank(status: SkillStatus) -> int:
    ranking = {
        SkillStatus.STABLE: 5,
        SkillStatus.VERIFIED: 4,
        SkillStatus.CANDIDATE: 2,
        SkillStatus.DRAFT: 1,
        SkillStatus.DEPRECATED: 0,
        SkillStatus.BLOCKED: -1,
    }
    return ranking[status]


def required_inputs(skill: SkillContract) -> Sequence[Port]:
    return [port for port in skill.inputs if port.required and port.default is None]


def _jsonable(value: Any) -> Any:
    if isinstance(value, SemanticFilter):
        return value.to_dict()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
