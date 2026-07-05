from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.app.factory import build_agent
from wiicon5.regression import load_cases, run_regression_cases
from wiicon5.regression.replay import run_regression_replay, save_replay_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or replay WIICON5 regression case files.")
    parser.add_argument("--cases", required=True, help="Case JSON file or directory with JSON cases.")
    parser.add_argument("--replay", action="store_true", help="Run cases through the agent instead of validating only.")
    parser.add_argument("--root", default=".", help="Project root for settings, skills, and bot instances.")
    parser.add_argument("--out", default="", help="Optional directory for replay result JSON.")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases).expanduser())
    if args.replay:
        root = Path(args.root).resolve()
        settings = Settings.from_env(root=root)
        result_obj = run_regression_replay(cases, build_agent(settings))
        result = result_obj.to_dict()
        out_dir = Path(args.out).expanduser() if args.out else settings.bot_context.root / "regression" / "results"
        result["path"] = str(save_replay_result(result_obj, out_dir))
    else:
        result = run_regression_cases(cases)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
