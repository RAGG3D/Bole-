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
CHINA_JOB_HTML = """<!doctype html>
<html><head>
<meta http-equiv="Content-Type" content="text/html; charset=gb18030">
<title>数据分析师 - 示例科技 | BOSS直聘</title>
</head><body><h1>数据分析师</h1>
<p>负责经营数据分析、SQL 查询和中文业务报告。</p></body></html>"""


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


def load_script_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本模块：{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def run_triage(self, candidates: list[dict], config: dict) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            candidates_path = base / "candidates.json"
            config_path = base / "config.json"
            output_path = base / "buckets.json"
            candidates_path.write_text(
                json.dumps({"generated": "2026-07-25", "days": 7,
                            "count": len(candidates), "candidates": candidates}),
                encoding="utf-8",
            )
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = run_script(
                "triage.py", "--candidates", candidates_path,
                "--config", config_path, "--out", output_path,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(output_path.read_text(encoding="utf-8"))["buckets"]

    def test_triage_manual_bypasses_title_gates(self) -> None:
        buckets = self.run_triage(
            [{"source": "manual", "channel": "url", "title": "Citizen Data Scientist",
              "company": "Example", "id": "", "url": "https://example.test/c"}],
            {"target_titles": [], "target_skills": [],
             "requires_no_citizenship_roles": True},
        )
        self.assertEqual(
            [item["title"] for item in buckets["SCORE"]], ["Citizen Data Scientist"]
        )

    def test_triage_short_skill_needs_word_boundary(self) -> None:
        buckets = self.run_triage(
            [{"source": "board", "channel": "company_boards", "title": "Farm Hand",
              "company": "Example Farms", "id": "9", "url": "https://example.test/9"}],
            {"target_titles": [], "target_skills": ["R"],
             "requires_no_citizenship_roles": True},
        )
        self.assertEqual(len(buckets["SCORE"]), 0, "短技能词必须整词命中")
        self.assertEqual(len(buckets["LIST_other"]), 1)

    def test_triage_redline_only_matches_title(self) -> None:
        buckets = self.run_triage(
            [{"source": "board", "channel": "company_boards", "title": "Data Analyst",
              "company": "DevOps Institute", "id": "8", "url": "https://example.test/8"}],
            {"target_titles": [], "target_skills": [],
             "redline_stack_regex": "DevOps",
             "requires_no_citizenship_roles": True},
        )
        self.assertEqual(len(buckets["SKIP_redline"]), 0, "红线只扫 title，不扫公司名")
        self.assertEqual(len(buckets["LIST_other"]), 1)

    def test_relative_days_parses_yesterday_and_open_ended(self) -> None:
        module = load_script_module("sources")
        self.assertEqual(module.relative_days("Posted Yesterday"), 1)
        self.assertEqual(module.relative_days("Posted 30+ Days Ago"), 30)

    def test_url_channel_decodes_gb18030_and_splits_chinese_title(self) -> None:
        module = load_script_module("sources")
        encoded = CHINA_JOB_HTML.encode("gb18030")
        url = "https://www.zhipin.com/job_detail/example.html"
        with mock.patch.object(
            module, "request_bytes", return_value=(encoded, url)
        ):
            result = module.jd_url(url)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["title"], "数据分析师")
        self.assertEqual(result["company"], "示例科技")
        self.assertIn("负责经营数据分析", result["text"])
        self.assertNotIn("\ufffd", result["text"])

    def test_http_charset_precedes_fallback_decoding(self) -> None:
        module = load_script_module("sources")
        raw = "<p>中文职位详情</p>".encode("gb18030")
        decoded = module.decode_response_body(
            raw, "text/html; charset=GB18030"
        )
        self.assertEqual(decoded, "<p>中文职位详情</p>")

    def test_invalid_http_charset_falls_through_to_html_meta(self) -> None:
        module = load_script_module("sources")
        raw = CHINA_JOB_HTML.encode("gb18030")
        decoded = module.decode_response_body(
            raw, "text/html; charset=not-a-real-codec"
        )
        self.assertIn("负责经营数据分析", decoded)
        self.assertNotIn("\ufffd", decoded)

    def test_chinese_bot_wall_returns_manual_status(self) -> None:
        module = load_script_module("sources")
        markup = "<html><body><div id='geetest'>请完成滑块验证</div></body></html>"
        url = "https://www.zhipin.com/job_detail/walled.html"
        with mock.patch.object(
            module, "request_bytes", return_value=(markup.encode(), url)
        ):
            result = module.jd_url(url)
        self.assertEqual(
            result,
            {"status": "bot_walled", "source": "url", "url": url},
        )

    def test_unsplittable_page_title_does_not_guess(self) -> None:
        module = load_script_module("sources")
        markup = "<html><head><title>招聘详情</title></head><body>职位正文</body></html>"
        url = "https://careers.example.test/job"
        with mock.patch.object(
            module, "request_bytes", return_value=(markup.encode(), url)
        ):
            result = module.jd_url(url)
        self.assertIsNone(result["title"])
        self.assertIsNone(result["company"])

    def test_company_recruiting_title_fallback(self) -> None:
        module = load_script_module("sources")
        self.assertEqual(
            module.split_page_title("示例科技招聘数据分析师_BOSS直聘"),
            ("数据分析师", "示例科技"),
        )

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

    def test_chinese_cover_renders_without_mojibake(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cover = {
                "type": "cover",
                "name": "李示例",
                "contact": {"email": "li.example@example.com"},
                "recipient": "尊敬的招聘团队：",
                "paragraphs": [
                    "我希望申请数据分析师职位。",
                    "我使用 R、Python 和 SQL 交付可复现的数据质量报告。",
                    "我尚未接触贵司特有系统，但已有快速理解业务指标的经验。",
                    "感谢您考虑我的申请。",
                ],
                "closing": "此致",
                "signoff": "李示例",
            }
            source = base / "cover.json"
            target = base / "cover.pdf"
            source.write_text(
                json.dumps(cover, ensure_ascii=False), encoding="utf-8"
            )
            result = run_script(
                "build_docs.py",
                source,
                target,
                "--fit-pages",
                1,
                env={"BOLE_BROWSER_BIN": str(base / "missing-browser")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = target.with_suffix(".html").read_text(encoding="utf-8")
            self.assertIn("我希望申请数据分析师职位", rendered)
            self.assertIn("Noto Sans CJK SC", rendered)
            self.assertIn("Microsoft YaHei", rendered)
            self.assertNotIn("\ufffd", rendered)

    def test_china_manual_flow_contract_is_self_contained(self) -> None:
        scan = (ROOT / ".claude/commands/scan.md").read_text(encoding="utf-8")
        for expected in (
            "有没有想补投的职位链接？任何网站都行，包括中国大陆招聘站",
            "sources.py jd --source url",
            "status=bot_walled",
            "请改贴 JD 全文",
            'facts.language_of_materials',
            "recommended_salary_form.amount",
            "除以 12",
            "BOSS直聘",
        ):
            self.assertIn(expected, scan)

    def test_china_offline_application_pack_chain(self) -> None:
        """模拟 URL→SCORE→裁决→中文材料→README 的 prompt-driven 全链路。"""
        module = load_script_module("sources")
        url = "https://www.zhipin.com/job_detail/chain.html"
        with mock.patch.object(
            module,
            "request_bytes",
            return_value=(CHINA_JOB_HTML.encode("gb18030"), url),
        ):
            jd = module.jd_url(url)
        self.assertEqual(jd["status"], "ok")

        candidate = {
            "source": "manual",
            "channel": "url",
            "title": jd["title"],
            "company": jd["company"],
            "location": "北京",
            "date": None,
            "days_ago": None,
            "in_window": True,
            "id": None,
            "url": url,
            "keyword": None,
        }
        buckets = self.run_triage(
            [candidate],
            {
                "target_titles": ["数据分析师"],
                "target_skills": ["SQL"],
                "requires_no_citizenship_roles": True,
            },
        )
        self.assertEqual(len(buckets["SCORE"]), 1)

        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp) / "示例科技 - 数据分析师"
            content = job / "_content"
            content.mkdir(parents=True)
            (job / "JD.txt").write_text(jd["text"], encoding="utf-8")
            verdict = {
                "jd_key": "示例科技 :: 数据分析师",
                "company": "示例科技",
                "title": "数据分析师",
                "url": url,
                "apply_url": url,
                "fit": 82,
                "decision": "generate",
                "rationale": "SQL 与数据报告事实重合",
                "recommended_salary_form": {
                    "amount": 240000,
                    "currency": "CNY",
                    "includes_super": False,
                },
                "recommended_salary_note": "按 12 薪折算为 20,000 CNY/月",
            }
            (job / "verdict.json").write_text(
                json.dumps(verdict, ensure_ascii=False), encoding="utf-8"
            )
            cover = {
                "type": "cover",
                "name": "李示例",
                "contact": {"email": "li.example@example.com"},
                "recipient": "尊敬的招聘团队：",
                "paragraphs": [
                    "我希望申请数据分析师职位。",
                    "我使用 R、Python 和 SQL 交付可复现的数据质量报告。",
                    "我尚未接触贵司特有系统，但已有快速理解业务指标的经验。",
                    "感谢您考虑我的申请。",
                ],
                "closing": "此致",
                "signoff": "李示例",
            }
            cover_path = content / "cover.json"
            cover_path.write_text(
                json.dumps(cover, ensure_ascii=False), encoding="utf-8"
            )
            redline = run_script(
                "redline_scan.py",
                "--facts",
                ROOT / "examples/demo_facts.json",
                "--content",
                content,
            )
            self.assertEqual(redline.returncode, 0, redline.stdout + redline.stderr)
            built = run_script(
                "build_docs.py",
                cover_path,
                job / "李示例 - Cover Letter - 示例科技.pdf",
                "--fit-pages",
                1,
                env={"BOLE_BROWSER_BIN": str(job / "missing-browser")},
            )
            self.assertEqual(built.returncode, 0, built.stderr)

            readme = (ROOT / "templates/readme_template.md").read_text(
                encoding="utf-8"
            )
            values = {
                "{{TITLE}}": "数据分析师",
                "{{COMPANY}}": "示例科技",
                "{{SUMMARY}}": "中国站手动投递包。",
                "{{FIT}}": "82",
                "{{DECISION}}": "generate",
                "{{RATIONALE}}": verdict["rationale"],
                "{{SALARY}}": "20,000 CNY/月（12 薪基准；13–16 薪另行校准）",
                "{{MATERIALS}}": "- 中文求职信",
                "{{APPLICATION_GUIDE}}": "BOSS直聘需本人沟通，不自动投递。",
                "{{FORM_ANSWERS}}": "- 期望薪资：20,000 CNY/月",
            }
            for marker, value in values.items():
                readme = readme.replace(marker, str(value))
            (job / "README.md").write_text(readme, encoding="utf-8")
            self.assertIn("20,000 CNY/月", readme)
            self.assertIn("本人沟通", readme)
            self.assertNotIn("{{", readme)
            self.assertTrue(
                (job / "李示例 - Cover Letter - 示例科技.html").is_file()
            )

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
            module = load_script_module("sources")
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

    def test_china_ats_and_salary_entries_are_manual_and_monthly(self) -> None:
        ats = json.loads((ROOT / "data/ats_map.json").read_text(encoding="utf-8"))
        for name in ("zhipin", "zhaopin", "51job", "liepin", "lagou"):
            self.assertIn(name, ats["tricky"])
            self.assertIs(ats["tricky"][name]["auto_submit"], False)
        salaries = json.loads(
            (ROOT / "data/salary_regions.json").read_text(encoding="utf-8")
        )
        for region in (
            "CN-Beijing",
            "CN-Shanghai",
            "CN-Shenzhen",
            "CN-Hangzhou",
        ):
            self.assertEqual(salaries[region]["currency"], "CNY")
            self.assertIn("月薪", salaries[region]["salary_note"])
            self.assertIn("/月", salaries[region]["bands"]["mid"])


if __name__ == "__main__":
    unittest.main()
