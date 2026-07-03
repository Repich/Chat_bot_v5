from __future__ import annotations

from typing import Dict, List, Set

from wiicon5.models import SkillPlan, ValidationIssue, ValidationResult
from wiicon5.planner.placeholders import is_unresolved_placeholder_value
from wiicon5.skills.registry import SkillRegistry


class SkillPlanValidator:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def validate(self, plan: SkillPlan) -> ValidationResult:
        issues: List[ValidationIssue] = []
        node_ids = {node.invocation_id for node in plan.nodes}
        if len(node_ids) != len(plan.nodes):
            issues.append(ValidationIssue("duplicate_node", "Skill plan contains duplicate invocation ids."))
        for node in plan.nodes:
            skill = self.registry.get(node.skill_id)
            if skill is None:
                issues.append(ValidationIssue("unknown_skill", "Skill is not registered.", node.invocation_id))
                continue
            for input_port in skill.inputs:
                if input_port.required and input_port.default is None and input_port.name not in node.inputs:
                    issues.append(
                        ValidationIssue(
                            "missing_required_input",
                            "Required skill input is not bound.",
                            f"{node.invocation_id}.{input_port.name}",
                        )
                    )
                if input_port.name in node.inputs and is_unresolved_placeholder_value(node.inputs[input_port.name]):
                    issues.append(
                        ValidationIssue(
                            "unresolved_placeholder_input",
                            "Skill input contains an unresolved placeholder instead of a real value or dependency.",
                            f"{node.invocation_id}.{input_port.name}",
                        )
                    )
        for edge in plan.edges:
            if len(edge) != 2:
                issues.append(ValidationIssue("invalid_edge", "Plan edge must contain source and target."))
                continue
            source_node = edge[0].split(".", 1)[0]
            target_node = edge[1].split(".", 1)[0]
            if source_node not in node_ids:
                issues.append(ValidationIssue("unknown_edge_source", "Edge source node is unknown.", edge[0]))
            if target_node not in node_ids:
                issues.append(ValidationIssue("unknown_edge_target", "Edge target node is unknown.", edge[1]))
        if _has_cycle({node.invocation_id: node.depends_on for node in plan.nodes}):
            issues.append(ValidationIssue("cycle", "Skill plan DAG contains a cycle."))
        return ValidationResult(ok=not issues, issues=issues)


def _has_cycle(dependencies: Dict[str, List[str]]) -> bool:
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dependency in dependencies.get(node, []):
            if visit(dependency):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in dependencies)
