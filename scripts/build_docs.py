#!/usr/bin/env python3
"""把 Bole 的 cv.json / cover.json 渲染为 HTML，并尽力打印为 PDF。"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
BROWSER_CANDIDATES = (
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "msedge",
)
BROWSER_PATHS = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
)


class BuildError(ValueError):
    """输入材料不符合约定。"""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"无法读取 JSON：{path}（{exc}）") from exc
    if not isinstance(value, dict):
        raise BuildError("材料 JSON 顶层必须是对象")
    return value


def inline(value: object) -> str:
    """转义 HTML，并只支持 **加粗** 这一种内联标记。"""
    escaped = html.escape(str(value or ""))
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def contact_line(contact: object) -> str:
    if not isinstance(contact, dict):
        return ""
    order = ("address", "phone", "email", "linkedin", "github", "portfolio")
    values = [inline(contact.get(key)) for key in order if contact.get(key)]
    return " &nbsp;·&nbsp; ".join(values)


def require_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BuildError(f"缺少必填字符串：{key}")
    return value.strip()


def render_cv(data: dict[str, Any], zoom: float) -> str:
    name = require_text(data, "name")
    sections = data.get("sections")
    if not isinstance(sections, list):
        raise BuildError("cv.sections 必须是数组")

    section_html: list[str] = []
    for s_index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise BuildError(f"cv.sections[{s_index}] 必须是对象")
        heading = inline(section.get("heading"))
        entries = section.get("entries", [])
        if not isinstance(entries, list):
            raise BuildError(f"cv.sections[{s_index}].entries 必须是数组")
        rendered_entries: list[str] = []
        for e_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise BuildError(
                    f"cv.sections[{s_index}].entries[{e_index}] 必须是对象"
                )
            bullets = entry.get("bullets", [])
            if not isinstance(bullets, list):
                raise BuildError(
                    f"cv.sections[{s_index}].entries[{e_index}].bullets 必须是数组"
                )
            bullet_html = "".join(f"<li>{inline(item)}</li>" for item in bullets)
            rendered_entries.append(
                '<div class="entry">'
                '<div class="entry-head"><span>'
                f"{inline(entry.get('role'))}"
                + (
                    f' <span class="entry-org">— {inline(entry.get("org"))}</span>'
                    if entry.get("org")
                    else ""
                )
                + f'</span><span class="meta">{inline(entry.get("meta"))}</span></div>'
                + (f"<ul>{bullet_html}</ul>" if bullet_html else "")
                + "</div>"
            )
        section_html.append(
            f"<section><h2>{heading}</h2>{''.join(rendered_entries)}</section>"
        )

    template = (TEMPLATES / "cv_template.html").read_text(encoding="utf-8")
    replacements = {
        "{{TITLE}}": inline(f"{name} - CV"),
        "{{ZOOM}}": f"{zoom:.2f}",
        "{{NAME}}": inline(name),
        "{{SUBTITLE}}": inline(data.get("subtitle")),
        "{{CONTACT}}": contact_line(data.get("contact")),
        "{{PROFILE}}": inline(data.get("profile")),
        "{{SECTIONS}}": "".join(section_html),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def render_cover(data: dict[str, Any], zoom: float) -> str:
    name = require_text(data, "name")
    paragraphs = data.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise BuildError("cover.paragraphs 必须是非空数组")
    template = (TEMPLATES / "cover_template.html").read_text(encoding="utf-8")
    replacements = {
        "{{TITLE}}": inline(f"{name} - Cover Letter"),
        "{{ZOOM}}": f"{zoom:.2f}",
        "{{NAME}}": inline(name),
        "{{CONTACT}}": contact_line(data.get("contact")),
        "{{RECIPIENT}}": inline(data.get("recipient") or "Dear Hiring Team,"),
        "{{PARAGRAPHS}}": "".join(f"<p>{inline(p)}</p>" for p in paragraphs),
        "{{CLOSING}}": inline(data.get("closing") or "Yours sincerely,"),
        "{{SIGNOFF}}": inline(data.get("signoff") or name),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def render(data: dict[str, Any], zoom: float) -> str:
    kind = data.get("type")
    if kind == "cv":
        return render_cv(data, zoom)
    if kind == "cover":
        return render_cover(data, zoom)
    raise BuildError("type 必须是 cv 或 cover")


def find_browser() -> str | None:
    override = os.environ.get("BOLE_BROWSER_BIN")
    if override:
        return override if Path(override).exists() or shutil.which(override) else None
    for candidate in BROWSER_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    for candidate in BROWSER_PATHS:
        if candidate.is_file():
            return str(candidate)
    return None


def pdf_pages(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    return len(re.findall(rb"/Type\s*/Page\b", raw))


def print_pdf(browser: str, html_path: Path, pdf_path: Path) -> tuple[bool, str]:
    command = [
        browser,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={pdf_path.resolve()}",
        html_path.resolve().as_uri(),
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0 or not pdf_path.is_file():
        detail = (result.stderr or result.stdout).strip()
        return False, detail[-500:] or f"浏览器退出码 {result.returncode}"
    return True, ""


def build(input_path: Path, output_path: Path, fit_pages: int) -> int:
    data = load_json(input_path)
    if output_path.suffix.lower() != ".pdf":
        output_path = output_path.with_suffix(".pdf")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html_path = output_path.with_suffix(".html")
    browser = find_browser()
    zoom = 1.0

    while True:
        html_path.write_text(render(data, zoom), encoding="utf-8")
        if browser is None:
            print(
                f"未找到可用浏览器；已保留 HTML：{html_path}。"
                "请用浏览器打开后按 Ctrl+P 另存为 PDF。"
            )
            return 0
        ok, detail = print_pdf(browser, html_path, output_path)
        if not ok:
            print(
                f"浏览器未能生成 PDF（{detail}）；已保留 HTML：{html_path}。"
                "请用浏览器打开后按 Ctrl+P 另存为 PDF。"
            )
            return 0
        pages = pdf_pages(output_path)
        if fit_pages <= 0 or pages <= fit_pages or zoom < 0.75:
            print(f"OK {output_path} ({pages or '?'} pages) [zoom {zoom:.2f}]")
            return 0
        zoom = round(zoom - 0.05, 2)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把 Bole 材料 JSON 生成 HTML/PDF")
    parser.add_argument("input", type=Path, help="cv.json 或 cover.json")
    parser.add_argument("output", type=Path, help="目标 PDF 路径")
    parser.add_argument(
        "--fit-pages",
        type=int,
        default=0,
        metavar="N",
        help="逐步缩放，尽量控制在 N 页以内",
    )
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        return build(args.input, args.output, args.fit_pages)
    except BuildError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
