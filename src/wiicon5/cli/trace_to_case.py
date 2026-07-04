from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiicon5.regression.cases import case_filename, case_from_trace, save_case


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a WIICON5 regression case from an agent trace.")
    parser.add_argument("trace_path", help="Path to runs/agent_* trace directory.")
    parser.add_argument("--cases-dir", default="", help="Directory where the case JSON should be written.")
    parser.add_argument("--expected-ok", action="store_true", help="Mark this trace as an expected successful case.")
    args = parser.parse_args()

    trace_path = Path(args.trace_path).expanduser()
    case = case_from_trace(trace_path, expected_ok=args.expected_ok)
    if args.cases_dir:
        path = Path(args.cases_dir).expanduser() / case_filename(case.question)
        save_case(case, path)
        print(json.dumps({"path": str(path), "case": case.to_dict()}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(case.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
