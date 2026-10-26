#!/usr/bin/env python3
"""Tests of tools/check_pr_title.py: a PR title is a Conventional Commits 1.0.0 header.

    python3 tests/test_check_pr_title.py
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_pr_title  # noqa: E402

SCRIPT = ROOT / "tools" / "check_pr_title.py"


def run(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


class Titles(unittest.TestCase):
    def test_accepts_conventional_headers(self):
        for title in ("feat: add a switch", "fix(hooks): check the bytes first", "feat!: drop api 5",
                      "refactor(mod)!: split Start", "FIX: types are case-insensitive", "ci: pin the actions"):
            with self.subTest(title=title):
                check_pr_title.check(title)

    def test_refuses_the_rest(self):
        for title in ("", "Add a switch", "feat add a switch", "feat:no space", "feat: ", "wip: half done",
                      "feat(): empty scope", "feat: one\ntwo", "Merge branch 'main'"):
            with self.subTest(title=title):
                with self.assertRaises(check_pr_title.Failure):
                    check_pr_title.check(title)


class Command(unittest.TestCase):
    def test_ok_exits_zero(self):
        result = run("--title", "fix: x")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok:", result.stdout)

    def test_bad_title_exits_one_and_says_why(self):
        result = run("--title", "no type here")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL:", result.stderr)

    def test_no_title_fails_loudly(self):
        result = run(env={"PATH": ""})
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL:", result.stderr)


if __name__ == "__main__":
    unittest.main()
