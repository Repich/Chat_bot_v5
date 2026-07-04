from __future__ import annotations

from typing import Optional

from wiicon5.agent.orchestrator import AgentOrchestrator
from wiicon5.app.config import Settings
from wiicon5.conversation.memory import ConversationMemory
from wiicon5.execution.runtime import SkillPlanExecutor, default_runners
from wiicon5.intent.llm_decomposer import LLMGoalDecomposer
from wiicon5.knowledge.bindings import BindingResolver, JsonBindingStore
from wiicon5.knowledge.config_profile import build_configuration_profile, manual_configuration_profile
from wiicon5.knowledge.discovery import MetadataBindingDiscoverer
from wiicon5.knowledge.metadata import McpMetadataProvider
from wiicon5.llm.client import LLMClient, OpenAICompatibleLLMClient
from wiicon5.mcp.client import HttpMcpClient, McpClient
from wiicon5.policies import BaselineIntentPolicy, DomainPolicy
from wiicon5.presentation.llm_answer_formatter import LLMAnswerFormatter
from wiicon5.query.document_list_query_builder import DocumentListQueryBuilder
from wiicon5.query.learned_query_builder import LearnedQueryBuilder
from wiicon5.query.one_c_query_review import OneCQueryReviewer
from wiicon5.query.semantic_query_builder import SemanticQueryBuilder
from wiicon5.query_synthesis import QuerySynthesisEngine
from wiicon5.query_synthesis.sufficiency import ResultSufficiencyReviewer
from wiicon5.skill_runtime.data_skill_runner import DataSkillRunner
from wiicon5.skills.learned import LearnedSkillStore
from wiicon5.skills.registry import SkillRegistry


def build_agent(
    settings: Settings,
    *,
    llm_client: Optional[LLMClient] = None,
    mcp_client: Optional[McpClient] = None,
    memory: Optional[ConversationMemory] = None,
) -> AgentOrchestrator:
    registry = SkillRegistry.load_from_dir(settings.skills_dir)
    effective_llm = llm_client or build_llm_client(settings)
    effective_mcp = mcp_client or HttpMcpClient(base_url=settings.mcp_url, timeout_seconds=settings.mcp_timeout_seconds)
    domain_policy = DomainPolicy(settings.bot_instance)
    metadata_provider = McpMetadataProvider(effective_mcp)
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
    learned_skill_store = LearnedSkillStore(skills_dir=settings.skills_dir, registry=registry)
    return AgentOrchestrator(
        registry=registry,
        decomposer=LLMGoalDecomposer(llm_client=effective_llm, registry=registry, bot_config=settings.bot_instance),
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
            result_reviewer=ResultSufficiencyReviewer(effective_llm),
            bot_config=settings.bot_instance,
        ),
        learned_skill_store=learned_skill_store,
        trace_root=settings.runs_dir,
    )


def build_llm_client(settings: Settings) -> LLMClient:
    settings.validate_for_llm()
    return OpenAICompatibleLLMClient(
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def resolve_configuration_profile(settings: Settings, metadata_provider: McpMetadataProvider):
    if settings.config_fingerprint.lower() in {"auto", "computed"}:
        return build_configuration_profile(metadata_provider, source="mcp")
    return manual_configuration_profile(settings.config_fingerprint)
