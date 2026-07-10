from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from wiicon5.models import ArtifactRequirement, GapResolution, SemanticFilter, SkillContract, SkillGap, SkillInvocation, SkillPlan
from wiicon5.planner.aggregate_intent import AGGREGATE_TABLE_TYPE, document_list_misused_for_aggregation
from wiicon5.planner.domain_compatibility import (
    constraint_selects_skill_domain,
    skill_domain_compatible,
)
from wiicon5.planner.gap_detector import GapDetector
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.planner.placeholders import is_unresolved_placeholder_value
from wiicon5.planner.validator import SkillPlanValidator
from wiicon5.semantic_roles import roles_match
from wiicon5.skills.registry import SkillRegistry
from wiicon5.skills.semantic_contract import SemanticSkillContract, contract_from_goal, semantic_contract_compatibility
from wiicon5.types import TypeSystem


@dataclass(frozen=True)
class ComposeResult:
    plan: Optional[SkillPlan]
    gaps: List[SkillGap] = field(default_factory=list)
    search_trace: List[Dict[str, Any]] = field(default_factory=list)


class SkillComposer:
    def __init__(self, registry: SkillRegistry, type_system: Optional[TypeSystem] = None) -> None:
        self.registry = registry
        self.type_system = type_system or TypeSystem()
        self.gap_detector = GapDetector(registry, self.type_system)
        self.validator = SkillPlanValidator(registry)

    def compose(self, goal: GoalDecomposition) -> ComposeResult:
        goal = self._normalize_question_entity_filters(goal)
        aggregate_gap = self._aggregate_document_list_gap(goal)
        if aggregate_gap is not None:
            return ComposeResult(plan=None, gaps=[aggregate_gap])

        state = _ComposeState(goal=goal)
        try:
            self._ensure_artifact(goal.final_artifact_type, state)
        except _CompositionGap as exc:
            return ComposeResult(plan=None, gaps=[exc.gap], search_trace=state.search_trace)

        missing_required_gap = self._missing_required_artifact_gap(goal, state)
        if missing_required_gap is not None:
            return ComposeResult(plan=None, gaps=[missing_required_gap], search_trace=state.search_trace)

        plan = SkillPlan(
            plan_id="plan_001",
            business_goal=goal.business_goal,
            expected_answer_type=goal.expected_answer_type,
            nodes=state.nodes,
            edges=state.edges,
        )
        validation = self.validator.validate(plan)
        if not validation.ok:
            return ComposeResult(
                plan=None,
                gaps=[
                    SkillGap(
                        required_capability="valid_skill_plan",
                        required_output=goal.final_artifact_type,
                        reason="Generated skill plan failed deterministic validation.",
                        nearest_skill_ids=[node.skill_id for node in state.nodes],
                        recommended_resolution=self._validation_gap_resolution(validation.issues[0].code),
                        missing=[issue.code for issue in validation.issues],
                    )
                ],
                search_trace=state.search_trace,
            )
        return ComposeResult(plan=plan, gaps=[], search_trace=state.search_trace)

    def _normalize_question_entity_filters(self, goal: GoalDecomposition) -> GoalDecomposition:
        transferable: List[ArtifactRequirement] = []
        passthrough: List[ArtifactRequirement] = []
        for requirement in goal.required_artifacts:
            if question_entity_ref_requirement(requirement):
                transferable.append(requirement)
            else:
                passthrough.append(requirement)
        if not transferable:
            return goal

        changed = False
        normalized: List[ArtifactRequirement] = []
        for requirement in passthrough:
            accepted: List[SemanticFilter] = []
            for entity_requirement in transferable:
                if table_requirement_accepts_constraints(
                    requirement,
                    entity_requirement.constraints,
                    goal=goal,
                    registry=self.registry,
                    type_system=self.type_system,
                ):
                    accepted.extend(entity_requirement.constraints)
            if accepted:
                changed = True
                normalized.append(
                    ArtifactRequirement(
                        name=requirement.name,
                        type=requirement.type,
                        source=requirement.source,
                        required=requirement.required,
                        constraints=list(requirement.constraints) + accepted,
                        required_columns=list(requirement.required_columns),
                    )
                )
            else:
                normalized.append(requirement)

        for entity_requirement in transferable:
            if any(
                table_requirement_accepts_constraints(
                    requirement,
                    entity_requirement.constraints,
                    goal=goal,
                    registry=self.registry,
                    type_system=self.type_system,
                )
                for requirement in passthrough
            ):
                continue
            normalized.append(entity_requirement)

        if not changed:
            return goal
        return GoalDecomposition(
            business_goal=goal.business_goal,
            final_artifact_type=goal.final_artifact_type,
            expected_answer_type=goal.expected_answer_type,
            required_artifacts=normalized,
            semantic_contract=dict(goal.semantic_contract),
        )

    def _ensure_artifact(
        self,
        artifact_type: str,
        state: "_ComposeState",
        requirement_override: Optional[ArtifactRequirement] = None,
    ) -> Tuple[str, str]:
        existing = None if requirement_override and requirement_override.constraints else state.produced_artifact(artifact_type, self.type_system)
        if existing is not None:
            return existing

        requirement = requirement_override or state.goal.requirement_for_type(artifact_type)
        gap = self.gap_detector.detect_for_requirement(requirement, goal=state.goal)
        if gap is not None and not self._count_transform_applicable(requirement, state):
            raise _CompositionGap(gap)

        producer = self._choose_producer(requirement, state)
        if producer is None:
            raise _CompositionGap(
                SkillGap(
                    required_capability=f"produce:{artifact_type}",
                    required_output=artifact_type,
                    reason="No compatible producer was found.",
                    nearest_skill_ids=[],
                    recommended_resolution=self.gap_detector.detect_for_requirement(requirement, goal=state.goal).recommended_resolution
                    if self.gap_detector.detect_for_requirement(requirement, goal=state.goal)
                    else self._default_gap_resolution(),
                    missing=[artifact_type],
                )
            )

        inputs: Dict[str, Any] = {}
        dependencies: List[str] = []
        dependency_edges: List[Tuple[str, str, str]] = []
        consumed_constraints: List[SemanticFilter] = []
        for input_port in producer.inputs:
            matching_constraint = first_constraint_for_input(requirement.constraints, input_port.name)
            if matching_constraint is not None and input_port.type != "SemanticFilterList":
                if is_unresolved_placeholder_value(matching_constraint.value):
                    consumed_constraints.append(matching_constraint)
                    matching_constraint = None
                else:
                    inputs[input_port.name] = matching_constraint.value
                    consumed_constraints.append(matching_constraint)
                    continue
            if input_port.type == "SemanticFilterList":
                filter_constraints = semantic_filter_constraints_for_skill(requirement.constraints, producer)
                if filter_constraints:
                    inputs[input_port.name] = [item.to_dict() for item in filter_constraints]
                    consumed_constraints.extend(filter_constraints)
                elif input_port.required and input_port.default is None:
                    inputs[input_port.name] = []
                continue
            implicit_requirement = self._implicit_dependency_requirement(input_port.type, requirement, state)
            if implicit_requirement is not None:
                dependency_node, dependency_output = self._ensure_artifact(
                    implicit_requirement.type,
                    state,
                    requirement_override=implicit_requirement,
                )
                dependencies.append(dependency_node)
                dependency_edges.append((dependency_node, dependency_output, input_port.name))
                consumed_constraints.extend(implicit_requirement.constraints)
                continue
            if goal_has_assignable_requirement(state.goal, input_port.type, self.type_system):
                dependency_type = concrete_dependency_type_for_input(input_port.type, state, self.type_system)
                dependency_node, dependency_output = self._ensure_artifact(dependency_type, state)
                dependencies.append(dependency_node)
                dependency_edges.append((dependency_node, dependency_output, input_port.name))
                continue
            if input_port.required and input_port.default is None:
                if self.type_system.is_technical_port_type(input_port.type):
                    raise _CompositionGap(
                        SkillGap(
                            required_capability=f"input:{producer.skill_id}.{input_port.name}",
                            required_output=requirement.type,
                            reason=f"Required technical input {input_port.name} is missing.",
                            nearest_skill_ids=[producer.skill_id],
                            recommended_resolution=GapResolution.CLARIFY,
                            missing=[f"input:{input_port.name}"],
                        )
                    )
                raise _CompositionGap(
                    SkillGap(
                        required_capability=f"produce:{input_port.type}",
                        required_output=input_port.type,
                        reason=(
                            f"Skill {producer.skill_id} requires input artifact {input_port.type}, "
                            "but the user goal did not request or provide it."
                        ),
                        nearest_skill_ids=[producer.skill_id],
                        recommended_resolution=GapResolution.CLARIFY,
                        missing=[input_port.type],
                    )
                )
            elif input_port.default is not None:
                inputs[input_port.name] = input_port.default

        unconsumed_constraints = [
            constraint
            for constraint in requirement.constraints
            if constraint not in consumed_constraints
            and not is_unresolved_placeholder_value(constraint.value)
            and not constraint_selects_skill_domain(producer, constraint)
        ]
        if producer.kind.value == "data_acquisition" and unconsumed_constraints:
            raise _CompositionGap(
                SkillGap(
                    required_capability=f"route_filters:{producer.skill_id}",
                    required_output=requirement.type,
                    reason=(
                        "Selected skill can produce the artifact type, but at least one semantic filter "
                        "cannot be routed into skill inputs or an upstream lookup."
                    ),
                    nearest_skill_ids=[producer.skill_id],
                    recommended_resolution=GapResolution.EXTEND_EXISTING,
                    missing=[f"filter:{constraint.semantic_field}" for constraint in unconsumed_constraints],
                )
            )

        if requirement.required_columns:
            inputs["required_columns"] = list(requirement.required_columns)

        invocation_id = state.next_invocation_id()
        edges: List[List[str]] = []
        for dependency_node, dependency_output, input_name in dependency_edges:
            inputs[input_name] = f"${{{dependency_node}.{dependency_output}}}"
            edges.append([f"{dependency_node}.{dependency_output}", f"{invocation_id}.{input_name}"])

        expected_outputs = {output.name: output.type for output in producer.outputs}
        invocation = SkillInvocation(
            invocation_id=invocation_id,
            skill_id=producer.skill_id,
            inputs=inputs,
            expected_outputs=expected_outputs,
            depends_on=dependencies,
        )
        state.add_node(invocation)
        state.edges.extend(edges)
        output_names = producer.output_names_for_type(artifact_type)
        if output_names:
            return invocation_id, output_names[0]
        for output in producer.outputs:
            if self.type_system.is_assignable(output.type, artifact_type):
                return invocation_id, output.name
        raise RuntimeError(f"Producer {producer.skill_id} does not produce {artifact_type}.")

    def _choose_producer(self, requirement: ArtifactRequirement, state: "_ComposeState") -> Optional[SkillContract]:
        raw_candidates = [
            skill
            for skill in self.registry.active()
            if any(self.type_system.is_assignable(output.type, requirement.type) for output in skill.outputs)
        ]
        candidate_trace: List[Dict[str, Any]] = []
        candidates: List[SkillContract] = []
        for skill in raw_candidates:
            count_transform = skill.skill_id == "count_entities" and self._count_transform_applicable(requirement, state)
            accepts_constraints = all(_skill_accepts_constraint(skill, constraint) for constraint in requirement.constraints)
            domain_ok = skill_domain_compatible(skill, requirement, state.goal)
            semantic_compatibility = None
            if skill.implementation_strategy == "learned_query":
                semantic_compatibility = semantic_contract_compatibility(
                    contract_from_goal(None, state.goal),
                    SemanticSkillContract.from_dict(skill.semantic_contract),
                )
            accepted = (accepts_constraints or count_transform) and domain_ok
            score = producer_score(skill, requirement, state, self.type_system) if accepted else 0
            reasons = []
            if accepts_constraints:
                reasons.append("constraints_supported")
            if count_transform:
                reasons.append("count_transform_applicable")
            if domain_ok:
                reasons.append("domain_compatible")
            rejection_reason = ""
            if not accepted:
                if not (accepts_constraints or count_transform):
                    rejection_reason = "unsupported_constraints"
                elif not domain_ok:
                    rejection_reason = "domain_incompatible"
            candidate_trace.append(
                {
                    "skill_id": skill.skill_id,
                    "score": score,
                    "accepted": accepted,
                    "reasons": reasons,
                    "rejection_reason": rejection_reason,
                    "semantic_contract": semantic_compatibility.to_dict() if semantic_compatibility is not None else None,
                }
            )
            if accepted:
                candidates.append(skill)
        if not candidates:
            state.search_trace.append(
                {
                    "required_artifact": requirement.type,
                    "selected": "",
                    "candidates": candidate_trace,
                }
            )
            return None
        selected = sorted(
            candidates,
            key=lambda skill: (-producer_score(skill, requirement, state, self.type_system), skill.skill_id),
        )[0]
        state.search_trace.append(
            {
                "required_artifact": requirement.type,
                "selected": selected.skill_id,
                "candidates": candidate_trace,
            }
        )
        return selected

    def _count_transform_applicable(self, requirement: ArtifactRequirement, state: "_ComposeState") -> bool:
        if requirement.type not in {"AggregateTable", "CountResult"}:
            return False
        if not text_requests_count(state.goal.business_goal, requirement):
            return False
        return self._implicit_dependency_requirement("EntityRefList", requirement, state) is not None

    def _implicit_dependency_requirement(
        self,
        input_type: str,
        parent_requirement: ArtifactRequirement,
        state: "_ComposeState",
    ) -> Optional[ArtifactRequirement]:
        if input_type != "EntityRefList" and not input_type.endswith("RefList"):
            return None
        if not parent_requirement.constraints:
            return None
        constraints = entity_dependency_constraints(input_type, parent_requirement.constraints, self.registry, self.type_system)
        if not constraints:
            return None
        producer = self._choose_entity_list_producer(parent_requirement, state, input_type=input_type, constraints=constraints)
        if producer is None:
            return None
        output_type = next(
            (
                output.type
                for output in producer.outputs
                if output.type != input_type and self.type_system.is_assignable(output.type, input_type)
            ),
            "",
        )
        if not output_type and input_type != "EntityRefList":
            output_type = input_type
        if not output_type:
            return None
        return ArtifactRequirement(
            name=f"{parent_requirement.name}_items",
            type=output_type,
            source="skill",
            required=True,
            constraints=list(constraints),
        )

    def _choose_entity_list_producer(
        self,
        parent_requirement: ArtifactRequirement,
        state: "_ComposeState",
        *,
        input_type: str = "EntityRefList",
        constraints: Optional[List[SemanticFilter]] = None,
    ) -> Optional[SkillContract]:
        target_type = input_type if input_type != "EntityRefList" else "EntityRefList"
        requirement_constraints = list(constraints if constraints is not None else parent_requirement.constraints)
        entity_requirement = ArtifactRequirement(
            name=f"{parent_requirement.name}_items",
            type=target_type,
            source="skill",
            required=True,
            constraints=requirement_constraints,
        )
        candidates = [
            skill
            for skill in self.registry.active()
            if any(
                output.type != "EntityRefList" and self.type_system.is_assignable(output.type, target_type)
                for output in skill.outputs
            )
            if all(_skill_accepts_constraint(skill, constraint) for constraint in entity_requirement.constraints)
        ]
        candidates = [skill for skill in candidates if skill_domain_compatible(skill, entity_requirement, state.goal)]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda skill: (-producer_score(skill, entity_requirement, state, self.type_system), skill.skill_id),
        )[0]

    def _validation_gap_resolution(self, issue_code: str):
        from wiicon5.models import GapResolution

        if issue_code == "missing_required_input":
            return GapResolution.CLARIFY
        return GapResolution.CANNOT_SOLVE

    def _default_gap_resolution(self):
        from wiicon5.models import GapResolution

        return GapResolution.CREATE_NEW

    def _aggregate_document_list_gap(self, goal: GoalDecomposition) -> Optional[SkillGap]:
        if not document_list_misused_for_aggregation(goal):
            return None
        return SkillGap(
            required_capability="produce:aggregate_table",
            required_output=AGGREGATE_TABLE_TYPE,
            reason=(
                "The goal asks for aggregation/ranking, but the decomposed artifact is a raw document list. "
                "A document list cannot safely answer aggregate questions."
            ),
            nearest_skill_ids=[],
            recommended_resolution=GapResolution.CREATE_NEW,
            missing=["aggregate_query", "not_document_list"],
        )

    def _missing_required_artifact_gap(
        self,
        goal: GoalDecomposition,
        state: "_ComposeState",
    ) -> Optional[SkillGap]:
        for requirement in goal.required_artifacts:
            if not requirement.required or requirement.type == goal.final_artifact_type:
                continue
            if state.produced_artifact(requirement.type, self.type_system) is not None:
                continue
            detected = self.gap_detector.detect_for_requirement(requirement, goal=goal)
            if detected is not None:
                return detected
            return SkillGap(
                required_capability=f"produce:{requirement.type}",
                required_output=requirement.type,
                reason="Generated skill plan did not produce a required artifact from the decomposed goal.",
                nearest_skill_ids=[node.skill_id for node in state.nodes],
                recommended_resolution=GapResolution.CREATE_NEW,
                missing=[requirement.type, "required_artifact_not_produced"],
            )
        return None


