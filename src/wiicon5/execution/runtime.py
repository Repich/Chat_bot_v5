from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.artifacts import Artifact, TypedTable
from wiicon5.models import SkillContract, SkillInvocation, SkillKind, SkillPlan
from wiicon5.presentation.answer_formatter import format_cell, format_user_answer, rows_effectively_empty
from wiicon5.skills.registry import SkillRegistry


REF_RE = re.compile(r"^\$\{([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}$")


@dataclass(frozen=True)
class SkillRunResult:
    ok: bool
    skill_id: str
    artifacts: List[Artifact] = field(default_factory=list)
    error: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillPlanExecutionResult:
    ok: bool
    artifacts: Dict[str, Artifact] = field(default_factory=dict)
    final_artifact: Optional[Artifact] = None
    error: str = ""
    failed_invocation_id: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)


class SkillRunner(ABC):
    @abstractmethod
    def run(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> SkillRunResult:
        raise NotImplementedError


class SkillPlanExecutor:
    def __init__(self, registry: SkillRegistry, runners: Mapping[str, SkillRunner]) -> None:
        self.registry = registry
        self.runners = dict(runners)

    def execute(self, plan: SkillPlan, context: ConversationContext) -> SkillPlanExecutionResult:
        frame: Dict[str, Artifact] = {}
        invocation_traces: List[Dict[str, Any]] = []
        for invocation in plan.nodes:
            skill = self.registry.get(invocation.skill_id)
            if skill is None:
                return SkillPlanExecutionResult(
                    ok=False,
                    error=f"Unknown skill: {invocation.skill_id}",
                    failed_invocation_id=invocation.invocation_id,
                    trace={"invocations": invocation_traces},
                )
            runner = self._runner_for(skill)
            if runner is None:
                return SkillPlanExecutionResult(
                    ok=False,
                    error=f"No runner for skill strategy: {skill.implementation_strategy or skill.kind.value}",
                    failed_invocation_id=invocation.invocation_id,
                    trace={"invocations": invocation_traces},
                )
            inputs = resolve_invocation_inputs(invocation, frame)
            result = runner.run(skill, inputs, context)
            invocation_traces.append(
                {
                    "invocation_id": invocation.invocation_id,
                    "skill_id": skill.skill_id,
                    "ok": result.ok,
                    "error": result.error,
                    "inputs": inputs,
                    "artifacts": [artifact.to_dict() for artifact in result.artifacts],
                    "trace": result.trace,
                }
            )
            if not result.ok:
                return SkillPlanExecutionResult(
                    ok=False,
                    artifacts=dict(frame),
                    error=result.error,
                    failed_invocation_id=invocation.invocation_id,
                    trace={"invocations": invocation_traces},
                )
            for artifact in result.artifacts:
                frame[f"{invocation.invocation_id}.{artifact.name}"] = artifact
                context.add_artifact(artifact)

        final_artifact = _last_artifact(frame)
        return SkillPlanExecutionResult(
            ok=True,
            artifacts=dict(frame),
            final_artifact=final_artifact,
            trace={"invocations": invocation_traces},
        )

    def _runner_for(self, skill: SkillContract) -> Optional[SkillRunner]:
        if skill.implementation_strategy in self.runners:
            return self.runners[skill.implementation_strategy]
        if skill.kind.value in self.runners:
            return self.runners[skill.kind.value]
        if skill.kind == SkillKind.PRESENTATION and "presentation" in self.runners:
            return self.runners["presentation"]
        return None


class ContextArtifactRunner(SkillRunner):
    def run(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> SkillRunResult:
        artifacts: List[Artifact] = []
        for output in skill.outputs:
            artifact = context.latest_artifact(output.type)
            if artifact is None and skill.semantic_role:
                entity = context.latest_entity(skill.semantic_role)
                if entity is not None and entity.artifact_type == output.type:
                    artifact = Artifact(
                        name=output.name,
                        type=output.type,
                        value=entity.value,
                        provenance=[entity.source],
                    )
            if artifact is None:
                return SkillRunResult(
                    ok=False,
                    skill_id=skill.skill_id,
                    error=f"Missing context artifact: {output.type}",
                    trace={"missing_artifact_type": output.type},
                )
            artifacts.append(
                Artifact(
                    name=output.name,
                    type=output.type,
                    value=artifact.value,
                    provenance=list(artifact.provenance) + [skill.skill_id],
                )
            )
        return SkillRunResult(ok=True, skill_id=skill.skill_id, artifacts=artifacts)


class TableAnswerRunner(SkillRunner):
    def run(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> SkillRunResult:
        table = inputs.get("table")
        if isinstance(table, TypedTable):
            rows = table.rows
            columns = table.columns
        elif isinstance(table, dict):
            rows = list(table.get("rows", []))
            columns = list(table.get("columns", []))
        else:
            return SkillRunResult(
                ok=False,
                skill_id=skill.skill_id,
                error="Presentation input 'table' must be a TypedTable or table dict.",
            )
        if not rows or rows_effectively_empty(rows):
            answer = "Данных не найдено."
        else:
            answer = format_user_answer(question=latest_user_question(context), columns=columns, rows=rows)
        return SkillRunResult(
            ok=True,
            skill_id=skill.skill_id,
            artifacts=[
                Artifact(
                    name="answer",
                    type="UserAnswer",
                    value=answer,
                    provenance=[skill.skill_id],
                )
            ],
        )


class EntityListAnswerRunner(SkillRunner):
    def run(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> SkillRunResult:
        items = inputs.get("items")
        if not isinstance(items, list):
            return SkillRunResult(
                ok=False,
                skill_id=skill.skill_id,
                error="Presentation input 'items' must be a list.",
            )
        if not items:
            answer = "Данных не найдено."
        else:
            rows = [item if isinstance(item, dict) else {"Значение": item} for item in items]
            answer = format_user_answer(question=latest_user_question(context), columns=_columns_from_entity_rows(rows), rows=rows)
        return SkillRunResult(
            ok=True,
            skill_id=skill.skill_id,
            artifacts=[
                Artifact(
                    name="answer",
                    type="UserAnswer",
                    value=answer,
                    provenance=[skill.skill_id],
                )
            ],
        )


class StaticSkillRunner(SkillRunner):
    def __init__(self, artifacts_by_skill_id: Mapping[str, List[Artifact]]) -> None:
        self.artifacts_by_skill_id = {key: list(value) for key, value in artifacts_by_skill_id.items()}
        self.calls: List[Dict[str, Any]] = []

    def run(self, skill: SkillContract, inputs: Dict[str, Any], context: ConversationContext) -> SkillRunResult:
        self.calls.append({"skill_id": skill.skill_id, "inputs": inputs})
        if skill.skill_id not in self.artifacts_by_skill_id:
            return SkillRunResult(ok=False, skill_id=skill.skill_id, error=f"No scripted result for {skill.skill_id}")
        return SkillRunResult(ok=True, skill_id=skill.skill_id, artifacts=list(self.artifacts_by_skill_id[skill.skill_id]))


def default_runners() -> Dict[str, SkillRunner]:
    return {
        "context_artifact_lookup": ContextArtifactRunner(),
        "deterministic_table_renderer": TableAnswerRunner(),
        "deterministic_entity_list_renderer": EntityListAnswerRunner(),
    }


def resolve_invocation_inputs(invocation: SkillInvocation, frame: Mapping[str, Artifact]) -> Dict[str, Any]:
    return {key: resolve_value(value, frame) for key, value in invocation.inputs.items()}


def resolve_value(value: Any, frame: Mapping[str, Artifact]) -> Any:
    if isinstance(value, str):
        match = REF_RE.match(value)
        if match:
            artifact_key = f"{match.group(1)}.{match.group(2)}"
            artifact = frame.get(artifact_key)
            return artifact.value if artifact is not None else None
    if isinstance(value, list):
        return [resolve_value(item, frame) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item, frame) for key, item in value.items()}
    return value


def _last_artifact(frame: Mapping[str, Artifact]) -> Optional[Artifact]:
    if not frame:
        return None
    return next(reversed(frame.values()))


def _columns_from_entity_rows(rows: List[Dict[str, Any]]) -> List[str]:
    preferred = ["Наименование", "name", "Представление", "presentation", "Код", "code"]
    existing = []
    for column in preferred:
        if any(column in row for row in rows):
            existing.append(column)
    if not existing:
        for column in ["Ссылка", "ref"]:
            if any(column in row for row in rows):
                existing.append(column)
    for row in rows:
        for column in row:
            if column not in existing and column not in {"Ссылка", "ref"}:
                existing.append(column)
    return existing


def latest_user_question(context: ConversationContext) -> str:
    for message in reversed(context.messages):
        if message.role == "user":
            return message.content
    return ""
