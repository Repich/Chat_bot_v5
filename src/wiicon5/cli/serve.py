from __future__ import annotations

import argparse
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.app.factory import build_agent
from wiicon5.mcp.client import HttpMcpClient
from wiicon5.onboarding.status import OnboardingManager
from wiicon5.web.admin_security import AdminSecurityConfig
from wiicon5.web.server import run_http_server
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
    smoke_service = McpSmokeTestService(
        bot_instance_root=settings.bot_context.root,
        mcp_client=HttpMcpClient(base_url=settings.mcp_url, timeout_seconds=settings.mcp_timeout_seconds),
    )
    admin_security = AdminSecurityConfig(
        enabled=settings.admin_enabled,
        token=settings.admin_token,
        bind_local_only=settings.admin_bind_local_only,
        allowed_config_roots=settings.admin_allowed_config_roots,
    )
    print(f"WIICON5 listening on http://{args.host}:{args.port}/chat")
    run_http_server(
        agent,
        host=args.host,
        port=args.port,
        onboarding_manager=onboarding_manager,
        smoke_service=smoke_service,
        admin_security=admin_security,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