@dataclass
class _ComposeState:
    goal: GoalDecomposition
    nodes: List[SkillInvocation] = field(default_factory=list)
    edges: List[List[str]] = field(default_factory=list)
    search_trace: List[Dict[str, Any]] = field(default_factory=list)
    _counter: int = 0

    def next_invocation_id(self) -> str:
        self._counter += 1
        return f"inv_{self._counter:03d}"

    def add_node(self, invocation: SkillInvocation) -> None:
        self.nodes.append(invocation)

    def produced_artifact(self, artifact_type: str, type_system: TypeSystem) -> Optional[Tuple[str, str]]:
        for node in self.nodes:
            for output_name, output_type in node.expected_outputs.items():
                if type_system.is_assignable(output_type, artifact_type):
                    return node.invocation_id, output_name
        return None


class _CompositionGap(Exception):
    def __init__(self, gap: SkillGap) -> None:
        super().__init__(gap.reason)
        self.gap = gap


def _skill_accepts_constraint(skill: SkillContract, constraint: SemanticFilter) -> bool:
    return (
        _constraint_targets_input(skill, constraint)
        or _constraint_targets_entity_ref_input(skill, constraint)
        or any(roles_match(constraint.semantic_field, role) for role in skill.supported_filter_roles)
        or roles_match(skill.semantic_role, constraint.semantic_field)
        or constraint_selects_skill_domain(skill, constraint)
    )


