from __future__ import annotations

from typing import Optional

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.app.config import Settings
from wiicon5.conversation.memory import ConversationMemory
from wiicon5.execution.runtime import SkillPlanExecutor, default_runners
from wiicon5.intent.llm_decomposer import LLMGoalDecomposer
from wiicon5.instance_knowledge.answer import KnowledgeAnswerService
from wiicon5.instance_knowledge.index import InstanceKnowledgeBase
from wiicon5.instance_knowledge.storage import KnowledgeRepository
from wiicon5.knowledge.bindings import BindingResolver, JsonBindingStore
from wiicon5.knowledge.config_profile import build_configuration_profile, manual_configuration_profile
from wiicon5.knowledge.discovery import MetadataBindingDiscoverer
from wiicon5.knowledge.metadata import McpMetadataProvider, MetadataProvider
from wiicon5.knowledge.onboarding_evidence import OnboardingEvidenceProvider
from wiicon5.knowledge.onboarding_index import IndexedMetadataProvider, OnboardingMetadataIndex
from wiicon5.llm.client import LLMClient, OpenAICompatibleLLMClient
from wiicon5.mcp.client import HttpMcpClient, McpClient
from wiicon5.policies import BaselineIntentPolicy, DomainPolicy
from wiicon5.presentation.llm_answer_formatter import LLMAnswerFormatter
from wiicon5.query.document_list_query_builder import DocumentListQueryBuilder
from wiicon5.query.learned_query_builder import LearnedQueryBuilder
from wiicon5.query.one_c_query_review import OneCQueryReviewer
from wiicon5.query.semantic_query_builder import SemanticQueryBuilder
from wiicon5.query_synthesis import QuerySynthesisEngine
from wiicon5.query_synthesis.failure_solver import (
    CodexCliFailureSolver,
    FailureSolver,
    LLMFailureSolver,
    UnavailableFailureSolver,
)
from wiicon5.query_synthesis.sufficiency import ResultSufficiencyReviewer
from wiicon5.query_synthesis.reuse_review import SkillExecutionPostReviewer
from wiicon5.skill_runtime.data_skill_runner import DataSkillRunner
from wiicon5.skills.learned import LearnedSkillRuntimeHealthStore, LearnedSkillStore
from wiicon5.skills.migration import quarantine_legacy_learned_skills
from wiicon5.skills.registry import SkillRegistry
from wiicon5.workbench.synthesis_candidates import SynthesisCandidateStore


def build_agent(
    settings: Settings,
    *,
    llm_client: Optional[LLMClient] = None,
    mcp_client: Optional[McpClient] = None,
    memory: Optional[ConversationMemory] = None,
) -> AgentOrchestrator:
    quarantine_legacy_learned_skills(learned_skill_root(settings))
    registry = SkillRegistry.load_from_dirs(skill_registry_roots(settings))
    effective_llm = llm_client or build_llm_client(settings)
    effective_mcp = mcp_client or HttpMcpClient(base_url=settings.mcp_url, timeout_seconds=settings.mcp_timeout_seconds)
    domain_policy = DomainPolicy(settings.bot_instance)
    metadata_provider = build_metadata_provider(settings, effective_mcp)
    config_profile = resolve_configuration_profile(settings, metadata_provider)
    query_reviewer = OneCQueryReviewer()
    binding_store = JsonBindingStore(settings.bindings_dir)
    binding_resolver = BindingResolver(binding_store, MetadataBindingDiscoverer(metadata_provider))
    data_runner = DataSkillRunner(
        query_builder=SemanticQueryBuilder(binding_resolver),
        mcp_client=effective_mcp,
        query_reviewer=query_reviewer,
        metadata_provider=metadata_provider,
    )
    runners = default_runners()
    runners["semantic_binding_query"] = data_runner
    runners["semantic_measure_query"] = data_runner
    runners["semantic_document_count_query"] = data_runner
    runners["semantic_document_list_query"] = DataSkillRunner(
        query_builder=DocumentListQueryBuilder(metadata_provider),
        mcp_client=effective_mcp,
        query_reviewer=query_reviewer,
        metadata_provider=metadata_provider,
    )
    runners["learned_query"] = DataSkillRunner(
        query_builder=LearnedQueryBuilder(),
        mcp_client=effective_mcp,
        query_reviewer=query_reviewer,
        metadata_provider=metadata_provider,
    )
    effective_memory = memory or ConversationMemory(default_config_fingerprint=config_profile.fingerprint)
    instance_knowledge = build_instance_knowledge(settings)
    learned_skills_dir = learned_skill_root(settings)
    learned_health_store = LearnedSkillRuntimeHealthStore(
        skills_dir=learned_skills_dir,
        registry=registry,
        failure_threshold=settings.auto_learned_skills_failure_threshold,
    )
    learned_skill_store = (
        LearnedSkillStore(
            skills_dir=learned_skills_dir,
            registry=registry,
            auto_activate=settings.auto_learned_skills_activate,
        )
        if settings.auto_learned_skills_enabled
        else None
    )
    synthesis_candidate_store = SynthesisCandidateStore(bot_instance_root=settings.bot_context.root)
    result_reviewer = ResultSufficiencyReviewer(
        effective_llm,
        domain_hint_packs=settings.bot_instance.domain_hint_packs,
    )
    return AgentOrchestrator(
        registry=registry,
        decomposer=LLMGoalDecomposer(
            llm_client=effective_llm,
            registry=registry,
            bot_config=settings.bot_instance,
            instance_knowledge=instance_knowledge,
        ),
        memory=effective_memory,
        baseline_intent_policy=BaselineIntentPolicy(domain_policy),
        domain_policy=domain_policy,
        plan_executor=SkillPlanExecutor(registry, runners),
        query_synthesizer=QuerySynthesisEngine(
            llm_client=effective_llm,
            metadata_provider=metadata_provider,
            mcp_client=effective_mcp,
            query_reviewer=query_reviewer,
            answer_formatter=LLMAnswerFormatter(effective_llm),
            result_reviewer=result_reviewer,
            bot_config=settings.bot_instance,
            onboarding_evidence_provider=OnboardingEvidenceProvider(settings.bot_context.root / "onboarding"),
            failure_solver=build_failure_solver(settings),
            instance_knowledge=instance_knowledge,
        ),
        learned_skill_store=learned_skill_store,
        synthesis_candidate_store=synthesis_candidate_store,
        skill_execution_reviewer=SkillExecutionPostReviewer(result_reviewer, registry),
        learned_health_store=learned_health_store,
        trace_root=settings.runs_dir,
        knowledge_answerer=(
            KnowledgeAnswerService(
                knowledge_base=instance_knowledge,
                llm_client=effective_llm,
                top_k=settings.bot_instance.knowledge.search_top_k,
            )
            if instance_knowledge is not None and settings.bot_instance.knowledge.answer_enabled
            else None
        ),
    )


