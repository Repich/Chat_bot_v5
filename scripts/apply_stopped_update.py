from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a WIICON5 update while the Windows supervisor is stopped.")
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--package")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    staged_app_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(staged_app_root / "src"))
    from wiicon5.deployment.updates import apply_update, rollback_update

    install_root = Path(args.install_root).resolve()
    if args.rollback:
        result = {"ok": rollback_update(install_root=install_root), "rollback": True}
    else:
        if not args.package:
            parser.error("--package is required unless --rollback is used")
        result = apply_update(Path(args.package), install_root=install_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
