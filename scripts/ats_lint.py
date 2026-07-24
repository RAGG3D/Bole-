#!/usr/bin/env python3
"""离线校验社区维护的 ATS 能力地图与地区薪资数据。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


class Errors:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, path: str, message: str) -> None:
        self.items.append(f"{path}: {message}")

    def require_key(self, value: Any, key: str, path: str) -> Any:
        if not isinstance(value, dict) or key not in value:
            self.add(f"{path}.{key}", "缺少必填键")
            return None
        return value[key]


def read_json(path: Path, errors: Errors) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.add(str(path), f"无法读取：{exc}")
    except json.JSONDecodeError as exc:
        errors.add(str(path), f"JSON 语法错误：{exc}")
    return None


def lint_ats(value: Any, errors: Errors) -> None:
    if not isinstance(value, dict):
        errors.add("$", "ats_map 顶层必须是对象")
        return
    expected = {"_comment", "friendly", "tricky"}
    for key in sorted(set(value) - expected):
        errors.add(f"$.{key}", "顶层只允许 _comment/friendly/tricky")
    for key in sorted(expected - set(value)):
        errors.add(f"$.{key}", "缺少必填键")
    if not isinstance(value.get("_comment"), str):
        errors.add("$._comment", "必须是字符串")
    for group_name in ("friendly", "tricky"):
        group = value.get(group_name)
        group_path = f"$.{group_name}"
        if not isinstance(group, dict):
            errors.add(group_path, "必须是对象")
            continue
        for name, entry in group.items():
            path = f"{group_path}.{name}"
            if not isinstance(entry, dict):
                errors.add(path, "平台条目必须是对象")
                continue
            domains = errors.require_key(entry, "domains", path)
            auto_submit = errors.require_key(entry, "auto_submit", path)
            note = errors.require_key(entry, "note", path)
            if not isinstance(domains, list) or not domains:
                errors.add(f"{path}.domains", "必须是非空数组")
            else:
                for index, domain in enumerate(domains):
                    domain_path = f"{path}.domains[{index}]"
                    if not isinstance(domain, str) or not domain:
                        errors.add(domain_path, "必须是非空字符串")
                    elif (
                        "://" in domain
                        or "/" in domain
                        or ":" in domain
                        or domain != domain.lower()
                        or not DOMAIN.fullmatch(domain)
                    ):
                        errors.add(
                            domain_path,
                            "必须是小写裸域名，不含 scheme、斜杠或端口",
                        )
            if type(auto_submit) is not bool:
                errors.add(f"{path}.auto_submit", "必须是 bool")
            if not isinstance(note, str) or not note.strip():
                errors.add(f"{path}.note", "必须是非空字符串")
            if "quirks" in entry and (
                not isinstance(entry["quirks"], list)
                or not all(isinstance(item, str) for item in entry["quirks"])
            ):
                errors.add(f"{path}.quirks", "可选字段必须是字符串数组")


def lint_salary(value: Any, errors: Errors) -> None:
    if not isinstance(value, dict):
        errors.add("$", "salary_regions 顶层必须是对象")
        return
    if not isinstance(value.get("_comment"), str):
        errors.add("$._comment", "必须是字符串")
    regions = [key for key in value if key != "_comment"]
    if not regions:
        errors.add("$", "至少需要一个地区条目")
    for region in regions:
        entry = value[region]
        path = f"$.{region}"
        if not isinstance(entry, dict):
            errors.add(path, "地区条目必须是对象")
            continue
        currency = errors.require_key(entry, "currency", path)
        salary_note = errors.require_key(entry, "salary_note", path)
        bands = errors.require_key(entry, "bands", path)
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            errors.add(f"{path}.currency", "必须是三位大写币种代码")
        if not isinstance(salary_note, str):
            errors.add(f"{path}.salary_note", "必须是字符串")
        if not isinstance(bands, dict):
            errors.add(f"{path}.bands", "必须是对象")
            continue
        for band in ("junior", "mid", "senior"):
            if not isinstance(bands.get(band), str) or not bands.get(band):
                errors.add(f"{path}.bands.{band}", "缺少非空薪资区间")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Bole 社区 JSON 数据")
    parser.add_argument(
        "--ats-map", type=Path, default=ROOT / "data/ats_map.json"
    )
    parser.add_argument(
        "--salary", type=Path, default=ROOT / "data/salary_regions.json"
    )
    args = parser.parse_args()
    all_errors: list[str] = []
    ats_errors = Errors()
    lint_ats(read_json(args.ats_map, ats_errors), ats_errors)
    all_errors.extend(f"{args.ats_map}:{item}" for item in ats_errors.items)
    salary_errors = Errors()
    lint_salary(read_json(args.salary, salary_errors), salary_errors)
    all_errors.extend(f"{args.salary}:{item}" for item in salary_errors.items)
    if all_errors:
        for item in all_errors:
            print(f"错误：{item}", file=sys.stderr)
        print(f"校验失败：{len(all_errors)} 个问题。", file=sys.stderr)
        return 1
    print("PASS：ats_map.json 与 salary_regions.json schema 合法。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
