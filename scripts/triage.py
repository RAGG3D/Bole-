#!/usr/bin/env python3
"""在抓取全文 JD 之前，只按 title(+company) 做机械分诊。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_SENIOR = (
    r"\b(?:senior|lead|principal|staff|head|director|chief|manager|architect|founding)\b"
)
DEFAULT_GOVERNMENT = (
    r"\b(?:graduate\s+program|traineeship|australian\s+public\s+service|APS)\b"
)


def safe_regex(pattern: object, label: str) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(str(pattern), re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{label} 不是有效正则：{exc}") from exc


def positive_pattern(config: dict[str, Any]) -> re.Pattern[str] | None:
    terms: list[str] = []
    for key in ("target_titles", "target_skills"):
        values = config.get(key, [])
        if isinstance(values, list):
            terms.extend(str(value).strip() for value in values if str(value).strip())
    if not terms:
        return None
    return re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)


def user_requires_no_citizenship(config_path: Path, config: dict[str, Any]) -> bool:
    if "requires_no_citizenship_roles" in config:
        return bool(config["requires_no_citizenship_roles"])
    facts_path = config_path.with_name("facts.json")
    try:
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        return bool(facts.get("basics", {}).get("requires_no_citizenship_roles", True))
    except (OSError, json.JSONDecodeError, AttributeError):
        return True


def dual_band_title(title: str) -> bool:
    """例如 Data Analyst / Senior Data Analyst 不应在取 JD 前被封顶。"""
    if not re.search(r"[/|]", title):
        return False
    parts = re.split(r"\s*[/|]\s*", title)
    senior = re.compile(DEFAULT_SENIOR, re.IGNORECASE)
    return any(senior.search(part) for part in parts) and any(
        part.strip() and not senior.search(part) for part in parts
    )


def bucket_candidates(
    candidates_path: Path, config_path: Path, output_path: Path
) -> int:
    envelope = json.loads(candidates_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    candidates = envelope.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("候选文件缺少 candidates 数组")

    eligibility = safe_regex(
        config.get(
            "eligibility_regex",
            r"citizen|permanent resident|security clearance|NV1|NV2|baseline",
        ),
        "eligibility_regex",
    )
    redline = safe_regex(config.get("redline_stack_regex", ""), "redline_stack_regex")
    positive = positive_pattern(config)
    senior = re.compile(DEFAULT_SENIOR, re.IGNORECASE)
    government = re.compile(DEFAULT_GOVERNMENT, re.IGNORECASE)
    restrict_eligibility = user_requires_no_citizenship(config_path, config)
    buckets: dict[str, list[dict[str, Any]]] = {
        "SKIP_eligibility": [],
        "SKIP_redline": [],
        "LIST_senior": [],
        "SCORE": [],
        "LIST_other": [],
    }

    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        candidate = dict(raw)
        title = str(candidate.get("title") or "")
        company = str(candidate.get("company") or "")
        haystack = f"{title} {company}".strip()
        positive_hit = bool(positive and positive.search(haystack))
        if restrict_eligibility and (
            (eligibility and eligibility.search(haystack)) or government.search(haystack)
        ):
            bucket = "SKIP_eligibility"
            reason = "标题或公司命中资格/政府项目机械闸门"
        elif redline and redline.search(haystack) and not positive_hit:
            bucket = "SKIP_redline"
            reason = "标题命中红线技术且没有正向轮辐词"
        elif candidate.get("source") == "manual":
            bucket = "SCORE"
            reason = "用户手动指定，直接进入全文打分"
        elif senior.search(title) and not dual_band_title(title):
            bucket = "LIST_senior"
            reason = "标题命中资深/管理封顶词"
        elif positive_hit:
            bucket = "SCORE"
            reason = "命中目标职位或技能轮辐词"
        else:
            bucket = "LIST_other"
            reason = "未命中目标轮辐词"
        candidate["triage_reason"] = reason
        buckets[bucket].append(candidate)

    result = {
        "generated": envelope.get("generated"),
        "days": envelope.get("days"),
        "count": sum(len(items) for items in buckets.values()),
        "buckets": buckets,
        "counts": {name: len(items) for name, items in buckets.items()},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, items in buckets.items():
        print(f"{name} ({len(items)})")
        for item in items:
            print(f"  - {item.get('company') or '?'} :: {item.get('title') or '?'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bole 职位机械分诊（不读取 JD 全文）")
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        return bucket_candidates(args.candidates, args.config, args.out)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
