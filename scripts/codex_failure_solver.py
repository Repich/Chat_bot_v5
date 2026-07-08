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
        schema_path = Path(temp_dir) / "schema.json"
        schema_path.write_text(json.dumps(response_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            os.environ.get("WIICON5_CODEX_BIN", "codex"),
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--output-schema",
            str(schema_path),
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
        invocation = {
            "command": command_without_temp_paths(command, temp_dir),
            "timeout_seconds": float(os.environ.get("WIICON5_FAILURE_SOLVER_CODEX_TIMEOUT_SECONDS", "180")),
        }
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=invocation["timeout_seconds"],
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(
                json.dumps(
                    {
                        "action": "unavailable",
                        "developer_note": str(exc),
                        "codex_invocation": invocation,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        answer = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else completed.stdout
        parsed = parse_json_object(answer)
        invocation.update(
            {
                "returncode": completed.returncode,
                "stdout_preview": completed.stdout[:4000],
                "stderr_preview": completed.stderr[:4000],
                "answer_preview": answer[:4000],
            }
        )
        if parsed is None:
            parsed = {
                "action": "unavailable",
                "developer_note": "Codex did not return a JSON object.",
                "raw_stdout_preview": completed.stdout[:4000],
                "raw_stderr_preview": completed.stderr[:4000],
                "answer_preview": answer[:4000],
                "codex_invocation": invocation,
            }
        else:
            parsed = normalize_response(parsed)
            parsed["codex_invocation"] = invocation
        print(json.dumps(parsed, ensure_ascii=False))
    return 0


def response_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["retry_query", "needs_developer", "cannot_solve", "unavailable"],
            },
            "query": {"type": "string"},
            "params": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": ["string", "number", "boolean", "null"]},
                        "value_json": {"type": "string"},
                    },
                    "required": ["name", "value", "value_json"],
                },
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            "reasoning": {"type": "string"},
            "answer_guidance": {"type": "string"},
            "developer_note": {"type": "string"},
        },
        "required": ["action", "query", "params", "limit", "reasoning", "answer_guidance", "developer_note"],
    }


def command_without_temp_paths(command: list[str], temp_dir: str) -> list[str]:
    result = []
    for item in command:
        result.append(item.replace(temp_dir, "<temp>"))
    return result


def normalize_response(parsed: dict) -> dict:
    result = dict(parsed)
    params = result.get("params")
    if isinstance(params, list):
        result["params"] = params_array_to_dict(params)
    elif not isinstance(params, dict):
        result["params"] = {}
    result.setdefault("query", "")
    result.setdefault("limit", 100)
    result.setdefault("reasoning", "")
    result.setdefault("answer_guidance", "")
    result.setdefault("developer_note", "")
    return result


def params_array_to_dict(params: list) -> dict:
    result = {}
    for item in params:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        value_json = item.get("value_json")
        if isinstance(value_json, str) and value_json.strip():
            try:
                result[name] = json.loads(value_json)
                continue
            except ValueError:
                pass
        result[name] = item.get("value")
    return result


def build_prompt(payload: dict) -> str:
    return (
        "You are an emergency solver for WIICON ChatBot 5 query synthesis failures.\n"
        "Return only one JSON object matching this schema:\n"
        '{"action":"retry_query|needs_developer|cannot_solve","query":"","params":[{"name":"Param","value":"text","value_json":""}],'
        '"limit":100,"reasoning":"","answer_guidance":"","developer_note":""}\n\n'
        "Use params as an array. Put simple scalar values into value. "
        "For complex parameter values, put JSON text into value_json and null into value.\n"
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
