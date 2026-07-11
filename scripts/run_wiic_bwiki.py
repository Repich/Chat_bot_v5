from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    bot_root = root / "bot_instances" / "wiic_bwiki"
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(root / "src") if not existing else str(root / "src") + os.pathsep + existing
    env.setdefault("WIICON5_BOT_ID", "wiic_bwiki")
    env.setdefault("WIICON5_BOT_ROOT", str(bot_root))
    env.setdefault("WIICON5_RUNS_DIR", str(bot_root / "runs"))
    arguments = list(sys.argv[1:])
    if "--port" not in arguments:
        arguments.extend(["--port", "7786"])
    return subprocess.call(
        [sys.executable, "-m", "wiicon5.cli.serve", "--root", str(root), *arguments],
        cwd=str(root),
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
