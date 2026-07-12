from __future__ import annotations

import argparse
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.app.factory import build_agent, build_instance_knowledge
from wiicon5.deployment.diagnostics import SessionDiagnosticStore
from wiicon5.deployment.updates import OfflineUpdateManager
from wiicon5.instance_knowledge.storage import KnowledgeRepository
from wiicon5.instance_knowledge.sync import KnowledgeSyncService
from wiicon5.mcp.client import HttpMcpClient
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.web.admin_security import AdminSecurityConfig
from wiicon5.web.server import run_http_server
from wiicon5.workbench.metadata_explorer import MetadataExplorerService
from wiicon5.workbench.preview import QueryPreviewService
from wiicon5.workbench.smoke import McpSmokeTestService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WIICON ChatBot 5 HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7785)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    settings = Settings.from_env(root=root)
    agent = build_agent(settings)
    onboarding_manager = OnboardingManager(bot_instance_root=settings.bot_context.root, mcp_url=settings.mcp_url)
    metadata_explorer = MetadataExplorerService.from_bot_instance(settings.bot_context.root)
    preview_service = QueryPreviewService(metadata_lookup=metadata_explorer.metadata_object)
    smoke_service = McpSmokeTestService(
        bot_instance_root=settings.bot_context.root,
        mcp_client=HttpMcpClient(base_url=settings.mcp_url, timeout_seconds=settings.mcp_timeout_seconds),
        preview_service=preview_service,
    )
    admin_security = AdminSecurityConfig(
        enabled=settings.admin_enabled,
        token=settings.admin_token,
        bind_local_only=settings.admin_bind_local_only,
        allowed_config_roots=settings.admin_allowed_config_roots,
        allow_raw_query_edit=settings.workbench_allow_raw_query_edit,
    )
    instance_knowledge = build_instance_knowledge(settings)
    knowledge = settings.bot_instance.knowledge
    knowledge_sync_service = KnowledgeSyncService(
        repository=KnowledgeRepository(settings.bot_context.root / "knowledge"),
        source_kind=knowledge.source_kind,
        base_url=knowledge.base_url,
        root_page_id=knowledge.root_page_id,
        timeout_seconds=knowledge.sync_timeout_seconds,
        max_pages=knowledge.max_pages,
    )
    diagnostics = SessionDiagnosticStore(
        root=settings.diagnostics_dir,
        runs_root=settings.runs_dir,
        project_root=root,
        bot_root=settings.bot_context.root,
        service_log_paths=(
            settings.service_log_path,
            settings.install_root / "logs" / "supervisor.log",
        ),
    )
    update_manager = (
        OfflineUpdateManager(
            inbox=settings.update_inbox_dir,
            request_file=settings.update_request_file,
            current_version=(root / "VERSION").read_text(encoding="utf-8").strip(),
        )
        if settings.offline_updates_enabled
        else None
    )
    print(f"WIICON5 listening on http://{args.host}:{args.port}/chat")
    run_http_server(
        agent,
        host=args.host,
        port=args.port,
        onboarding_manager=onboarding_manager,
        metadata_explorer=metadata_explorer,
        preview_service=preview_service,
        smoke_service=smoke_service,
        admin_security=admin_security,
        instance_knowledge=instance_knowledge,
        knowledge_sync_service=knowledge_sync_service,
        diagnostics=diagnostics,
        update_manager=update_manager,
        bot_config=settings.bot_instance,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
