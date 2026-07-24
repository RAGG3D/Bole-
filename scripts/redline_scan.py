#!/usr/bin/env python3
"""对 Bole 生成材料执行确定性的红线扫描。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(item, f"{path}.{key}")


def term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip())
    left = r"(?<!\w)" if term and term[0].isalnum() else ""
    right = r"(?!\w)" if term and term[-1].isalnum() else ""
    return re.compile(left + escaped + right, re.IGNORECASE)


def known_technology(facts: dict[str, Any]) -> set[str]:
    known: set[str] = set()
    skills = facts.get("skills", {})
    if isinstance(skills, dict):
        for values in skills.values():
            if isinstance(values, list):
                known.update(str(item).casefold() for item in values)
    for experience in facts.get("experiences", []):
        if isinstance(experience, dict):
            tech = experience.get("tech", [])
            if isinstance(tech, list):
                known.update(str(item).casefold() for item in tech)
    return known


def scan(facts_path: Path, content_path: Path) -> int:
    try:
        facts = load_json(facts_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取事实台账 {facts_path}：{exc}", file=sys.stderr)
        return 2
    if not content_path.exists():
        print(f"错误：材料路径不存在：{content_path}", file=sys.stderr)
        return 2
    files = (
        sorted(content_path.rglob("*.json"))
        if content_path.is_dir()
        else [content_path]
    )
    if not files:
        print(f"错误：没有找到待扫描的 JSON：{content_path}", file=sys.stderr)
        return 2

    red_lines = facts.get("red_lines", [])
    if not isinstance(red_lines, list):
        print("错误：facts.red_lines 必须是数组", file=sys.stderr)
        return 2
    patterns = [(str(term), term_pattern(str(term))) for term in red_lines if str(term)]
    hits: list[str] = []
    warnings: list[str] = []
    known = known_technology(facts)
    jargon_pattern = re.compile(
        r"\b(?:[A-Z][A-Z0-9+#.-]{1,}|[A-Z][a-z]+[A-Z][A-Za-z0-9]*|[A-Z]\+\+)\b"
    )
    ignored = {
        "cv",
        "dear",
        "experience",
        "education",
        "technical",
        "skills",
        "profile",
        "github",
        "linkedin",
    }

    for file_path in files:
        try:
            material = load_json(file_path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"错误：无法读取材料 {file_path}：{exc}", file=sys.stderr)
            return 2
        for json_path, text in strings(material):
            for term, pattern in patterns:
                if pattern.search(text):
                    hits.append(f"{file_path}:{json_path} 命中红线「{term}」")
            for token in jargon_pattern.findall(text):
                folded = token.casefold().strip(".")
                if folded not in known and folded not in ignored and len(token) > 1:
                    warnings.append(
                        f"{file_path}:{json_path} 台账外专名候选「{token}」，请人工复核"
                    )

    combined = "\n".join(
        text for file_path in files for _, text in strings(load_json(file_path))
    )
    for rule in facts.get("phrasing_rules", []):
        rule_text = str(rule)
        if (
            re.search(r"R.*Python.*前", rule_text, re.IGNORECASE)
            and re.search(r"\bPython\b", combined, re.IGNORECASE)
            and re.search(r"\bR\b", combined)
        ):
            first_r = re.search(r"\bR\b", combined)
            first_python = re.search(r"\bPython\b", combined, re.IGNORECASE)
            if first_r and first_python and first_python.start() < first_r.start():
                warnings.append("phrasing_rules 警告：材料中 Python 首次出现早于 R")

    for warning in dict.fromkeys(warnings):
        print(f"WARNING: {warning}")
    if hits:
        for hit in dict.fromkeys(hits):
            print(f"REDLINE: {hit}")
        print(f"扫描失败：共命中 {len(set(hits))} 条红线。", file=sys.stderr)
        return 1
    print(f"PASS：已扫描 {len(files)} 个材料文件，未命中红线。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描生成材料中的事实红线")
    parser.add_argument("--facts", required=True, type=Path)
    parser.add_argument("--content", required=True, type=Path)
    args = parser.parse_args()
    return scan(args.facts, args.content)


if __name__ == "__main__":
    raise SystemExit(main())
