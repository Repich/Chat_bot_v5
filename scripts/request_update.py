from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Request installation of the newest offline WIICON5 update.")
    parser.add_argument("--install-root", required=True)
    args = parser.parse_args()
    install_root = Path(args.install_root).resolve()
    app_root = install_root / "app" / "current"
    sys.path.insert(0, str(app_root / "src"))

    from wiicon5.deployment.updates import OfflineUpdateManager

    current_version = (app_root / "VERSION").read_text(encoding="utf-8").strip()
    manager = OfflineUpdateManager(
        inbox=install_root / "updates" / "inbox",
        request_file=install_root / "updates" / "apply-request.json",
        current_version=current_version,
    )
    package = manager.request_latest()
    print(f"Обновление {package.version} поставлено в очередь: {package.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
