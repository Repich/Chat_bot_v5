from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliSmokeTests(unittest.TestCase):
    def test_mcp_smoke_reports_unknown_skill(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/mcp_smoke.py", "--skill-id", "unknown_skill"],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("Unknown skill", payload["error"])


if __name__ == "__main__":
    unittest.main()

