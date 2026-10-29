# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The ruff lint gate rejects the security and async rules it promises to."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

# One representative violation per selected rule. Each is a complete module so
# that only the rule under test can fire.
BAD_SNIPPETS = {
    "S102": "def f(source):\n    exec(source)\n",
    "S113": "import requests\n\n\ndef f(url):\n    requests.get(url)\n",
    "S301": "import pickle\n\n\ndef f(blob):\n    pickle.loads(blob)\n",
    "S310": "import urllib.request\n\n\ndef f(url):\n    urllib.request.urlopen(url)\n",
    "S605": "import os\n\n\ndef f(command):\n    os.system(command)\n",
    "ASYNC210": "import requests\n\n\nasync def f(url):\n    requests.get(url, timeout=5)\n",
    "ASYNC220": "import subprocess\n\n\nasync def f():\n    subprocess.Popen(['true'])\n",
    "ASYNC230": "async def f():\n    open('x')\n",
    "ASYNC240": "import os\n\n\nasync def f():\n    os.path.exists('x')\n",
    "ASYNC251": "import time\n\n\nasync def f():\n    time.sleep(1)\n",
}


def _ruff_codes(source: str, filename: str = "src/ruff_probe.py", *extra: str) -> list[str]:
    """Lint ``source`` as if it lived at ``filename`` under the repository config."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(PYPROJECT),
            "--no-cache",
            "--output-format",
            "json",
            *extra,
            "--stdin-filename",
            filename,
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise AssertionError(f"ruff failed to run: {result.stderr}")
    return sorted({item["code"] for item in json.loads(result.stdout or "[]")})


@unittest.skipIf(importlib.util.find_spec("ruff") is None, "ruff is not installed")
class RuffSecurityGateTests(unittest.TestCase):
    def test_each_rule_rejects_a_representative_violation(self):
        for rule, snippet in BAD_SNIPPETS.items():
            with self.subTest(rule=rule):
                self.assertEqual(_ruff_codes(snippet), [rule])

    def test_requests_without_timeout_fails_and_with_timeout_passes(self):
        bad = BAD_SNIPPETS["S113"]
        self.assertEqual(_ruff_codes(bad), ["S113"])
        self.assertEqual(_ruff_codes(bad.replace("(url)\n", "(url, timeout=5)\n")), [])

    def test_rules_apply_to_tests_and_scripts(self):
        bad = BAD_SNIPPETS["S113"]
        self.assertEqual(_ruff_codes(bad, "tests/test_probe.py"), ["S113"])
        self.assertEqual(_ruff_codes(bad, "scripts/probe.py"), ["S113"])

    def test_assert_is_allowed_only_in_tests(self):
        snippet = "def f(x):\n    assert x\n"
        extend = ("--extend-select", "S101")
        self.assertEqual(_ruff_codes(snippet, "src/ruff_probe.py", *extend), ["S101"])
        self.assertEqual(_ruff_codes(snippet, "tests/test_probe.py", *extend), [])


if __name__ == "__main__":
    unittest.main()
