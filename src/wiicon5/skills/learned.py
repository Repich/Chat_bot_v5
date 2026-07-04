from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from wiicon5.intent.models import IntentResult
from wiicon5.models import SkillContract, SkillKind, SkillStatus
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query_synthesis import QuerySynthesisResult
from wiicon5.skills.registry import SkillRegistry


@dataclass(frozen=True)
class LearnedSkillWriteResult:
    skill: SkillContract
    path: Path
    created: bool
    evidence_path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill.skill_id,
            "path": str(self.path),
            "created": self.created,
            "status": self.skill.status.value,
            "evidence_path": str(self.evidence_path) if self.evidence_path else "",
            "output_types": [output.type for output in self.skill.outputs],
        }


class LearnedSkillStore:
    def __init__(self, *, skills_dir: Path, registry: SkillRegistry) -> None:
        self.skills_dir = skills_dir
        self.learned_dir = skills_dir / "learned"
        self.candidates_dir = self.learned_dir / "candidates"
        self.evidence_dir = self.learned_dir / "evidence"
        self.registry = registry

    def learn_from_synthesis(
        self,
        *,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        synthesis_result: QuerySynthesisResult,
        created_from_trace: str = "",
    ) -> Optional[LearnedSkillWriteResult]:
        if not synthesis_result.ok:
            return None
        final_query = synthesis_result.trace.get("final_query")
        if not isinstance(final_query, dict):
            return None
        query = str(final_query.get("query") or "")
        spec = learned_period_metric_spec(query=query, intent=intent, trace=synthesis_result.trace)
        if spec is None:
            return None
        spec = enrich_spec_with_lifecycle(
            spec,
            intent=intent,
            trace=synthesis_result.trace,
            created_from_trace=created_from_trace,
        )
        skill = skill_from_spec(spec, intent=intent, goal=goal)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        path = self.candidates_dir / f"{skill.skill_id}.json"
        created = not path.exists()
        path.write_text(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        evidence_path = self.write_evidence(skill, spec, synthesis_result.trace, created_from_trace)
        self.registry.add(skill)
        return LearnedSkillWriteResult(skill=skill, path=path, created=created, evidence_path=evidence_path)

    def write_evidence(
        self,
        skill: SkillContract,
        spec: Dict[str, Any],
        trace: Dict[str, Any],
        created_from_trace: str,
    ) -> Path:
        skill_evidence_dir = self.evidence_dir / skill.skill_id
        skill_evidence_dir.mkdir(parents=True, exist_ok=True)
        creation_path = skill_evidence_dir / "creation_trace.json"
        payload = {
            "skill_id": skill.skill_id,
            "created_from_trace": created_from_trace,
            "evidence": spec.get("evidence", {}),
            "metadata_dependency_contract": spec.get("metadata_dependency_contract", []),
            "final_query": (trace.get("final_query") or {}),
        }
        creation_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        successful_path = skill_evidence_dir / "successful_runs.jsonl"
        with successful_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return creation_path


def learned_period_metric_spec(*, query: str, intent: IntentResult, trace: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    source_match = re.search(
        r"\bИЗ\s+(?P<source>[A-Za-zА-Яа-яЁё0-9_.]+)\s+КАК\s+(?P<alias>[A-Za-zА-Яа-яЁё0-9_]+)",
        query,
        flags=re.IGNORECASE,
    )
    if source_match is None:
        return None
    source = source_match.group("source")
    alias = source_match.group("alias")
    if "Регистр" not in source:
        return None
    period_field = first_period_field(query, alias)
    if not period_field:
        return None
    metrics = select_metrics(query, alias)
    if not metrics:
        return None
    spec = {
        "kind": "period_metric_aggregate",
        "source": source,
        "alias": alias,
        "period_field": period_field,
        "metrics": metrics,
        "limit": int((trace.get("final_query") or {}).get("limit") or 100),
        "metadata_dependencies": [source],
        "metric_terms": metric_terms(intent),
    }
    if is_raw_accumulation_register_source(source) and re.search(rf"\b{re.escape(alias)}\.Активность\b", query):
        spec["activity_filter"] = True
        spec["activity_field"] = "Активность"
    return spec


def enrich_spec_with_lifecycle(
    spec: Dict[str, Any],
    *,
    intent: IntentResult,
    trace: Dict[str, Any],
    created_from_trace: str,
) -> Dict[str, Any]:
    result = dict(spec)
    final_query = dict(trace.get("final_query") or {})
    query = str(final_query.get("query") or "")
    result["metadata_dependency_contract"] = metadata_dependency_contract(result, query=query)
    result["evidence"] = {
        "created_from_trace": created_from_trace,
        "question": intent.business_goal,
        "final_query_hash": hash_payload(final_query),
        "result_sample_hash": hash_payload(trace.get("successful_steps", [])),
        "sufficiency_review": latest_sufficiency_review(trace),
        "human_confirmed": False,
        "successful_runs": 1,
    }
    return result


def metadata_dependency_contract(spec: Dict[str, Any], *, query: str) -> List[Dict[str, Any]]:
    source = str(spec.get("source") or "")
    if not source:
        return []
    alias = str(spec.get("alias") or "Источник")
    period_field = str(spec.get("period_field") or "")
    metrics = spec.get("metrics") if isinstance(spec.get("metrics"), list) else []
    required_fields = {field: "unknown" for field in source_field_names(query, alias)}
    if period_field:
        required_fields.setdefault(period_field, "unknown")
    field_roles: Dict[str, str] = {}
    if period_field:
        field_roles["period"] = period_field
    for metric in metrics:
        if isinstance(metric, dict) and metric.get("label"):
            label = str(metric.get("label"))
            fields = source_field_names(str(metric.get("expression") or ""), alias)
            if fields:
                field_roles[label] = ", ".join(fields)
    if spec.get("activity_filter"):
        activity_field = str(spec.get("activity_field") or "Активность")
        required_fields.setdefault(activity_field, "unknown")
        field_roles["activity"] = activity_field
    return [
        {
            "object": source,
            "required_fields": required_fields,
            "virtual_table": virtual_table_name(source),
            "field_roles": field_roles,
        }
    ]


def source_field_names(text: str, alias: str) -> List[str]:
    fields: List[str] = []
    for match in re.finditer(rf"\b{re.escape(alias)}\.([A-Za-zА-Яа-яЁё0-9_]+)\b", text):
        field = match.group(1)
        if field not in fields:
            fields.append(field)
    return sorted(fields)


def virtual_table_name(source: str) -> Optional[str]:
    match = re.search(r"\.(ОстаткиИОбороты|Остатки|Обороты)\s*\(", source)
    return match.group(1) if match else None


def latest_sufficiency_review(trace: Dict[str, Any]) -> Dict[str, Any]:
    attempts = trace.get("attempts")
    if not isinstance(attempts, list):
        return {}
    for attempt in reversed(attempts):
        if isinstance(attempt, dict) and isinstance(attempt.get("result_sufficiency"), dict):
            return dict(attempt["result_sufficiency"])
    return {}


def hash_payload(payload: Any) -> str:
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def fixed_query_spec(*, final_query: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "fixed_query",
        "query": str(final_query.get("query") or ""),
        "params": dict(final_query.get("params") or {}),
        "limit": int(final_query.get("limit") or 100),
        "metadata_dependencies": [
            item.get("full_name")
            for item in trace.get("metadata_objects", [])
            if isinstance(item, dict) and item.get("full_name")
        ][:5],
    }


def skill_from_spec(
    spec: Dict[str, Any],
    *,
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
) -> SkillContract:
    output_type = output_type_for_intent(intent, spec)
    skill_id = skill_id_for_spec(output_type, spec)
    domain_terms = metric_terms(intent)
    description_terms = ", ".join(domain_terms[:6]) or intent.business_goal
    return SkillContract.from_dict(
        {
            "skill_id": skill_id,
            "version": "0.1.0",
            "kind": SkillKind.DATA.value,
            "status": SkillStatus.CANDIDATE.value,
            "description": f"Learned query skill for {description_terms}.",
            "capabilities": [
                "learned_query",
                "retrieve_metrics",
                *domain_terms,
                f"produce:{output_type}",
            ],
            "inputs": [
                {
                    "name": "filters",
                    "type": "SemanticFilterList",
                    "required": False,
                    "description": "Semantic filters such as year or period granularity.",
                },
                {
                    "name": "limit",
                    "type": "Integer",
                    "required": False,
                    "description": "Maximum rows to return",
                    "default": 100,
                },
            ],
            "outputs": [
                {
                    "name": "table",
                    "type": output_type,
                    "required": True,
                    "description": "Learned metric table",
                }
            ],
            "tags": ["learned", "metrics", *domain_terms],
            "semantic_role": semantic_role_for_output(output_type),
            "supported_filter_roles": ["year", "period", "period_granularity", "group_by", "metric"],
            "implementation_strategy": "learned_query",
            "implementation": spec,
        }
    )


def output_type_for_intent(intent: IntentResult, spec: Dict[str, Any]) -> str:
    words = " ".join([intent.business_goal, *intent.domain_terms, *spec.get("metric_terms", [])]).lower()
    if any(marker in words for marker in ["выруч", "приб", "profit", "revenue"]):
        return "FinancialMetricsTable"
    return "LearnedMetricsTable"


def semantic_role_for_output(output_type: str) -> str:
    if output_type == "FinancialMetricsTable":
        return "financial_metrics"
    return "learned_metrics"


def skill_id_for_spec(output_type: str, spec: Dict[str, Any]) -> str:
    if output_type == "FinancialMetricsTable":
        return "learned_financial_metrics"
    digest = hashlib.sha1(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    return f"learned_query_{digest}"


def first_period_field(query: str, alias: str) -> str:
    pattern = re.compile(rf"\b{re.escape(alias)}\.([A-Za-zА-Яа-яЁё0-9_]*Период[A-Za-zА-Яа-яЁё0-9_]*)\b")
    match = pattern.search(query)
    return match.group(1) if match else ""


def is_raw_accumulation_register_source(source: str) -> bool:
    if not source.startswith("РегистрНакопления."):
        return False
    return not re.search(r"\.(?:ОстаткиИОбороты|Остатки|Обороты)\s*\(", source)


def select_metrics(query: str, alias: str) -> List[Dict[str, str]]:
    match = re.search(r"\bВЫБРАТЬ\s+(?P<select>.*?)\s+\bИЗ\b", query, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return []
    metrics: List[Dict[str, str]] = []
    for expression in split_select_expressions(match.group("select")):
        alias_match = re.search(r"(?P<expr>.+?)\s+КАК\s+(?P<label>[A-Za-zА-Яа-яЁё0-9_]+)\s*$", expression, flags=re.IGNORECASE)
        if alias_match is None:
            continue
        label = alias_match.group("label")
        expr = alias_match.group("expr").strip()
        if label.lower() in {"год", "period", "период"}:
            continue
        if alias + "." not in expr:
            continue
        metrics.append({"label": label, "expression": expr})
    return metrics


def split_select_expressions(select_text: str) -> List[str]:
    result: List[str] = []
    current: List[str] = []
    depth = 0
    for char in select_text:
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                result.append(item)
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        result.append(tail)
    return result


def metric_terms(intent: IntentResult) -> List[str]:
    terms: List[str] = []
    for value in [intent.business_goal, *intent.domain_terms]:
        for word in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", value.lower()):
            if len(word) >= 4 and word not in terms:
                terms.append(word)
    return terms[:12]
