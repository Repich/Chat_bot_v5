from __future__ import annotations

from typing import Optional

from wiicon5.intent.models import IntentResult
from wiicon5.models import ArtifactRequirement
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.skills.semantic_contract import SemanticSkillContract


AGGREGATE_TABLE_TYPE = "AggregateTable"
DOCUMENT_LIST_TABLE_TYPE = "DocumentListTable"

def document_list_misused_for_aggregation(
    goal: GoalDecomposition,
    intent: Optional[IntentResult] = None,
) -> bool:
    if not any(requirement.type == DOCUMENT_LIST_TABLE_TYPE for requirement in goal.required_artifacts):
        return False
    contract = SemanticSkillContract.from_dict(goal.semantic_contract)
    if not contract.current:
        return False
    return contract.operation in {"aggregate", "rank", "balance"} or any(
        measure.aggregation for measure in contract.measures
    )


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
                required_columns=list(requirement.required_columns),
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
        semantic_contract=dict(goal.semantic_contract),
    )
