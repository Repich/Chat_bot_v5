from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.regression import load_cases, run_regression_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate WIICON5 regression case files.")
    parser.add_argument("--cases", required=True, help="Case JSON file or directory with JSON cases.")
    args = parser.parse_args()

    result = run_regression_cases(load_cases(Path(args.cases).expanduser()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
