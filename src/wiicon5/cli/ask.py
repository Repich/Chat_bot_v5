from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.app.factory import build_agent
from wiicon5.conversation.context import ResolvedEntity
from wiicon5.execution.artifacts import Artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask WIICON ChatBot 5 one question.")
    parser.add_argument("message", nargs="+", help="User message.")
    parser.add_argument("--session-id", default="cli", help="Session id.")
    parser.add_argument("--root", default=".", help="Project root for skills/bindings/runs.")
    parser.add_argument("--product-ref", default="", help="Optional product ref to seed dialog context.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    settings = Settings.from_env(root=root)
    agent = build_agent(settings)
    context = agent.memory.get_or_create(args.session_id)
    context.config_fingerprint = settings.config_fingerprint
    if args.product_ref:
        value = parse_ref_argument(args.product_ref)
        context.add_artifact(Artifact(name="product", type="ProductRef", value=value, provenance=["cli"]))
        context.add_resolved_entity(
            ResolvedEntity(role="product", artifact_type="ProductRef", value=value, source="cli", confidence=1.0)
        )
    result = agent.handle(" ".join(args.message), session_id=args.session_id)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.source not in {"skill_execution_failed", "skill_gap", "needs_goal_decomposition"} else 1


def parse_ref_argument(raw: str):
    text = raw.strip()
    if text.startswith("{"):
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    return {"ref": raw}


if __name__ == "__main__":
    raise SystemExit(main())
