from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.mcp.client import HttpMcpClient
from wiicon5.onboarding.binding_candidate_verifier import verify_binding_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify onboarding binding candidates against MCP metadata.")
    parser.add_argument("--bot-instance", required=True, help="Path to bot instance workspace.")
    parser.add_argument("--mcp-url", required=True, help="MCP proxy URL.")
    parser.add_argument("--timeout", type=float, default=30.0, help="MCP request timeout in seconds.")
    parser.add_argument("--input", default="", help="Optional candidate_bindings.json path.")
    parser.add_argument("--output", default="", help="Optional verified_binding_candidates.json path.")
    parser.add_argument("--max-candidates", type=int, default=0, help="Verify only first N candidates; 0 means all.")
    parser.add_argument("--max-objects", type=int, default=0, help="Verify candidates for first N unique objects; 0 means all.")
    args = parser.parse_args()

    bot_instance = Path(args.bot_instance).expanduser()
    input_path = Path(args.input).expanduser() if args.input else bot_instance / "onboarding" / "candidate_bindings.json"
    output_path = (
        Path(args.output).expanduser() if args.output else bot_instance / "onboarding" / "verified_binding_candidates.json"
    )
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    candidates = apply_limits(candidates, max_candidates=args.max_candidates, max_objects=args.max_objects)
    results = verify_binding_candidates(
        candidates,
        HttpMcpClient(base_url=args.mcp_url, timeout_seconds=args.timeout),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "mcp_url": args.mcp_url,
                "input": str(input_path),
                "limits": {"max_candidates": args.max_candidates, "max_objects": args.max_objects},
                "verified": sum(1 for item in results if item.status == "verified_by_mcp"),
                "rejected": sum(1 for item in results if item.status == "rejected"),
                "items": [item.to_dict() for item in results],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "output": str(output_path), "items": len(results)}, ensure_ascii=False, indent=2))
    return 0


def apply_limits(candidates, *, max_candidates: int, max_objects: int):
    limited = list(candidates)
    if max_objects > 0:
        allowed = []
        seen = set()
        for candidate in limited:
            object_name = str(candidate.get("object") or candidate.get("metadata_object") or "")
            if object_name and object_name not in seen:
                if len(seen) >= max_objects:
                    continue
                seen.add(object_name)
            if object_name in seen:
                allowed.append(candidate)
        limited = allowed
    if max_candidates > 0:
        limited = limited[:max_candidates]
    return limited


if __name__ == "__main__":
    raise SystemExit(main())
