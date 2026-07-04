from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.onboarding import run_onboarding


def main() -> int:
    parser = argparse.ArgumentParser(description="Build WIICON5 onboarding candidates from a 1C configuration dump.")
    parser.add_argument("--config-dump", required=True, help="Path to exported 1C configuration files.")
    parser.add_argument("--bot-instance", required=True, help="Path to bot instance workspace.")
    parser.add_argument("--mcp-url", default="", help="Optional MCP URL recorded in the onboarding manifest.")
    args = parser.parse_args()

    result = run_onboarding(
        config_dump=Path(args.config_dump).expanduser(),
        bot_instance=Path(args.bot_instance).expanduser(),
        mcp_url=args.mcp_url,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
