from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.app.config import Settings
from wiicon5.skills.packs import export_skill_pack, save_skill_pack


def main() -> int:
    parser = argparse.ArgumentParser(description="Export WIICON5 skills into a portable candidate skill pack.")
    parser.add_argument("--root", default=".", help="Project root for settings, skills, and bot instance.")
    parser.add_argument("--bot", default="", help="Bot id override.")
    parser.add_argument("--skills", nargs="+", required=True, help="Skill ids to export.")
    parser.add_argument("--out", required=True, help="Output skill pack JSON path.")
    parser.add_argument("--include-bindings", action="store_true", help="Include matching binding JSON records.")
    args = parser.parse_args()

    env = {"WIICON5_BOT_ID": args.bot} if args.bot else None
    root = Path(args.root).resolve()
    settings = Settings.from_env(env=env, root=root)
    pack = export_skill_pack(
        skill_ids=args.skills,
        global_skills_dir=settings.skills_dir,
        bot_instance_root=settings.bot_context.root,
        include_bindings=args.include_bindings,
        bindings_dirs=[settings.bindings_dir],
        source_bot_id=settings.bot_context.root.name or "local",
    )
    save_skill_pack(pack, Path(args.out).expanduser())
    print(json.dumps({"ok": not pack["missing_skill_ids"], "path": args.out, "pack": pack}, ensure_ascii=False, indent=2))
    return 0 if not pack["missing_skill_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