def question_entity_ref_requirement(requirement: ArtifactRequirement) -> bool:
    if requirement.source != "question":
        return False
    if not requirement.type.endswith("Ref") or requirement.type.endswith("RefList"):
        return False
    return bool(requirement.constraints)


def table_requirement_accepts_constraints(
    requirement: ArtifactRequirement,
    constraints: List[SemanticFilter],
    *,
    goal: GoalDecomposition,
    registry: SkillRegistry,
    type_system: TypeSystem,
) -> bool:
    if not constraints or not type_system.is_assignable(requirement.type, "TypedTable"):
        return False
    for skill in registry.active():
        if not any(type_system.is_assignable(output.type, requirement.type) for output in skill.outputs):
            continue
        merged = ArtifactRequirement(
            name=requirement.name,
            type=requirement.type,
            source=requirement.source,
            required=requirement.required,
            constraints=list(requirement.constraints) + list(constraints),
            required_columns=list(requirement.required_columns),
        )
        if all(_skill_accepts_constraint(skill, constraint) for constraint in constraints) and skill_domain_compatible(
            skill, merged, goal
        ):
            return True
    return False


def _constraint_targets_input(skill: SkillContract, constraint: SemanticFilter) -> bool:
    return any(roles_match(input_port.name, constraint.semantic_field) for input_port in skill.inputs)


