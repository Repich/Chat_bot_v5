from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.app.factory import build_agent
from wiicon5.evaluation.mvp import load_mvp_cases, run_mvp_evaluation, save_mvp_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated cold/warm MVP learning evaluation.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--cases", default="evaluation/mvp_cases.json")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cases = load_mvp_cases((root / args.cases).resolve() if not Path(args.cases).is_absolute() else Path(args.cases))
    output_dir = Path(args.out).expanduser().resolve() if args.out else root / "bot_instances" / "local" / "evaluation" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wiicon5_mvp_") as temp_dir:
        temp_root = Path(temp_dir)

        def isolated_agent(case):
            safe_case_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in case.case_id)
            isolated_bot = temp_root / (safe_case_id or "case")
            copy_bot_read_only_context(root / "bot_instances" / "local", isolated_bot)
            settings = Settings.from_env(
                {
                    "WIICON5_BOT_ROOT": str(isolated_bot),
                    "WIICON5_RUNS_DIR": str(output_dir / "runs"),
                    "WIICON5_CONFIG_FINGERPRINT": "auto",
                },
                root=root,
            )
            return build_agent(settings)

        result = run_mvp_evaluation(cases, agent_factory=isolated_agent)
    report_path = output_dir / f"{result.run_id}.json"
    save_mvp_evaluation(result, report_path)
    payload = result.to_dict()
    payload["path"] = str(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def copy_bot_read_only_context(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    bot_config = source / "bot.yaml"
    if bot_config.exists():
        shutil.copy2(bot_config, destination / "bot.yaml")
    onboarding = source / "onboarding"
    if onboarding.exists():
        shutil.copytree(onboarding, destination / "onboarding", dirs_exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
