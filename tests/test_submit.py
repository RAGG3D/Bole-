from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBMIT = ROOT / "scripts/submit.py"
FAKE = ROOT / "tests/fake_openclaw"


class SubmitLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.profile = self.base / "profile"
        self.profile.mkdir()
        self.job = self.base / "Applications" / "Tier 1 (80+)" / "Example - Analyst"
        (self.job / "_content").mkdir(parents=True)
        self.verdict = {
            "jd_key": "Example :: Data Analyst",
            "company": "Example",
            "title": "Data Analyst",
            "url": "https://job-boards.greenhouse.io/example/jobs/123",
            "apply_url": "https://job-boards.greenhouse.io/example/jobs/123",
            "apply_type": "direct",
            "fit": 88,
            "seniority_band": "mid",
            "eligible": True,
            "redline_core_count": 0,
            "redline_flags": [],
            "decision": "generate",
            "rationale": "fixture",
            "jd_completeness": "full",
            "recommended_salary_note": "AUD 100,000 including super",
            "recommended_salary_form": {
                "amount": 100000,
                "currency": "AUD",
                "includes_super": True,
            },
        }
        (self.job / "verdict.json").write_text(
            json.dumps(self.verdict), encoding="utf-8"
        )
        (self.job / "README.md").write_text("# fixture\n", encoding="utf-8")
        (self.job / "Li - CV - Example.pdf").write_bytes(b"%PDF fixture")
        (self.job / "Li - Cover Letter - Example.pdf").write_bytes(b"%PDF fixture")
        (self.job / "_content/cv.json").write_text(
            json.dumps({"type": "cv", "profile": "R and Python analyst"}),
            encoding="utf-8",
        )
        self.facts = {
            "basics": {
                "work_rights": "Full work rights",
                "notice_period": "Two weeks",
                "date_of_birth": None,
            },
            "red_lines": ["Power BI", "wet-lab"],
        }
        self.config = {
            "salary_expectation": {
                "amount": 95000,
                "currency": "AUD",
                "includes_super": True,
            },
            "auto_submit": {
                "enabled": True,
                "allowed_ats": ["greenhouse"],
                "max_per_run": 5,
                "final_confirm": "per_run",
                "submit_timeout_s": 1,
                "verify_timeout_s": 1,
                "max_continues_per_job": 6,
            },
        }
        self.config_path = self.profile / "config.json"
        self.facts_path = self.profile / "facts.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.facts_path.write_text(json.dumps(self.facts), encoding="utf-8")
        self.script_path = self.base / "script.txt"
        self.log_path = self.base / "calls.jsonl"
        self.state_path = self.base / "fake.state"
        self.env = {
            **os.environ,
            "BOLE_OPENCLAW_BIN": str(FAKE),
            "BOLE_FAKE_SCRIPT": str(self.script_path),
            "BOLE_FAKE_LOG": str(self.log_path),
            "BOLE_FAKE_STATE": str(self.state_path),
            "BOLE_SUBMISSIONS_FILE": str(self.base / "state/submissions.json"),
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def command(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SUBMIT), *(str(arg) for arg in args)],
            cwd=self.base,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

    def run_new(self) -> subprocess.CompletedProcess[str]:
        return self.command(
            "run",
            "--job",
            self.job,
            "--config",
            self.config_path,
            "--facts",
            self.facts_path,
        )

    def ledger_entry(self) -> dict[str, object]:
        data = json.loads(
            (self.base / "state/submissions.json").read_text(encoding="utf-8")
        )
        return data["submissions"][0]

    def calls(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_need_otp_continue_reuses_thread_then_submits_and_dedupes(self) -> None:
        self.script_path.write_text(
            "RESULT: NEED | what=otp | question=Enter code\n"
            "RESULT: SUBMITTED | evidence=confirmation-123\n",
            encoding="utf-8",
        )
        first = self.run_new()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("RESULT: NEED", first.stdout)
        continued = self.command(
            "continue", "--job", self.job, "--answer", "123456"
        )
        self.assertEqual(continued.returncode, 0, continued.stderr)
        self.assertIn("RESULT: SUBMITTED", continued.stdout)
        entry = self.ledger_entry()
        self.assertEqual(entry["status"], "submitted")
        self.assertEqual(entry["evidence"], "confirmation-123")
        self.assertEqual(
            [attempt["result"] for attempt in entry["attempts"]],
            ["NEED", "SUBMITTED"],
        )
        calls = self.calls()
        self.assertEqual(calls[0]["thread"], entry["thread"])
        self.assertEqual(calls[1]["thread"], entry["thread"])
        duplicate = self.run_new()
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("双投风险", duplicate.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_timeout_has_no_retry_then_verify_unknown(self) -> None:
        self.config["auto_submit"]["submit_timeout_s"] = 0.1
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.script_path.write_text(
            "SLEEP: 1\nVERIFY: UNKNOWN\n", encoding="utf-8"
        )
        first = self.run_new()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "RESULT: UNKNOWN")
        self.assertEqual(len(self.calls()), 1, "超时后 submit.py 不得自动重试")
        verified = self.command("verify", "--job", self.job)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(verified.stdout.strip(), "VERIFY: UNKNOWN")
        entry = self.ledger_entry()
        self.assertEqual(entry["status"], "unknown")
        self.assertEqual(
            [attempt["result"] for attempt in entry["attempts"]],
            ["UNKNOWN", "UNKNOWN"],
        )
        calls = self.calls()
        self.assertIsNone(calls[1]["thread"], "verify 必须新开只读会话")
        refused = self.command("continue", "--job", self.job)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("禁止直接续跑", refused.stderr)
        self.assertEqual(len(self.calls()), 2)

    def test_blocked_captcha_is_recorded_without_retry(self) -> None:
        self.script_path.write_text(
            "RESULT: BLOCKED | reason=captcha | detail=challenge\n",
            encoding="utf-8",
        )
        result = self.run_new()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ledger_entry()["status"], "blocked")
        self.assertEqual(len(self.calls()), 1)
        refused = self.command("continue", "--job", self.job)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(len(self.calls()), 1)

    def test_need_login_continue_without_answer_reuses_thread(self) -> None:
        self.script_path.write_text(
            "RESULT: NEED | what=login | question=Sign in\n"
            "RESULT: SUBMITTED | evidence=confirmation-login\n",
            encoding="utf-8",
        )
        first = self.run_new()
        self.assertEqual(first.returncode, 0, first.stderr)
        bad_answer = self.command(
            "continue", "--job", self.job, "--answer", "I have logged in"
        )
        self.assertNotEqual(bad_answer.returncode, 0)
        self.assertIn("无 --answer", bad_answer.stderr)
        continued = self.command("continue", "--job", self.job)
        self.assertEqual(continued.returncode, 0, continued.stderr)
        self.assertEqual(self.ledger_entry()["status"], "submitted")
        calls = self.calls()
        self.assertEqual(calls[0]["thread"], calls[1]["thread"])
        self.assertIn("请从当前进度继续", calls[1]["message"])

    def test_blocked_oauth_register_is_recorded(self) -> None:
        self.script_path.write_text(
            "RESULT: BLOCKED | reason=oauth_register | detail=Google only\n",
            encoding="utf-8",
        )
        result = self.run_new()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ledger_entry()["status"], "blocked")
        self.assertEqual(len(self.calls()), 1)

    def test_disabled_switch_never_invokes_openclaw(self) -> None:
        self.config["auto_submit"]["enabled"] = False
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.script_path.write_text(
            "RESULT: SUBMITTED | evidence=should-not-run\n", encoding="utf-8"
        )
        result = self.run_new()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("自动投递未开启", result.stderr)
        self.assertFalse(self.log_path.exists())

    def test_two_failed_results_move_job_to_manual(self) -> None:
        self.script_path.write_text(
            "RESULT: FAILED | detail=page load failed\n"
            "RESULT: FAILED | detail=page load failed again\n",
            encoding="utf-8",
        )
        first = self.run_new()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.command("continue", "--job", self.job)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.ledger_entry()["status"], "manual")
        refused = self.command("continue", "--job", self.job)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(len(self.calls()), 2)


if __name__ == "__main__":
    unittest.main()
