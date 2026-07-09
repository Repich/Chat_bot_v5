from __future__ import annotations

from typing import Any, Dict, List, Optional

from wiicon5.bot_instance import BotInstanceConfig
from wiicon5.conversation.context import ConversationContext
from wiicon5.intent.decomposer import DecompositionResult, GoalDecomposer
from wiicon5.intent.models import ContextDependency, IntentResult, IntentType
from wiicon5.llm.client import LLMClient, LLMProviderError
from wiicon5.models import ArtifactRequirement, SemanticFilter
from wiicon5.planner.aggregate_intent import AGGREGATE_TABLE_TYPE, repair_document_list_aggregate_goal
from wiicon5.planner.domain_compatibility import meaningful_words, words_match
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.prompting import PromptCatalog
from wiicon5.skills.registry import SkillRegistry
from wiicon5.types import TypeSystem


class LLMGoalDecomposer(GoalDecomposer):
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        registry: SkillRegistry,
        bot_config: Optional[BotInstanceConfig] = None,
        prompt_catalog: Optional[PromptCatalog] = None,
    ) -> None:
        self.llm_client = llm_client
        self.registry = registry
        self.bot_config = bot_config or BotInstanceConfig.default()
        self.prompt_catalog = prompt_catalog or PromptCatalog()

    def decompose(self, message: str, context: ConversationContext) -> DecompositionResult:
        payload = {
            "message": message,
            "conversation_context": context.to_packet(),
            "available_artifact_types": sorted(available_artifact_types(self.registry)),
            "available_skills": skill_catalog(self.registry),
            "schema": decomposition_schema(),
        }
        try:
            response = self.llm_client.complete_json(
                system_prompt=self.prompt_catalog.decomposition_prompt(self.bot_config),
                user_payload=payload,
            )
        except LLMProviderError as exc:
            return DecompositionResult(intent=unknown_intent(message, f"LLM unavailable: {exc}"))
        return parse_decomposition_response(message, response, self.registry)


DECOMPOSITION_PROMPT = PromptCatalog().decomposition_prompt(BotInstanceConfig.default())


def decomposition_schema() -> Dict[str, Any]:
    return {
        "intent": {
            "intent_type": "data_question | general_question | clarification | out_of_scope | unknown",
            "business_goal": "short user business goal",
            "requires_1c_data": "boolean",
            "expected_output": "table | short_answer | answer",
            "domain_terms": ["terms from user question"],
            "context_dependencies": [
                {
                    "role": "semantic role, e.g. product",
                    "artifact_type": "typed artifact, e.g. ProductRef",
                    "source": "question | dialog_context | question_or_context",
                    "required": "boolean",
                }
            ],
            "relevant": "boolean",
            "reasoning": "short explanation",
        },
        "goal": {
            "business_goal": "same or refined business goal",
            "final_artifact_type": "UserAnswer",
            "expected_answer_type": "table | short_answer | answer",
            "required_artifacts": [
                {
                    "name": "artifact name",
                    "type": "artifact type",
                    "source": "question | dialog_context | skill",
                    "required": "boolean",
                    "constraints": [
                        {
                            "semantic_field": "semantic field role",
                            "operator": "equals | contains | starts_with | in_list",
                            "value": "semantic value",
                            "raw_user_text": "original phrase",
                        }
                    ],
                    "required_columns": [
                        "Business columns or dimensions that must be present in the result, e.g. Номенклатура, Склад, Контрагент"
                    ],
                }
            ],
        },
    }


def parse_decomposition_response(message: str, response: Dict[str, Any], registry: SkillRegistry) -> DecompositionResult:
    intent = parse_intent(message, response.get("intent"))
    goal_payload = response.get("goal")
    goal = parse_goal(goal_payload) if isinstance(goal_payload, dict) else None
    goal = repair_document_list_aggregate_goal(intent, goal)
    goal = complete_goal_from_skill_catalog(intent, goal, registry)
    return DecompositionResult(intent=intent, goal=goal)


