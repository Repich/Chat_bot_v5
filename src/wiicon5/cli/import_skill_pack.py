from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.skills.packs import import_skill_pack


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a WIICON5 skill pack into a bot workspace as candidate skills.")
    parser.add_argument("--root", default=".", help="Project root for settings and bot instance.")
    parser.add_argument("--bot", default="", help="Bot id override.")
    parser.add_argument("--file", required=True, help="Skill pack JSON path.")
    parser.add_argument("--include-bindings", action="store_true", help="Import bundled bindings as candidate evidence.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing imported candidate files.")
    parser.add_argument("--actor", default="admin", help="Audit actor.")
    args = parser.parse_args()

    env = {"WIICON5_BOT_ID": args.bot} if args.bot else None
    settings = Settings.from_env(env=env, root=Path(args.root).resolve())
    result = import_skill_pack(
        pack_path=Path(args.file).expanduser(),
        bot_instance_root=settings.bot_context.root,
        include_bindings=args.include_bindings,
        overwrite=args.overwrite,
        actor=args.actor,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
