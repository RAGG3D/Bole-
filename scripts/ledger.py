#!/usr/bin/env python3
"""Bole 已见职位台账：双键去重与提交。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LEDGER = Path("state/seen_jobs.json")


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def candidate_keys(candidate: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    job_id = str(candidate.get("id") or "").strip()
    if candidate.get("source") == "linkedin" and job_id:
        keys.add(f"linkedin:{job_id}")
    company = normalize(candidate.get("company"))
    title = normalize(candidate.get("title"))
    if company and title:
        keys.add(f"name:{company}|{title}")
    return keys


def read_candidates(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise ValueError("候选文件必须符合 §6.2：顶层对象含 candidates 数组")
    candidates = [item for item in data["candidates"] if isinstance(item, dict)]
    return data, candidates


def read_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "jobs": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError(f"台账格式错误：{path}")
    return data


def filter_candidates(source: Path, output: Path, ledger_path: Path) -> int:
    envelope, candidates = read_candidates(source)
    ledger = read_ledger(ledger_path)
    seen = {
        key
        for record in ledger["jobs"]
        if isinstance(record, dict)
        for key in record.get("keys", [])
        if isinstance(key, str)
    }
    fresh: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    batch_seen: set[str] = set()
    for candidate in candidates:
        keys = candidate_keys(candidate)
        if keys and (keys & seen or keys & batch_seen):
            duplicates.append(candidate)
            continue
        fresh.append(candidate)
        batch_seen.update(keys)
    result = dict(envelope)
    result.update(
        {
            "count": len(fresh),
            "candidates": fresh,
            "duplicate_count": len(duplicates),
            "duplicates": duplicates,
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"新职位 {len(fresh)} 个；已见/本轮重复 {len(duplicates)} 个。")
    return 0


def commit_candidates(source: Path, ledger_path: Path) -> int:
    _, candidates = read_candidates(source)
    ledger = read_ledger(ledger_path)
    existing: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for record in ledger["jobs"]:
        if not isinstance(record, dict):
            continue
        keys = record.get("keys", [])
        if keys:
            for key in keys:
                existing[str(key)] = record
        else:
            unkeyed.append(record)

    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for candidate in candidates:
        keys = sorted(candidate_keys(candidate))
        if keys and any(key in existing for key in keys):
            continue
        record = {
            "keys": keys,
            "first_seen": now,
            "source": candidate.get("source"),
            "id": candidate.get("id"),
            "company": candidate.get("company"),
            "title": candidate.get("title"),
            "location": candidate.get("location"),
            "url": candidate.get("url"),
        }
        if keys:
            for key in keys:
                existing[key] = record
        else:
            unkeyed.append(record)
        added += 1

    unique: list[dict[str, Any]] = []
    seen_objects: set[int] = set()
    for record in [*existing.values(), *unkeyed]:
        marker = id(record)
        if marker not in seen_objects:
            unique.append(record)
            seen_objects.add(marker)
    unique.sort(key=lambda item: str(item.get("first_seen", "")))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps({"version": 1, "jobs": unique}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"已向台账写入 {added} 个职位；台账共 {len(unique)} 个。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bole 已见职位去重台账")
    sub = parser.add_subparsers(dest="command", required=True)
    filter_parser = sub.add_parser("filter", help="滤掉已见职位")
    filter_parser.add_argument("--candidates", required=True, type=Path)
    filter_parser.add_argument("--out", required=True, type=Path)
    filter_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    commit_parser = sub.add_parser("commit", help="把本轮全部候选写入台账")
    commit_parser.add_argument("--candidates", required=True, type=Path)
    commit_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    try:
        if args.command == "filter":
            return filter_candidates(args.candidates, args.out, args.ledger)
        return commit_candidates(args.candidates, args.ledger)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