def parse_intent(message: str, payload: Any) -> IntentResult:
    if not isinstance(payload, dict):
        return unknown_intent(message, "LLM response has no intent object.")
    raw_type = str(payload.get("intent_type") or IntentType.UNKNOWN.value)
    try:
        intent_type = IntentType(raw_type)
    except ValueError:
        intent_type = IntentType.UNKNOWN
    dependencies = []
    for item in payload.get("context_dependencies", []) or []:
        if isinstance(item, dict):
            dependencies.append(
                ContextDependency(
                    role=str(item.get("role") or ""),
                    artifact_type=str(item.get("artifact_type") or ""),
                    source=str(item.get("source") or ""),
                    required=bool(item.get("required", True)),
                )
            )
    return IntentResult(
        intent_type=intent_type,
        business_goal=str(payload.get("business_goal") or message),
        requires_1c_data=bool(payload.get("requires_1c_data", False)),
        expected_output=str(payload.get("expected_output") or "answer"),
        domain_terms=[str(item) for item in payload.get("domain_terms", []) or []],
        context_dependencies=dependencies,
        relevant=bool(payload.get("relevant", intent_type not in {IntentType.OUT_OF_SCOPE, IntentType.UNKNOWN})),
        reasoning=str(payload.get("reasoning") or ""),
    )


def parse_goal(payload: Dict[str, Any]) -> GoalDecomposition:
    requirements = []
    for item in payload.get("required_artifacts", []) or []:
        if not isinstance(item, dict):
            continue
        requirements.append(
            ArtifactRequirement(
                name=str(item.get("name") or item.get("type") or ""),
                type=str(item.get("type") or ""),
                source=str(item.get("source") or "skill"),
                required=bool(item.get("required", True)),
                constraints=parse_constraints(item.get("constraints")),
                required_columns=[str(column) for column in item.get("required_columns", []) or []],
            )
        )
    goal = GoalDecomposition(
        business_goal=str(payload.get("business_goal") or ""),
        final_artifact_type=str(payload.get("final_artifact_type") or "UserAnswer"),
        expected_answer_type=str(payload.get("expected_answer_type") or "answer"),
        required_artifacts=requirements,
    )
    return ensure_requested_detail_columns(goal)


def parse_constraints(payload: Any) -> List[SemanticFilter]:
    constraints = []
    for item in payload or []:
        if isinstance(item, dict):
            constraints.append(
                SemanticFilter(
                    semantic_field=str(item.get("semantic_field") or ""),
                    operator=str(item.get("operator") or "equals"),
                    value=item.get("value"),
                    raw_user_text=str(item.get("raw_user_text") or ""),
                )
            )
    return constraints


def ensure_requested_detail_columns(goal: GoalDecomposition) -> GoalDecomposition:
    requested = detail_columns_from_text(goal.business_goal)
    if not requested:
        return goal
    updated = []
    changed = False
    for requirement in goal.required_artifacts:
        if not requirement.type.endswith("Table"):
            updated.append(requirement)
            continue
        columns = merge_required_columns(requirement.required_columns, requested)
        changed = changed or columns != requirement.required_columns
        updated.append(
            ArtifactRequirement(
                name=requirement.name,
                type=requirement.type,
                source=requirement.source,
                required=requirement.required,
                constraints=list(requirement.constraints),
                required_columns=columns,
            )
        )
    if not changed:
        return goal
    return GoalDecomposition(
        business_goal=goal.business_goal,
        final_artifact_type=goal.final_artifact_type,
        expected_answer_type=goal.expected_answer_type,
        required_artifacts=updated,
    )


def detail_columns_from_text(text: str) -> List[str]:
    normalized = text.lower()
    columns = []
    if "детализа" in normalized and ("номенклат" in normalized or "товар" in normalized):
        columns.append("Номенклатура")
    if "детализа" in normalized and ("по склад" in normalized or "по мест" in normalized or "в разрезе склад" in normalized):
        columns.append("Склад")
    return columns


def merge_required_columns(existing: List[str], requested: List[str]) -> List[str]:
    result = list(existing)
    normalized = {item.strip().lower() for item in result}
    for column in requested:
        key = column.strip().lower()
        if key and key not in normalized:
            result.append(column)
            normalized.add(key)
    return result


def unknown_intent(message: str, reasoning: str) -> IntentResult:
    return IntentResult(
        intent_type=IntentType.UNKNOWN,
        business_goal=message,
        requires_1c_data=False,
        relevant=False,
        reasoning=reasoning,
    )


def available_artifact_types(registry: SkillRegistry) -> List[str]:
    type_system = TypeSystem()
    result = set(type_system.concrete_artifact_types())
    for skill in registry.all():
        if not skill_available_for_goal_decomposition(skill):
            continue
        for port in skill.outputs:
            if not type_system.is_abstract_artifact_type(port.type) and not type_system.is_technical_port_type(port.type):
                result.add(port.type)
    return sorted(result)


