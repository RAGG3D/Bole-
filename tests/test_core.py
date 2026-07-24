from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run_script(
    script: str,
    *args: object,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, str(ROOT / "scripts" / script), *(str(arg) for arg in args)],
        cwd=cwd or ROOT,
        env={**os.environ, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )


class CoreFlowTests(unittest.TestCase):
    def test_paste_jd_preserves_fixture(self) -> None:
        fixture = ROOT / "examples/demo_jds/jd1.txt"
        result = run_script(
            "sources.py", "jd", "--source", "paste", "--file", fixture
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["source"], "paste")
        self.assertEqual(payload["text"], fixture.read_text(encoding="utf-8"))
        self.assertTrue(payload["text"].strip())

    def test_triage_places_senior_staff_in_list_senior(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            candidates = {
                "generated": "2026-07-24",
                "days": 7,
                "count": 3,
                "candidates": [
                    {
                        "source": "board",
                        "channel": "company_boards",
                        "title": "Senior Staff Engineer",
                        "company": "Example Systems",
                        "location": "Sydney",
                        "id": "2",
                        "url": "https://example.test/2",
                    },
                    {
                        "source": "board",
                        "channel": "company_boards",
                        "title": "Junior Data Analyst",
                        "company": "Example Retail",
                        "location": "Melbourne",
                        "id": "1",
                        "url": "https://example.test/1",
                    },
                    {
                        "source": "manual",
                        "channel": "url",
                        "title": "Senior Unusual Insights Role",
                        "company": "Example",
                        "location": "Remote",
                        "id": "",
                        "url": "https://example.test/3",
                    },
                ],
            }
            config = {
                "target_titles": ["Data Analyst"],
                "target_skills": ["SQL"],
                "eligibility_regex": "citizen|security clearance",
                "redline_stack_regex": "C\\+\\+|DevOps",
                "requires_no_citizenship_roles": True,
            }
            candidates_path = base / "candidates.json"
            config_path = base / "config.json"
            output_path = base / "buckets.json"
            candidates_path.write_text(json.dumps(candidates), encoding="utf-8")
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = run_script(
                "triage.py",
                "--candidates",
                candidates_path,
                "--config",
                config_path,
                "--out",
                output_path,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            buckets = json.loads(output_path.read_text(encoding="utf-8"))["buckets"]
            self.assertEqual(
                [item["title"] for item in buckets["LIST_senior"]],
                ["Senior Staff Engineer"],
            )
            self.assertEqual(len(buckets["SCORE"]), 2)

    def test_redline_blocks_and_clean_content_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            facts = ROOT / "examples/demo_facts.json"
            content = base / "content"
            content.mkdir()
            material = {
                "type": "cv",
                "name": "李示例",
                "profile": "Data analyst experienced with Power BI.",
                "sections": [],
            }
            cv_path = content / "cv.json"
            cv_path.write_text(json.dumps(material), encoding="utf-8")
            blocked = run_script(
                "redline_scan.py", "--facts", facts, "--content", content
            )
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("Power BI", blocked.stdout + blocked.stderr)
            material["profile"] = "Data analyst experienced with R and Python."
            cv_path.write_text(json.dumps(material), encoding="utf-8")
            clean = run_script(
                "redline_scan.py", "--facts", facts, "--content", content
            )
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
            self.assertIn("PASS", clean.stdout)

    def test_build_docs_gracefully_keeps_html_without_browser(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cv = {
                "type": "cv",
                "name": "Li Example",
                "subtitle": "Data Analyst",
                "contact": {"email": "li@example.com"},
                "profile": "Careful and reproducible analyst.",
                "sections": [
                    {
                        "heading": "EXPERIENCE",
                        "entries": [
                            {
                                "role": "Data Analyst",
                                "org": "Example",
                                "meta": "2024–present · Melbourne",
                                "bullets": ["Automated a **weekly** quality report."],
                            }
                        ],
                    }
                ],
            }
            source = base / "cv.json"
            target = base / "cv.pdf"
            source.write_text(json.dumps(cv), encoding="utf-8")
            result = run_script(
                "build_docs.py",
                source,
                target,
                "--fit-pages",
                2,
                env={"BOLE_BROWSER_BIN": str(base / "missing-browser")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.with_suffix(".html").is_file())
            self.assertIn("Ctrl+P", result.stdout)

    def test_ledger_dual_key_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "discover.json"
            ledger = base / "seen.json"
            filtered = base / "filtered.json"
            envelope = {
                "generated": "2026-07-24",
                "days": 7,
                "count": 1,
                "candidates": [
                    {
                        "source": "linkedin",
                        "id": "123",
                        "company": "Example, Inc.",
                        "title": "Data Analyst",
                        "url": "https://www.linkedin.com/jobs/view/123",
                    }
                ],
            }
            source.write_text(json.dumps(envelope), encoding="utf-8")
            committed = run_script(
                "ledger.py",
                "commit",
                "--candidates",
                source,
                "--ledger",
                ledger,
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            second = dict(envelope)
            second["candidates"] = [
                {
                    "source": "board",
                    "id": "different",
                    "company": "example inc",
                    "title": "DATA ANALYST",
                    "url": "https://example.test/job",
                }
            ]
            source.write_text(json.dumps(second), encoding="utf-8")
            filtered_result = run_script(
                "ledger.py",
                "filter",
                "--candidates",
                source,
                "--out",
                filtered,
                "--ledger",
                ledger,
            )
            self.assertEqual(filtered_result.returncode, 0, filtered_result.stderr)
            payload = json.loads(filtered.read_text(encoding="utf-8"))
            self.assertEqual(payload["count"], 0)
            self.assertEqual(payload["duplicate_count"], 1)

    def test_discover_offline_preserves_manual_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / "config.json"
            output = base / "discover.json"
            config.write_text(
                json.dumps(
                    {
                        "days": 7,
                        "linkedin_keywords": [],
                        "workday_sources": [],
                        "board_sources": [],
                        "manual_candidates": ["http://127.0.0.1:9/unreachable"],
                    }
                ),
                encoding="utf-8",
            )
            spec = importlib.util.spec_from_file_location(
                "bole_sources_for_test", ROOT / "scripts/sources.py"
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with mock.patch.object(
                module,
                "jd_url",
                side_effect=module.SourceError("模拟断网 / simulated offline"),
            ):
                code = module.discover(config, None, output)
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["manual_queue"]), 1)
            self.assertEqual(
                payload["manual_queue"][0]["url"],
                "http://127.0.0.1:9/unreachable",
            )


class DataLintTests(unittest.TestCase):
    def test_repository_data_passes(self) -> None:
        result = run_script("ats_lint.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_missing_required_key_reports_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ats = json.loads((ROOT / "data/ats_map.json").read_text(encoding="utf-8"))
            del ats["friendly"]["greenhouse"]["note"]
            ats_path = base / "ats.json"
            ats_path.write_text(json.dumps(ats), encoding="utf-8")
            result = run_script(
                "ats_lint.py",
                "--ats-map",
                ats_path,
                "--salary",
                ROOT / "data/salary_regions.json",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("$.friendly.greenhouse.note", result.stderr)


if __name__ == "__main__":
    unittest.main()