def _constraint_targets_entity_ref_input(skill: SkillContract, constraint: SemanticFilter) -> bool:
    for input_port in skill.inputs:
        role = artifact_role_for_ref_list(input_port.type)
        if role and roles_match(role, constraint.semantic_field):
            return True
    return False


def artifact_role_for_ref_list(artifact_type: str) -> str:
    if not artifact_type.endswith("RefList"):
        return ""
    base = artifact_type[: -len("RefList")]
    mapping = {
        "Product": "product",
        "Warehouse": "warehouse",
        "Counterparty": "counterparty",
        "Document": "document",
    }
    return mapping.get(base, base[:1].lower() + base[1:] if base else "")


def first_constraint_for_input(constraints: List[SemanticFilter], input_name: str) -> Optional[SemanticFilter]:
    for constraint in constraints:
        if roles_match(constraint.semantic_field, input_name):
            return constraint
    return None


def semantic_filter_constraints_for_skill(
    constraints: List[SemanticFilter],
    skill: SkillContract,
) -> List[SemanticFilter]:
    return [
        constraint
        for constraint in constraints
        if not _constraint_targets_input(skill, constraint) and not constraint_selects_skill_domain(skill, constraint)
    ]


def entity_dependency_constraints(
    input_type: str,
    constraints: List[SemanticFilter],
    registry: SkillRegistry,
    type_system: TypeSystem,
) -> List[SemanticFilter]:
    if input_type == "EntityRefList":
        return list(constraints)
    role = artifact_role_for_ref_list(input_type)
    if not role:
        return []
    candidate_producers = [
        skill
        for skill in registry.active()
        if any(
            output.type != "EntityRefList" and type_system.is_assignable(output.type, input_type)
            for output in skill.outputs
        )
        if roles_match(skill.semantic_role, role)
    ]
    result = []
    for constraint in constraints:
        if is_unresolved_placeholder_value(constraint.value):
            continue
        if roles_match(constraint.semantic_field, role):
            result.append(constraint)
            continue
        if any(_skill_accepts_constraint(skill, constraint) for skill in candidate_producers):
            result.append(constraint)
    return result