def build_instance_knowledge(settings: Settings) -> Optional[InstanceKnowledgeBase]:
    config = settings.bot_instance.knowledge
    if not config.enabled:
        return None
    return InstanceKnowledgeBase(
        KnowledgeRepository(settings.bot_context.root / "knowledge"),
        stale_after_days=config.stale_after_days,
    )


def skill_registry_roots(settings: Settings):
    seed_root = settings.skills_dir / "atomic" if (settings.skills_dir / "atomic").exists() else settings.skills_dir
    roots = [seed_root, settings.bot_context.root / "skills"]
    if settings.auto_learned_skills_scope == "global":
        roots.append(settings.skills_dir / "learned")
    return roots


def learned_skill_root(settings: Settings):
    if settings.auto_learned_skills_scope == "global":
        return settings.skills_dir
    return settings.bot_context.root / "skills"


def build_llm_client(settings: Settings) -> LLMClient:
    settings.validate_for_llm()
    return OpenAICompatibleLLMClient(
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def build_failure_solver(settings: Settings) -> Optional[FailureSolver]:
    if not settings.failure_solver_enabled:
        return None
    provider = settings.failure_solver_provider.strip().lower()
    if provider in {"openai", "openai_compatible", "api"}:
        missing = []
        if not settings.failure_solver_api_base:
            missing.append("WIICON5_FAILURE_SOLVER_API_BASE")
        if not settings.failure_solver_api_key:
            missing.append("WIICON5_FAILURE_SOLVER_API_KEY")
        if missing:
            return UnavailableFailureSolver("Missing failure solver settings: " + ", ".join(missing))
        return LLMFailureSolver(
            OpenAICompatibleLLMClient(
                api_base=settings.failure_solver_api_base,
                api_key=settings.failure_solver_api_key,
                model=settings.failure_solver_model,
                timeout_seconds=settings.failure_solver_timeout_seconds,
            )
        )
    if provider in {"codex", "codex_cli", "cli"}:
        if not settings.failure_solver_codex_command:
            return UnavailableFailureSolver("Missing failure solver setting: WIICON5_FAILURE_SOLVER_CODEX_COMMAND")
        return CodexCliFailureSolver(
            command=settings.failure_solver_codex_command,
            timeout_seconds=settings.failure_solver_timeout_seconds,
        )
    return UnavailableFailureSolver(f"Unsupported failure solver provider: {settings.failure_solver_provider}")


def build_metadata_provider(settings: Settings, mcp_client: McpClient) -> MetadataProvider:
    primary = McpMetadataProvider(mcp_client)
    index_path = settings.bot_context.root / "onboarding" / "metadata_index.sqlite"
    return IndexedMetadataProvider(primary, OnboardingMetadataIndex(index_path))


def resolve_configuration_profile(settings: Settings, metadata_provider: MetadataProvider):
    if settings.config_fingerprint.lower() in {"auto", "computed"}:
        return build_configuration_profile(metadata_provider, source="mcp")
    return manual_configuration_profile(settings.config_fingerprint)
