from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from wiicon5.conversation.context import ConversationContext
from wiicon5.execution.runtime import SkillPlanExecutionResult, SkillRunResult
from wiicon5.intent.models import IntentResult
from wiicon5.models import SkillContract, SkillKind, SkillPlan, SkillStatus
from wiicon5.planner.goal import GoalDecomposition
from wiicon5.query.parameterized_lookup import constraints_from_goal_payload, parameterized_lookup_spec_from_query
from wiicon5.query_synthesis import QuerySynthesisResult
from wiicon5.skills.learning_gate import LearningGateResult, evaluate_learning_gate
from wiicon5.skills.query_template_learning import semantic_query_template_spec, skill_from_semantic_template
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
    def __init__(self, *, skills_dir: Path, registry: SkillRegistry, auto_activate: bool = True) -> None:
        self.skills_dir = skills_dir
        self.learned_dir = skills_dir / "learned"
        self.active_dir = self.learned_dir / ("active" if auto_activate else "inactive")
        self.evidence_dir = self.learned_dir / "evidence"
        self.registry = registry
        self.auto_activate = auto_activate
        self.last_gate_result: Optional[LearningGateResult] = None

    def learn_from_synthesis(
        self,
        *,
        intent: IntentResult,
        goal: Optional[GoalDecomposition],
        synthesis_result: QuerySynthesisResult,
        created_from_trace: str = "",
        config_fingerprint: str = "",
    ) -> Optional[LearnedSkillWriteResult]:
        if not synthesis_result.ok:
            self.last_gate_result = None
            return None
        final_query = synthesis_result.trace.get("final_query")
        if not isinstance(final_query, dict):
            self.last_gate_result = None
            return None
        query = str(final_query.get("query") or "")
        spec = semantic_query_template_spec(
            query=query,
            params=dict(final_query.get("params") or {}),
            limit=int(final_query.get("limit") or 100),
            intent=intent,
            goal=goal,
            trace=synthesis_result.trace,
        )
        if spec is None:
            self.last_gate_result = None
            return None
        gate = evaluate_learning_gate(
            intent=intent,
            goal=goal,
            synthesis_result=synthesis_result,
            spec=spec,
            config_fingerprint=config_fingerprint,
        )
        self.last_gate_result = gate
        if not gate.ok:
            return None
        spec["learning_validation"] = gate.to_dict()
        spec = enrich_spec_with_lifecycle(
            spec,
            intent=intent,
            trace=synthesis_result.trace,
            created_from_trace=created_from_trace,
            config_fingerprint=config_fingerprint,
            auto_activate=self.auto_activate,
        )
        skill = skill_from_semantic_template(spec, intent=intent, goal=goal)
        self.active_dir.mkdir(parents=True, exist_ok=True)
        path = self.active_dir / f"{skill.skill_id}.json"
        created = not path.exists()
        if not created:
            skill = preserve_existing_runtime_health(skill, path)
        path.write_text(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        evidence_path = self.write_evidence(skill, spec, synthesis_result.trace, created_from_trace)
        if self.auto_activate:
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
    if not period_metric_shape_can_be_generalized(query, alias=alias, period_field=period_field):
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


def learned_parameterized_lookup_spec(
    *,
    query: str,
    final_query: Dict[str, Any],
    goal: Optional[GoalDecomposition],
    trace: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    params = dict(final_query.get("params") or {}) if isinstance(final_query.get("params"), dict) else {}
    spec = parameterized_lookup_spec_from_query(
        query=query,
        params=params,
        constraints=constraints_from_goal_payload(goal),
        limit=int(final_query.get("limit") or 100),
        metadata_dependencies=query_sources_from_query(query) or metadata_dependencies_from_trace(trace),
    )
    if spec is None:
        return None
    spec["output_columns"] = output_columns_from_trace(trace) or output_columns_from_query(query)
    return spec


def enrich_spec_with_lifecycle(
    spec: Dict[str, Any],
    *,
    intent: IntentResult,
    trace: Dict[str, Any],
    created_from_trace: str,
    config_fingerprint: str,
    auto_activate: bool = True,
) -> Dict[str, Any]:
    result = dict(spec)
    final_query = dict(trace.get("final_query") or {})
    query = str(final_query.get("query") or "")
    result.setdefault("metadata_dependency_contract", metadata_dependency_contract(result, query=query))
    result["evidence"] = {
        "created_from_trace": created_from_trace,
        "question": intent.business_goal,
        "final_query_hash": hash_payload(final_query),
        "result_sample_hash": hash_payload(trace.get("successful_steps", [])),
        "sufficiency_review": compact_sufficiency_review(latest_sufficiency_review(trace)),
        "human_confirmed": False,
        "successful_runs": 1,
        "created_by": "agent",
        "verification_mode": "runtime_auto",
        "experiment": "auto_learning_v1",
    }
    result["activation_mode"] = "auto_active" if auto_activate else "auto_inactive"
    result["human_confirmed"] = False
    result["verification_mode"] = "runtime_auto"
    result["created_by"] = "agent"
    result["experiment"] = "auto_learning_v1"
    result["runtime_health"] = default_runtime_health()
    if config_fingerprint:
        result["config_fingerprint"] = config_fingerprint
    return result


class LearnedSkillRuntimeHealthStore:
    def __init__(self, *, skills_dir: Path, registry: SkillRegistry, failure_threshold: int = 3) -> None:
        self.skills_dir = skills_dir
        self.learned_dir = skills_dir / "learned"
        self.active_dir = self.learned_dir / "active"
        self.evidence_dir = self.learned_dir / "evidence"
        self.registry = registry
        self.failure_threshold = max(1, int(failure_threshold or 3))

    def record(
        self,
        skill: SkillContract,
        result: SkillRunResult,
        context: ConversationContext,
        *,
        invocation_id: str = "",
        inputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        failed = learned_result_failed(result)
        self.record_outcome(
            skill=skill,
            context=context,
            accepted=not failed,
            error=learned_result_error(result),
            invocation_id=invocation_id,
            inputs=inputs or {},
        )

    def record_plan_outcome(
        self,
        *,
        plan: SkillPlan,
        execution_result: SkillPlanExecutionResult,
        context: ConversationContext,
        accepted: bool,
        error: str = "",
    ) -> None:
        traces = {
            str(item.get("invocation_id") or ""): item
            for item in execution_result.trace.get("invocations", []) or []
            if isinstance(item, dict)
        }
        for invocation in plan.nodes:
            skill = self.registry.get(invocation.skill_id)
            if skill is None or skill.implementation_strategy != "learned_query":
                continue
            if invocation.invocation_id not in traces:
                continue
            invocation_trace = traces.get(invocation.invocation_id, {})
            invocation_ok = bool(invocation_trace.get("ok", execution_result.ok))
            if not execution_result.ok and invocation.invocation_id != execution_result.failed_invocation_id:
                continue
            invocation_error = str(invocation_trace.get("error") or error)
            self.record_outcome(
                skill=skill,
                context=context,
                accepted=accepted and invocation_ok,
                error="" if accepted and invocation_ok else invocation_error or error or "semantic_result_rejected",
                invocation_id=invocation.invocation_id,
                inputs=dict(invocation_trace.get("inputs") or invocation.inputs),
            )

    def record_outcome(
        self,
        *,
        skill: SkillContract,
        context: ConversationContext,
        accepted: bool,
        error: str = "",
        invocation_id: str = "",
        inputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        if skill.implementation_strategy != "learned_query":
            return
        skill_path = self.active_dir / f"{skill.skill_id}.json"
        if not skill_path.exists():
            return
        health = dict(skill.implementation.get("runtime_health") or default_runtime_health())
        now = utc_iso()
        health["reuse_count"] = int(health.get("reuse_count") or 0) + 1
        health["last_used_at"] = now
        if not accepted:
            health["failure_count"] = int(health.get("failure_count") or 0) + 1
            health["consecutive_failures"] = int(health.get("consecutive_failures") or 0) + 1
            health["last_error"] = error or "semantic_result_rejected"
            health["last_failed_at"] = now
        else:
            health["success_count"] = int(health.get("success_count") or 0) + 1
            health["consecutive_failures"] = 0
            health["last_error"] = ""
        if int(health.get("consecutive_failures") or 0) >= self.failure_threshold:
            health["auto_blocked"] = True
            health["auto_blocked_at"] = now

        skill.implementation["runtime_health"] = health
        self._patch_skill_file(skill_path, health)
        self._append_reuse_evidence(
            skill=skill,
            health=health,
            result=None,
            context=context,
            invocation_id=invocation_id,
            inputs=inputs or {},
            failed=not accepted,
            error=error,
        )

    def _patch_skill_file(self, path: Path, health: Dict[str, Any]) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        implementation = data.setdefault("implementation", {})
        implementation["runtime_health"] = health
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _append_reuse_evidence(
        self,
        *,
        skill: SkillContract,
        health: Dict[str, Any],
        result: Optional[SkillRunResult],
        context: ConversationContext,
        invocation_id: str,
        inputs: Dict[str, Any],
        failed: bool,
        error: str = "",
    ) -> None:
        evidence_dir = self.evidence_dir / skill.skill_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": utc_iso(),
            "skill_id": skill.skill_id,
            "invocation_id": invocation_id,
            "question": latest_user_question(context),
            "ok": (result.ok if result is not None else True) and not failed,
            "failed": failed,
            "error": error or (learned_result_error(result) if result is not None else ""),
            "inputs": inputs,
            "runtime_health": health,
        }
        with (evidence_dir / "reuse_runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def default_runtime_health() -> Dict[str, Any]:
    return {
        "reuse_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "consecutive_failures": 0,
        "last_used_at": "",
        "last_failed_at": "",
        "last_error": "",
        "auto_blocked": False,
        "auto_blocked_at": "",
    }


def preserve_existing_runtime_health(skill: SkillContract, path: Path) -> SkillContract:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return skill
    implementation = existing.get("implementation") if isinstance(existing.get("implementation"), dict) else {}
    health = implementation.get("runtime_health")
    if isinstance(health, dict):
        skill.implementation["runtime_health"] = dict(health)
    return skill


def learned_result_failed(result: SkillRunResult) -> bool:
    if not result.ok:
        return True
    for artifact in result.artifacts:
        value = artifact.value
        if isinstance(value, dict) and isinstance(value.get("rows"), list) and not value.get("rows"):
            return True
        if isinstance(value, list) and not value:
            return True
    return False


def learned_result_error(result: SkillRunResult) -> str:
    if result.error:
        return result.error
    if learned_result_failed(result):
        return "empty_result"
    return ""


def latest_user_question(context: ConversationContext) -> str:
    for message in reversed(context.messages):
        if message.role == "user":
            return message.content
    return ""


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def auto_learning_report(skills_dir: Path) -> Dict[str, Any]:
    learned_dir = skills_dir / "learned"
    active_dir = learned_dir / "active"
    inactive_dir = learned_dir / "inactive"
    skills = []
    for root in [active_dir, inactive_dir]:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not data.get("skill_id"):
                    continue
            except (OSError, json.JSONDecodeError):
                continue
            implementation = data.get("implementation") if isinstance(data.get("implementation"), dict) else {}
            evidence = implementation.get("evidence") if isinstance(implementation.get("evidence"), dict) else {}
            health = implementation.get("runtime_health") if isinstance(implementation.get("runtime_health"), dict) else default_runtime_health()
            skills.append(
                {
                    "skill_id": data.get("skill_id"),
                    "status": data.get("status", ""),
                    "path": str(path),
                    "active": root == active_dir,
                    "kind": implementation.get("kind", ""),
                    "activation_mode": implementation.get("activation_mode", ""),
                    "human_confirmed": bool(implementation.get("human_confirmed") or evidence.get("human_confirmed")),
                    "created_by": implementation.get("created_by", ""),
                    "created_from_trace": evidence.get("created_from_trace", ""),
                    "created_from_question": evidence.get("question", ""),
                    "config_fingerprint": implementation.get("config_fingerprint", ""),
                    "runtime_health": dict(health),
                    "reused_for": reused_questions(learned_dir / "evidence" / str(data.get("skill_id")) / "reuse_runs.jsonl"),
                }
            )
    summary = learning_summary(skills)
    return {"summary": summary, "skills": skills}


def reused_questions(path: Path) -> List[str]:
    if not path.exists():
        return []
    result: List[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        question = str(payload.get("question") or "").strip()
        if question and question not in result:
            result.append(question)
    return result[-20:]


def learning_summary(skills: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_kind: Dict[str, int] = {}
    for item in skills:
        kind = str(item.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "auto_learned_created_total": len(skills),
        "auto_learned_active_total": sum(1 for item in skills if item.get("active")),
        "auto_learned_reused_total": sum(
            1 for item in skills if int((item.get("runtime_health") or {}).get("reuse_count") or 0) > 0
        ),
        "auto_learned_never_reused_total": sum(
            1 for item in skills if int((item.get("runtime_health") or {}).get("reuse_count") or 0) == 0
        ),
        "auto_learned_failed_total": sum(
            1 for item in skills if int((item.get("runtime_health") or {}).get("failure_count") or 0) > 0
        ),
        "auto_learned_auto_blocked_total": sum(
            1 for item in skills if bool((item.get("runtime_health") or {}).get("auto_blocked"))
        ),
        "auto_learned_by_kind": by_kind,
    }


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


def compact_sufficiency_review(review: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(review, dict):
        return {}
    return {
        key: review.get(key)
        for key in [
            "sufficient",
            "partial",
            "missing_facts",
            "next_query_goal",
            "needs_clarification",
            "clarification_question",
            "clarification_options",
            "reasoning",
            "error",
        ]
        if key in review
    }


def hash_payload(payload: Any) -> str:
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def fixed_query_spec(*, final_query: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "fixed_query",
        "query": str(final_query.get("query") or ""),
        "params": dict(final_query.get("params") or {}),
        "limit": int(final_query.get("limit") or 100),
        "metadata_dependencies": metadata_dependencies_from_trace(trace) or query_sources_from_query(str(final_query.get("query") or ""))[:5],
    }


def fixed_query_can_be_reused(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    if not normalized.startswith("выбрать"):
        return False
    return " из " in f" {normalized} " and any(marker in normalized for marker in ["как ", "где", "сгруппировать по", "упорядочить по"])


def period_metric_shape_can_be_generalized(query: str, *, alias: str, period_field: str) -> bool:
    normalized = " ".join(query.lower().split())
    if "первые" in normalized:
        return False
    group_fields = group_by_expressions(query)
    if not group_fields:
        return True
    allowed_year = f"год({alias}.{period_field})".lower()
    return all("".join(field.lower().split()) == "".join(allowed_year.split()) for field in group_fields)


def group_by_expressions(query: str) -> List[str]:
    match = re.search(
        r"\bСГРУППИРОВАТЬ\s+ПО\s+(?P<group>.*?)(?:\bУПОРЯДОЧИТЬ\s+ПО\b|\bИМЕЮЩИЕ\b|$)",
        query,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return []
    return split_select_expressions(match.group("group"))


def metadata_dependencies_from_trace(trace: Dict[str, Any]) -> List[str]:
    result: List[str] = []
    for item in trace.get("metadata_objects", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("full_name") or item.get("ПолноеИмя") or "").strip()
        if name and name not in result:
            result.append(name)
    return result[:10]


def output_columns_from_trace(trace: Dict[str, Any]) -> List[str]:
    final_artifact = trace.get("final_artifact") if isinstance(trace.get("final_artifact"), dict) else {}
    value = final_artifact.get("value") if isinstance(final_artifact, dict) and isinstance(final_artifact.get("value"), dict) else {}
    columns = value.get("columns") if isinstance(value.get("columns"), list) else []
    result = [str(item) for item in columns if str(item or "").strip()]
    if result:
        return result
    attempts = trace.get("successful_steps")
    if isinstance(attempts, list):
        for item in reversed(attempts):
            if not isinstance(item, dict):
                continue
            rows = item.get("rows")
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                return [str(key) for key in rows[0].keys()]
    return []


def output_columns_from_query(query: str) -> List[str]:
    match = re.search(r"\bВЫБРАТЬ\s+(?P<select>.*?)\s+\bИЗ\b", query, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return []
    result: List[str] = []
    for expression in split_select_expressions(match.group("select")):
        alias_match = re.search(r"\s+КАК\s+(?P<label>[A-Za-zА-Яа-яЁё0-9_]+)\s*$", expression, flags=re.IGNORECASE)
        if alias_match:
            label = alias_match.group("label")
            if label not in result:
                result.append(label)
    return result


def query_sources_from_query(query: str) -> List[str]:
    result: List[str] = []
    for match in re.finditer(
        r"\b(?:ИЗ|СОЕДИНЕНИЕ)\s+(?P<source>[A-Za-zА-Яа-яЁё0-9_.]+(?:\([^)]*\))?)",
        query,
        flags=re.IGNORECASE,
    ):
        source = match.group("source").strip()
        if source and source not in result:
            result.append(source)
    return result


def skill_from_spec(
    spec: Dict[str, Any],
    *,
    intent: IntentResult,
    goal: Optional[GoalDecomposition],
) -> SkillContract:
    if spec.get("kind") == "parameterized_lookup_query":
        return lookup_skill_from_spec(spec, intent=intent)
    output_type = output_type_for_intent(intent, spec)
    skill_id = skill_id_for_spec(output_type, spec)
    domain_terms = metric_terms(intent)
    description_terms = ", ".join(domain_terms[:6]) or intent.business_goal
    return SkillContract.from_dict(
        {
            "skill_id": skill_id,
            "version": "0.1.0",
            "kind": SkillKind.DATA.value,
            "status": SkillStatus.VERIFIED.value,
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


def lookup_skill_from_spec(spec: Dict[str, Any], *, intent: IntentResult) -> SkillContract:
    output_type = output_type_for_intent(intent, spec)
    skill_id = skill_id_for_spec(output_type, spec)
    roles = [str(item) for item in spec.get("supported_filter_roles", []) or []]
    domain_terms = metric_terms(intent)
    description_terms = ", ".join(domain_terms[:6]) or intent.business_goal
    return SkillContract.from_dict(
        {
            "skill_id": skill_id,
            "version": "0.1.0",
            "kind": SkillKind.DATA.value,
            "status": SkillStatus.VERIFIED.value,
            "description": f"Learned parameterized lookup query for {description_terms}.",
            "capabilities": [
                "learned_query",
                "parameterized_lookup_query",
                *roles,
                *domain_terms,
                f"produce:{output_type}",
            ],
            "inputs": [
                {
                    "name": "filters",
                    "type": "SemanticFilterList",
                    "required": True,
                    "description": "Semantic filters used to fill learned query parameters.",
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
                    "description": "Learned lookup table",
                }
            ],
            "tags": ["learned", "lookup", *roles, *domain_terms],
            "semantic_role": semantic_role_for_output(output_type),
            "supported_filter_roles": roles,
            "implementation_strategy": "learned_query",
            "implementation": spec,
        }
    )


def output_type_for_intent(intent: IntentResult, spec: Dict[str, Any]) -> str:
    words = " ".join([intent.business_goal, *intent.domain_terms, *spec.get("metric_terms", [])]).lower()
    if spec.get("kind") == "parameterized_lookup_query":
        roles = set(spec.get("supported_filter_roles", []) or [])
        columns = [str(item).lower() for item in spec.get("output_columns", []) or []]
        if {"product", "price_type"}.issubset(roles) and any("цена" in item or "price" in item for item in columns + [words]):
            return "PriceTable"
        return "LearnedLookupTable"
    if any(marker in words for marker in ["выруч", "приб", "profit", "revenue"]):
        return "FinancialMetricsTable"
    return "LearnedMetricsTable"


def semantic_role_for_output(output_type: str) -> str:
    if output_type == "PriceTable":
        return "product_price_lookup"
    if output_type == "LearnedLookupTable":
        return "learned_lookup"
    if output_type == "FinancialMetricsTable":
        return "financial_metrics"
    return "learned_metrics"


def skill_id_for_spec(output_type: str, spec: Dict[str, Any]) -> str:
    if output_type == "FinancialMetricsTable":
        return "learned_financial_metrics"
    if spec.get("kind") == "parameterized_lookup_query":
        roles_list = [str(item) for item in spec.get("supported_filter_roles", []) or []]
        roles = "_".join(roles_list)
        stable_payload = {
            "kind": spec.get("kind"),
            "query": spec.get("query"),
            "roles": roles,
            "bindings": [
                {
                    "semantic_field": item.get("semantic_field"),
                    "parameter": item.get("parameter"),
                    "transform": item.get("transform"),
                }
                for item in spec.get("parameter_bindings", [])
                if isinstance(item, dict)
            ],
        }
        if output_type == "PriceTable" and {"product", "price_type"}.issubset(set(roles_list)):
            return "learned_product_price_lookup"
        digest = hashlib.sha1(json.dumps(stable_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"learned_lookup_{digest}"
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
        expr = re.sub(r"^\s*ПЕРВЫЕ\s+\d+\s+", "", expr, flags=re.IGNORECASE).strip()
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