def concrete_dependency_type_for_input(input_type: str, state: _ComposeState, type_system: TypeSystem) -> str:
    if not type_system.is_abstract_artifact_type(input_type):
        return input_type
    for requirement in reversed(state.goal.required_artifacts):
        if requirement.type != input_type and type_system.is_assignable(requirement.type, input_type):
            return requirement.type
    return input_type


def producer_score(
    skill: SkillContract,
    requirement: ArtifactRequirement,
    state: _ComposeState,
    type_system: TypeSystem,
) -> int:
    score = 0
    goal_required_types = {item.type for item in state.goal.required_artifacts}
    for output in skill.outputs:
        if output.type == requirement.type:
            score += 3
        elif type_system.is_assignable(output.type, requirement.type):
            score += 2
        if output.type in goal_required_types:
            score += 20

    if requirement.type == "UserAnswer":
        has_table_requirement = any(
            type_system.is_assignable(item.type, "TypedTable") for item in state.goal.required_artifacts
        )
        for input_port in skill.inputs:
            if input_port.required and goal_has_assignable_requirement(state.goal, input_port.type, type_system):
                score += 5
            if input_port.type == "TypedTable" and has_table_requirement:
                score += 10
            if input_port.type == "EntityRefList" and not has_table_requirement:
                score += 10
    if skill.implementation_strategy == "learned_query":
        compatibility = semantic_contract_compatibility(
            contract_from_goal(None, state.goal),
            SemanticSkillContract.from_dict(skill.semantic_contract),
        )
        if compatibility.compatible:
            score += compatibility.score
    return score


def goal_has_assignable_requirement(goal: GoalDecomposition, artifact_type: str, type_system: TypeSystem) -> bool:
    return any(type_system.is_assignable(item.type, artifact_type) for item in goal.required_artifacts)


def text_requests_count(goal_text: str, requirement: ArtifactRequirement) -> bool:
    parts = [goal_text, requirement.name]
    for constraint in requirement.constraints:
        parts.extend([str(constraint.value or ""), constraint.raw_user_text])
    lowered = " ".join(parts).lower()
    return any(marker in lowered for marker in ["сколько", "количество", "число", "count"])
