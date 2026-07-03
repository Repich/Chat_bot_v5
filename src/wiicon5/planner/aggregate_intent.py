from __future__ import annotations

from typing import Iterable, Optional

from wiicon5.intent.models import IntentResult
from wiicon5.models import ArtifactRequirement
from wiicon5.planner.goal import GoalDecomposition


AGGREGATE_TABLE_TYPE = "AggregateTable"
DOCUMENT_LIST_TABLE_TYPE = "DocumentListTable"

RANKING_MARKERS = (
    "сам",
    "топ",
    "top",
    "наибольш",
    "наименьш",
    "максим",
    "миним",
    "больше всего",
    "меньше всего",
    "популяр",
    "продающ",
    "лидер",
)

AGGREGATE_MARKERS = (
    "сколько",
    "количество",
    "сумма",
    "итого",
    "остаток",
    "остатки",
    "выруч",
    "прибыл",
    "задолж",
    "оборот",
    "расход",
    "продаж",
    "продан",
    "по дням",
    "по годам",
    "по месяцам",
    "по неделям",
)


def document_list_misused_for_aggregation(
    goal: GoalDecomposition,
    intent: Optional[IntentResult] = None,
) -> bool:
    if not any(requirement.type == DOCUMENT_LIST_TABLE_TYPE for requirement in goal.required_artifacts):
        return False
    return text_requests_aggregation(goal_text(goal, intent))


def text_requests_aggregation(text: str) -> bool:
    lowered = text.lower()
    return contains_any(lowered, RANKING_MARKERS) or contains_any(lowered, AGGREGATE_MARKERS)


def repair_document_list_aggregate_goal(
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
) -> Optional[GoalDecomposition]:
    if goal is None or not document_list_misused_for_aggregation(goal, intent):
        return goal

    repaired_requirements = []
    replaced = False
    for requirement in goal.required_artifacts:
        if requirement.type != DOCUMENT_LIST_TABLE_TYPE:
            repaired_requirements.append(requirement)
            continue
        repaired_requirements.append(
            ArtifactRequirement(
                name=requirement.name or "aggregate_result",
                type=AGGREGATE_TABLE_TYPE,
                source=requirement.source,
                required=requirement.required,
                constraints=requirement.constraints,
            )
        )
        replaced = True

    if not replaced:
        return goal
    return GoalDecomposition(
        business_goal=goal.business_goal,
        final_artifact_type=goal.final_artifact_type,
        expected_answer_type=goal.expected_answer_type,
        required_artifacts=repaired_requirements,
    )


def goal_text(goal: GoalDecomposition, intent: Optional[IntentResult] = None) -> str:
    parts = [goal.business_goal]
    if intent is not None:
        parts.extend([intent.business_goal, *intent.domain_terms, intent.reasoning])
    for requirement in goal.required_artifacts:
        parts.append(requirement.name)
        for constraint in requirement.constraints:
            parts.extend([str(constraint.value or ""), constraint.raw_user_text])
    return " ".join(parts)


def contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker in text for marker in markers)
