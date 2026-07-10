from __future__ import annotations

import re
from typing import Iterable, List, Optional

from wiicon5.models import ArtifactRequirement, SemanticFilter, SkillContract, SkillKind
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.skills.semantic_contract import SemanticSkillContract, contract_from_goal, semantic_contract_compatibility


DOMAIN_SELECTOR_FIELDS = {"document_type", "document_kind", "object_type", "object_name", "entity_type"}

GENERIC_DOMAIN_WORDS = {
    "answer",
    "answers",
    "balance",
    "balances",
    "binding",
    "data",
    "discovery",
    "entity",
    "entities",
    "filter",
    "filters",
    "from",
    "get",
    "list",
    "measure",
    "object",
    "objects",
    "optional",
    "produce",
    "product",
    "products",
    "retrieve",
    "set",
    "table",
    "tables",
    "type",
    "using",
    "warehouse",
    "warehouses",
    "wiic",
    "wiicon",
    "агрегат",
    "вывести",
    "данные",
    "запрос",
    "информация",
    "количество",
    "найди",
    "найти",
    "остаток",
    "остатка",
    "остатки",
    "остатков",
    "ответ",
    "получи",
    "получить",
    "показать",
    "покажи",
    "список",
    "строки",
    "таблица",
    "таблицу",
}


def skill_domain_compatible(
    skill: SkillContract,
    requirement: ArtifactRequirement,
    goal: Optional[GoalDecomposition],
) -> bool:
    if skill.kind != SkillKind.DATA:
        return True
    if skill.implementation_strategy == "context_artifact_lookup":
        return True
    if skill.implementation_strategy == "learned_query":
        if goal is None:
            return False
        return semantic_contract_compatibility(
            contract_from_goal(None, goal),
            SemanticSkillContract.from_dict(skill.semantic_contract),
        ).compatible
    if _generic_document_list_request(skill, requirement):
        return True

    question_words = meaningful_question_words(requirement, goal)
    if not question_words:
        return True

    skill_words = meaningful_skill_words(skill)
    if not skill_words:
        return True

    return any(any(words_match(word, skill_word) for skill_word in skill_words) for word in question_words)


def constraint_selects_skill_domain(skill: SkillContract, constraint: SemanticFilter) -> bool:
    if constraint.semantic_field not in DOMAIN_SELECTOR_FIELDS:
        return False
    value_words = meaningful_words(" ".join([str(constraint.value or ""), constraint.raw_user_text]))
    if not value_words:
        return False
    skill_words = meaningful_skill_words(skill)
    if not skill_words:
        return False
    matches = 0
    for word in value_words:
        if any(words_match(word, candidate) for candidate in skill_words):
            matches += 1
    return matches / len(value_words) >= 0.5


def meaningful_question_words(requirement: ArtifactRequirement, goal: Optional[GoalDecomposition]) -> List[str]:
    parts: List[str] = []
    if goal is not None:
        parts.append(goal.business_goal)
    parts.append(requirement.name)
    for constraint in requirement.constraints:
        parts.extend([str(constraint.value or ""), constraint.raw_user_text])
    return meaningful_words(" ".join(parts))


def meaningful_skill_words(skill: SkillContract) -> List[str]:
    capabilities = [
        capability
        for capability in skill.capabilities
        if not capability.lower().startswith("produce:")
    ]
    text = " ".join(
        [
            skill.skill_id,
            skill.description,
            skill.semantic_role or "",
            " ".join(capabilities),
            " ".join(skill.tags),
        ]
    )
    return meaningful_words(text)


def meaningful_words(value: str) -> List[str]:
    return [word for word in normalized_words(value) if word not in GENERIC_DOMAIN_WORDS]


def normalized_words(value: str) -> List[str]:
    compact = re.sub(r"([a-zа-яё])([A-ZА-ЯЁ])", r"\1 \2", value)
    return [item for item in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", compact.lower()) if item and len(item) >= 3]


def words_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) >= 4 and len(right) >= 4 and (left in right or right in left):
        return True
    if len(left) >= 5 and len(right) >= 5 and left[:5] == right[:5]:
        return True
    return False


def text_matches_skill_domain(skill: SkillContract, values: Iterable[str]) -> bool:
    value_words = meaningful_words(" ".join(values))
    skill_words = meaningful_skill_words(skill)
    if not value_words or not skill_words:
        return False
    return any(any(words_match(word, skill_word) for skill_word in skill_words) for word in value_words)


def _generic_document_list_request(skill: SkillContract, requirement: ArtifactRequirement) -> bool:
    if skill.implementation_strategy != "semantic_document_list_query":
        return False
    return any(constraint.semantic_field in DOMAIN_SELECTOR_FIELDS for constraint in requirement.constraints)
