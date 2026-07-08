#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        print(json.dumps({"action": "unavailable", "developer_note": f"Invalid stdin JSON: {exc}"}))
        return 0

    prompt = build_prompt(payload)
    with tempfile.TemporaryDirectory(prefix="wiicon5_codex_solver_") as temp_dir:
        output_path = Path(temp_dir) / "answer.txt"
        command = [
            os.environ.get("WIICON5_CODEX_BIN", "codex"),
            "exec",
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--output-last-message",
            str(output_path),
        ]
        model = os.environ.get("WIICON5_FAILURE_SOLVER_CODEX_MODEL", "").strip()
        if model:
            command.extend(["--model", model])
        profile = os.environ.get("WIICON5_FAILURE_SOLVER_CODEX_PROFILE", "").strip()
        if profile:
            command.extend(["--profile", profile])
        command.append("-")
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=float(os.environ.get("WIICON5_FAILURE_SOLVER_CODEX_TIMEOUT_SECONDS", "180")),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(json.dumps({"action": "unavailable", "developer_note": str(exc)}, ensure_ascii=False))
            return 0
        answer = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else completed.stdout
        parsed = parse_json_object(answer)
        if parsed is None:
            parsed = {
                "action": "unavailable",
                "developer_note": "Codex did not return a JSON object.",
                "raw_stdout_preview": completed.stdout[:2000],
                "raw_stderr_preview": completed.stderr[:1000],
                "answer_preview": answer[:2000],
            }
        print(json.dumps(parsed, ensure_ascii=False))
    return 0


def build_prompt(payload: dict) -> str:
    return (
        "You are an emergency solver for WIICON ChatBot 5 query synthesis failures.\n"
        "Return only one JSON object matching this schema:\n"
        '{"action":"retry_query|needs_developer|cannot_solve","query":"","params":{},'
        '"limit":100,"reasoning":"","answer_guidance":"","developer_note":""}\n\n'
        "Do not edit code. If code changes are required, return needs_developer.\n"
        "If a safe 1C query can solve the data task, return retry_query.\n\n"
        "<diagnostic_json>\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n</diagnostic_json>\n"
    )


def parse_json_object(text: str):
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


if __name__ == "__main__":
    raise SystemExit(main())