def skill_catalog(registry: SkillRegistry) -> List[Dict[str, Any]]:
    result = []
    for skill in registry.active():
        if not skill_available_for_goal_decomposition(skill):
            continue
        if skill.kind.value == "presentation":
            continue
        result.append(
            {
                "skill_id": skill.skill_id,
                "kind": skill.kind.value,
                "description": skill.description,
                "capabilities": list(skill.capabilities),
                "inputs": [item.to_dict() for item in skill.inputs],
                "outputs": [item.to_dict() for item in skill.outputs],
                "semantic_role": skill.semantic_role,
                "supported_filter_roles": list(skill.supported_filter_roles),
                "output_columns": list(skill.implementation.get("output_columns", []))
                if isinstance(skill.implementation.get("output_columns"), list)
                else [],
            }
        )
    return result


def complete_goal_from_skill_catalog(
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
    registry: SkillRegistry,
) -> Optional[GoalDecomposition]:
    if goal is None or not intent.requires_1c_data or goal.final_artifact_type != "UserAnswer":
        return goal
    if goal_has_unresolved_data_artifact(goal, intent, registry):
        return goal
    if goal_has_skill_data_artifact(goal, intent, registry):
        return goal

    best = best_data_skill_output(intent, goal, registry)
    if best is None:
        return goal
    output_name, output_type, score = best
    if score <= 0:
        return goal
    return GoalDecomposition(
        business_goal=goal.business_goal,
        final_artifact_type=goal.final_artifact_type,
        expected_answer_type=goal.expected_answer_type,
        required_artifacts=[
            *goal.required_artifacts,
            ArtifactRequirement(name=output_name, type=output_type, source="skill", required=True),
        ],
    )


def goal_has_skill_data_artifact(goal: GoalDecomposition, intent: IntentResult, registry: SkillRegistry) -> bool:
    context_types = {
        item.artifact_type
        for item in intent.context_dependencies
        if item.source in {"dialog_context", "question_or_context"}
    }
    data_output_types = {
        output.type
        for skill in registry.active()
        if skill_available_for_goal_decomposition(skill)
        if skill.kind.value == "data_acquisition" and skill.implementation_strategy != "context_artifact_lookup"
        for output in skill.outputs
    }
    for requirement in goal.required_artifacts:
        if requirement.source == "skill" and requirement.type not in context_types and requirement.type in data_output_types:
            return True
    return False


def goal_has_unresolved_data_artifact(goal: GoalDecomposition, intent: IntentResult, registry: SkillRegistry) -> bool:
    type_system = TypeSystem()
    context_types = {
        item.artifact_type
        for item in intent.context_dependencies
        if item.source in {"dialog_context", "question_or_context"}
    }
    data_output_types = {
        output.type
        for skill in registry.active()
        if skill_available_for_goal_decomposition(skill)
        if skill.kind.value == "data_acquisition" and skill.implementation_strategy != "context_artifact_lookup"
        for output in skill.outputs
    }
    for requirement in goal.required_artifacts:
        if requirement.type in context_types or requirement.type == "UserAnswer":
            continue
        if type_system.is_abstract_artifact_type(requirement.type):
            return True
        if type_system.is_assignable(requirement.type, "TypedTable") and requirement.type not in data_output_types:
            return True
    return False


def best_data_skill_output(
    intent: IntentResult,
    goal: GoalDecomposition,
    registry: SkillRegistry,
) -> Optional[tuple]:
    existing_types = {item.type for item in goal.required_artifacts}
    text_words = meaningful_words(" ".join([intent.business_goal, goal.business_goal, *intent.domain_terms]))
    scored = []
    for skill in registry.active():
        if not skill_available_for_goal_decomposition(skill):
            continue
        if skill.kind.value != "data_acquisition" or skill.implementation_strategy == "context_artifact_lookup":
            continue
        score = skill_text_score(skill.to_dict(), text_words)
        if score <= 0:
            continue
        for output in skill.outputs:
            if output.type not in existing_types:
                scored.append((score, skill.status.value, skill.skill_id, output.name, output.type))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[2], item[3]))
    return scored[0][3], scored[0][4], scored[0][0]


def skill_text_score(skill_data: Dict[str, Any], text_words: List[str]) -> int:
    skill_words = meaningful_words(
        " ".join(
            [
                str(skill_data.get("skill_id") or ""),
                str(skill_data.get("semantic_role") or ""),
                str(skill_data.get("description") or ""),
                " ".join(str(item) for item in skill_data.get("tags", []) or []),
            ]
        )
    )
    score = 0
    for word in text_words:
        if len(word) < 3:
            continue
        if any(words_match(word, skill_word) for skill_word in skill_words):
            score += 1
    return score


def skill_available_for_goal_decomposition(skill) -> bool:
    if skill.implementation_strategy != "learned_query":
        return True
    return skill.implementation.get("kind") != "fixed_query"
