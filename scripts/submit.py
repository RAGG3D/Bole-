#!/usr/bin/env python3
"""Bole 与 OpenClaw 的单点桥接、协议解析和投递记账。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATS_MAP = ROOT / "data/ats_map.json"
DEFAULT_CONFIG = Path("profile/config.json")
DEFAULT_FACTS = Path("profile/facts.json")
DEFAULT_SUBMISSIONS = Path("state/submissions.json")
RESULT_PATTERN = re.compile(
    r"^RESULT: (SUBMITTED|NEED|BLOCKED|FAILED)(?:\s*\|\s*(.*))?$"
)
VERIFY_PATTERN = re.compile(
    r"^VERIFY: (SUBMITTED|NOT_SUBMITTED|UNKNOWN)(?:\s*\|\s*(.*))?$"
)


class SubmitError(RuntimeError):
    pass


def submissions_path() -> Path:
    return Path(os.environ.get("BOLE_SUBMISSIONS_FILE", str(DEFAULT_SUBMISSIONS)))


def ats_map_path() -> Path:
    return Path(os.environ.get("BOLE_ATS_MAP", str(DEFAULT_ATS_MAP)))


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubmitError(f"无法读取{label} {path}：{exc}") from exc
    if not isinstance(value, dict):
        raise SubmitError(f"{label}顶层必须是对象：{path}")
    return value


def load_verdict(job: Path) -> dict[str, Any]:
    verdict_path = job / "verdict.json"
    if not verdict_path.is_file():
        raise SubmitError(f"缺 verdict.json，请重跑 /scan：{verdict_path}")
    verdict = load_object(verdict_path, "裁决")
    for key in ("jd_key", "company", "title", "url"):
        if not isinstance(verdict.get(key), str) or not verdict[key].strip():
            raise SubmitError(f"verdict.json 缺少必填字段：{key}")
    return verdict


def load_submissions() -> dict[str, Any]:
    path = submissions_path()
    if not path.exists():
        return {"version": 1, "submissions": []}
    value = load_object(path, "投递台账")
    if not isinstance(value.get("submissions"), list):
        raise SubmitError("state/submissions.json 缺少 submissions 数组")
    return value


def save_submissions(data: dict[str, Any]) -> None:
    path = submissions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(
        prefix=".submissions-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def find_entry(data: dict[str, Any], jd_key: str) -> dict[str, Any] | None:
    for entry in data["submissions"]:
        if isinstance(entry, dict) and entry.get("jd_key") == jd_key:
            return entry
    return None


def parse_fields(detail: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in re.split(r"\s*\|\s*", detail):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def protocol_line(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def invoke_openclaw(
    message: str, thread: str | None = None, timeout: float = 600
) -> tuple[str, str]:
    """文件中唯一允许与 OpenClaw 通信的函数。返回(kind, stdout/detail)。"""
    binary = os.environ.get("BOLE_OPENCLAW_BIN", "openclaw")
    command = [binary]
    if thread is not None:
        command.extend(["--thread", thread])
    try:
        result = subprocess.run(
            command,
            input=message,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "UNKNOWN", "OpenClaw 超时；禁止自动重试，必须先 verify"
    except OSError as exc:
        return "UNKNOWN", f"OpenClaw 连接/启动失败：{exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return "UNKNOWN", f"OpenClaw 非零退出：{detail[-500:]}"
    return "OUTPUT", result.stdout


def match_ats(url: str, mapping: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    hostname = (urlparse(url).hostname or "").casefold()
    hits: list[tuple[int, str, dict[str, Any]]] = []
    for group_name in ("friendly", "tricky"):
        group = mapping.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for name, entry in group.items():
            if not isinstance(entry, dict):
                continue
            for domain in entry.get("domains", []):
                domain_text = str(domain)
                if hostname == domain_text or hostname.endswith("." + domain_text):
                    hits.append((len(domain_text), name, entry))
    if not hits:
        return None
    _, name, entry = max(hits, key=lambda item: item[0])
    return name, entry


def slug_for(jd_key: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", jd_key).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")
    if not slug:
        slug = "job-" + hashlib.sha256(jd_key.encode()).hexdigest()[:10]
    return slug[:64]


def new_thread(jd_key: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"bole-{slug_for(jd_key)}-{stamp}"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def materials(job: Path) -> tuple[Path, Path]:
    pdfs = sorted(job.glob("*.pdf"))
    cv = next((path for path in pdfs if re.search(r"\bcv\b", path.name, re.I)), None)
    cover = next(
        (path for path in pdfs if re.search(r"cover(?:\s+letter)?", path.name, re.I)),
        None,
    )
    if cv is None or cover is None or not (job / "README.md").is_file():
        raise SubmitError("材料不齐：需要 CV PDF、Cover Letter PDF 和 README.md")
    return cv.resolve(), cover.resolve()


def ensure_no_redlines(job: Path, facts: dict[str, Any]) -> None:
    content = job / "_content"
    if not content.is_dir():
        raise SubmitError("缺少 _content/，无法投前复核红线；请重跑 /scan")
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(content.glob("*.json"))
    )
    for raw in facts.get("red_lines", []):
        term = str(raw).strip()
        if not term:
            continue
        left = r"(?<!\w)" if term[0].isalnum() else ""
        right = r"(?!\w)" if term[-1].isalnum() else ""
        if re.search(left + re.escape(term) + right, combined, re.I):
            raise SubmitError(f"投前红线复核失败：材料命中「{term}」")


def salary_answer(
    verdict: dict[str, Any], config: dict[str, Any]
) -> tuple[Any, str, bool] | None:
    form = verdict.get("recommended_salary_form", {})
    if not isinstance(form, dict):
        form = {}
    amount = form.get("amount")
    currency = str(form.get("currency") or "")
    includes_super = bool(form.get("includes_super", True))
    if not isinstance(amount, (int, float)) or amount <= 0:
        fallback = config.get("salary_expectation", {})
        if isinstance(fallback, dict):
            amount = fallback.get("amount")
            currency = str(fallback.get("currency") or currency)
            includes_super = bool(fallback.get("includes_super", includes_super))
    if not isinstance(amount, (int, float)) or amount <= 0:
        return None
    return int(amount), currency, includes_super


def task_message(
    verdict: dict[str, Any],
    config: dict[str, Any],
    facts: dict[str, Any],
    ats_name: str,
    ats_entry: dict[str, Any],
    cv: Path,
    cover: Path,
) -> str:
    url = str(verdict.get("apply_url") or verdict.get("url"))
    basics = facts.get("basics", {}) if isinstance(facts.get("basics"), dict) else {}
    quick: list[str] = []
    if basics.get("work_rights"):
        quick.append(f"- 工作权利：{basics['work_rights']}")
    if basics.get("notice_period"):
        quick.append(f"- 通知期：{basics['notice_period']}")
    quick.append("- 如何得知职位：LinkedIn")
    salary = salary_answer(verdict, config)
    if salary:
        amount, currency, includes_super = salary
        quick.append(
            f"- 期望薪资：{amount} {currency}，"
            + ("含 super" if includes_super else "不含 super")
        )
    quirks = ats_entry.get("quirks", [])
    if any(
        re.search(r"出生日期|date of birth|\bdob\b", str(quirk), re.I)
        for quirk in quirks
    ) and basics.get("date_of_birth"):
        quick.append(f"- 出生日期：{basics['date_of_birth']}")
    quirks_text = "\n".join(f"- {item}" for item in quirks) or "- 无"
    return f"""你是 Bole 的浏览器投递代理。严格按以下顺序和边界完成一份投递。

1. 目标
- URL：{url}
- 公司：{verdict.get('company')}
- 职位：{verdict.get('title')}

2. 材料
- CV：{cv}
- Cover Letter：{cover}
必须上传这两个指定文件，绝不使用平台已存储的旧简历；简历解析回填的字段要逐一核对并改回定制内容。

3. 表单速查答案
{chr(10).join(quick)}
以上答案全部来自事实台账、配置或裁决。没有列出的答案不许自己发挥。

4. ATS：{ats_name}；已知 quirks
{quirks_text}

5. 行为红线
遇验证码/在线测评/视频面试/性格测试，立即停止并报 BLOCKED（对应 reason）。
站点只提供 Google/LinkedIn OAuth 一键登录/注册，报 BLOCKED oauth_register。
机器人墙报 BLOCKED bot_wall。
表单要求登录、会话失效、或出现任何“设置密码/输入密码”字段，报 NEED | what=login；绝不填写注册表单、绝不创建或输入密码。
绝不在浏览器打开 linkedin.com 岗位页。
表单出现速查答案之外的问题，不许编造，报 NEED。
核实状态时走权威页面（application 列表/确认页），不要依赖详情页懒加载渲染的文本。

6. 回复协议
最后必须输出恰好一行，且只能是以下格式之一：
RESULT: SUBMITTED | evidence=<确认编号或确认页原文摘录>
RESULT: NEED | what=<otp|dob|login|salary|file|answer> | question=<表单原文>
RESULT: BLOCKED | reason=<captcha|assessment|video|oauth_register|bot_wall> | detail=<...>
RESULT: FAILED | detail=<...>
"""


def verify_message(verdict: dict[str, Any]) -> str:
    return f"""只读核实 Bole 投递状态，绝不点击提交或新建申请。
公司：{verdict.get('company')}
职位：{verdict.get('title')}
投递 URL：{verdict.get('apply_url') or verdict.get('url')}
请通过 ATS application 列表、确认页 URL 或确认邮件等权威通道核实；不要依赖详情页懒加载文本。
最后必须输出恰好一行：
VERIFY: SUBMITTED | evidence=<...>
VERIFY: NOT_SUBMITTED | progress=<step_advanced|fields_saved|none> | detail=<当前所在步骤>
VERIFY: UNKNOWN
"""


def add_attempt(
    entry: dict[str, Any], action: str, result: str, detail: str
) -> None:
    entry.setdefault("attempts", []).append(
        {"ts": timestamp(), "action": action, "result": result, "detail": detail}
    )


def apply_result(
    entry: dict[str, Any], action: str, kind: str, payload: str
) -> str:
    if kind == "UNKNOWN":
        line = "RESULT: UNKNOWN"
        entry["status"] = "unknown"
        add_attempt(entry, action, "UNKNOWN", payload)
        return line
    line = protocol_line(payload)
    match = RESULT_PATTERN.fullmatch(line)
    if not match:
        entry["status"] = "unknown"
        add_attempt(entry, action, "UNKNOWN", "末行不符合 RESULT 协议")
        return "RESULT: UNKNOWN"
    result = match.group(1)
    fields = parse_fields(match.group(2) or "")
    if result == "SUBMITTED":
        evidence = fields.get("evidence", "")
        if not evidence:
            # 代理声称已投但没带证据：不能当 failed（会放行重投造成双投），按未知处理走 verify
            entry["status"] = "unknown"
            add_attempt(
                entry, action, "UNKNOWN", "代理声称 SUBMITTED 但缺 evidence，需 verify 权威核实"
            )
            return "RESULT: UNKNOWN"
        entry["status"] = "submitted"
        entry["evidence"] = evidence
    elif result == "NEED":
        entry["status"] = "needs_user"
    elif result == "BLOCKED":
        entry["status"] = "blocked"
    else:
        entry["status"] = "failed"
    add_attempt(entry, action, result, match.group(2) or "")
    if result == "FAILED":
        recent = entry.get("attempts", [])[-2:]
        if len(recent) == 2 and all(
            attempt.get("result") == "FAILED" for attempt in recent
        ):
            entry["status"] = "manual"
    return line


def apply_verify(entry: dict[str, Any], kind: str, payload: str) -> str:
    if kind == "UNKNOWN":
        entry["status"] = "unknown"
        add_attempt(entry, "verify", "UNKNOWN", payload)
        return "VERIFY: UNKNOWN"
    line = protocol_line(payload)
    match = VERIFY_PATTERN.fullmatch(line)
    if not match:
        entry["status"] = "unknown"
        add_attempt(entry, "verify", "UNKNOWN", "末行不符合 VERIFY 协议")
        return "VERIFY: UNKNOWN"
    result = match.group(1)
    fields = parse_fields(match.group(2) or "")
    if result == "SUBMITTED":
        evidence = fields.get("evidence", "")
        if evidence:
            entry["status"] = "submitted"
            entry["evidence"] = evidence
        else:
            entry["status"] = "unknown"
            result = "UNKNOWN"
            line = "VERIFY: UNKNOWN"
    elif result == "NOT_SUBMITTED":
        entry["status"] = "needs_user"
    else:
        entry["status"] = "unknown"
    add_attempt(entry, "verify", result, match.group(2) or "")
    if result == "NOT_SUBMITTED":
        recent = entry.get("attempts", [])[-2:]
        if len(recent) == 2 and all(
            attempt.get("action") == "verify"
            and attempt.get("result") == "NOT_SUBMITTED"
            and parse_fields(str(attempt.get("detail") or "")).get("progress")
            == "none"
            for attempt in recent
        ):
            entry["status"] = "manual"
    return line


def base_entry(
    verdict: dict[str, Any], ats_name: str, thread: str | None
) -> dict[str, Any]:
    return {
        "jd_key": verdict["jd_key"],
        "ats": ats_name,
        "url": verdict["url"],
        "apply_url": verdict.get("apply_url"),
        # 默认 unknown：桥接进程若中途死亡，台账停在 unknown 会被去重铁则拦住，必须先 verify
        "status": "unknown",
        "evidence": "",
        "thread": thread,
        "attempts": [],
    }


def require_auto_submit(config: dict[str, Any]) -> dict[str, Any]:
    auto = config.get("auto_submit", {})
    if not isinstance(auto, dict) or auto.get("enabled") is not True:
        raise SubmitError(
            "自动投递未开启；请先通过 /apply 开通并将 config.auto_submit.enabled 设为 true"
        )
    return auto


def replace_or_add(data: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """合并进台账并返回权威 dict；attempts 追加式保留历史，evidence 不被空值抹掉。"""
    previous = find_entry(data, entry["jd_key"])
    if previous is None:
        data["submissions"].append(entry)
        return entry
    entry["attempts"] = previous.get("attempts", []) + entry.get("attempts", [])
    if not entry.get("evidence"):
        entry["evidence"] = previous.get("evidence", "")
    previous.clear()
    previous.update(entry)
    return previous


def run_job(
    job: Path, config_path: Path, facts_path: Path, force: bool
) -> int:
    verdict = load_verdict(job)
    config = load_object(config_path, "配置")
    facts = load_object(facts_path, "事实台账")
    auto = require_auto_submit(config)
    data = load_submissions()
    previous = find_entry(data, verdict["jd_key"])
    if (
        previous
        and previous.get("status") in {"submitted", "unknown"}
        and not force
    ):
        raise SubmitError(
            f"拒绝重复投递：{verdict['jd_key']} 已是 {previous.get('status')}。"
            "如确知需要重投可用 --force，但有双投风险。"
        )
    if verdict.get("jd_completeness") == "stub":
        entry = base_entry(verdict, "unknown", None)
        entry["status"] = "manual"
        add_attempt(entry, "submit", "FAILED", "JD 为 stub，投前防线拦下")
        entry = replace_or_add(data, entry)
        save_submissions(data)
        raise SubmitError("JD 仍为 stub；必须先抓完整 JD 并重跑资格/红线裁决")
    target_url = str(verdict.get("apply_url") or verdict.get("url"))
    hostname = (urlparse(target_url).hostname or "").casefold()
    if hostname == "linkedin.com" or hostname.endswith(".linkedin.com"):
        entry = base_entry(verdict, "linkedin_easy_apply", None)
        entry["status"] = "manual"
        add_attempt(entry, "submit", "FAILED", "LinkedIn 岗位页禁止自动投递")
        entry = replace_or_add(data, entry)
        save_submissions(data)
        raise SubmitError("绝不把 linkedin.com 岗位页交给自动投递；请转手动")
    mapping = load_object(ats_map_path(), "ATS 能力地图")
    matched = match_ats(target_url, mapping)
    if matched is None:
        entry = base_entry(verdict, "unknown", None)
        entry["status"] = "manual"
        add_attempt(entry, "submit", "FAILED", "ATS 域名未收录，转手动")
        entry = replace_or_add(data, entry)
        save_submissions(data)
        raise SubmitError("ATS 域名未收录，已记入手动队列")
    ats_name, ats_entry = matched
    allowed = auto.get("allowed_ats", [])
    if ats_entry.get("auto_submit") is not True or ats_name not in allowed:
        entry = base_entry(verdict, ats_name, None)
        entry["status"] = "manual"
        add_attempt(entry, "submit", "FAILED", "ATS 不允许自动提交，转手动")
        entry = replace_or_add(data, entry)
        save_submissions(data)
        raise SubmitError(f"{ats_name} 不在自动投递路由中，已记入手动队列")
    cv, cover = materials(job)
    ensure_no_redlines(job, facts)
    thread = new_thread(verdict["jd_key"])
    entry = base_entry(verdict, ats_name, thread)
    entry = replace_or_add(data, entry)
    # 先以 status=unknown 落盘：进程若在投递会话中途死亡，去重铁则会拦住下一次 run，必须先 verify
    save_submissions(data)
    message = task_message(verdict, config, facts, ats_name, ats_entry, cv, cover)
    try:
        kind, payload = invoke_openclaw(
            message, thread=thread, timeout=float(auto.get("submit_timeout_s", 600))
        )
    except (KeyboardInterrupt, SystemExit):
        add_attempt(entry, "submit", "UNKNOWN", "桥接进程被中断；请先 submit.py verify 再决定续跑")
        save_submissions(data)
        raise
    line = apply_result(entry, "submit", kind, payload)
    save_submissions(data)
    print(line)
    return 0


def continue_job(job: Path, answer: str | None) -> int:
    verdict = load_verdict(job)
    # 与 run 同一道闸门：用户中途关掉开关后，续跑同样不许再碰 OpenClaw（verify 只读不受限）
    config = load_object(DEFAULT_CONFIG, "配置")
    auto = require_auto_submit(config)
    data = load_submissions()
    entry = find_entry(data, verdict["jd_key"])
    if not entry or not entry.get("thread"):
        raise SubmitError("找不到原投递 thread，无法续跑；请先执行 submit.py run")
    if entry.get("status") in {"submitted", "blocked", "manual"}:
        raise SubmitError(f"当前状态为 {entry.get('status')}，安全规则禁止续跑")
    attempts = entry.get("attempts", [])
    if entry.get("status") == "unknown" and (
        not attempts
        or attempts[-1].get("action") != "verify"
        or attempts[-1].get("result") != "NOT_SUBMITTED"
    ):
        raise SubmitError("上次结果为 UNKNOWN；禁止直接续跑，请先执行 submit.py verify")
    if answer and re.search(r"password|密码", answer, re.I):
        raise SubmitError("拒绝通过 --answer 接收或传递密码/凭据；请由用户本人在浏览器登录")
    if (
        answer
        and attempts
        and attempts[-1].get("result") == "NEED"
        and parse_fields(str(attempts[-1].get("detail") or "")).get("what")
        == "login"
    ):
        raise SubmitError("NEED login 后必须由用户本人登录，再使用无 --answer 的 continue")
    if answer:
        message = (
            "这是用户确认过的一次性补料，只用于当前表单，不要保存或扩展含义：\n"
            + answer
            + "\n请从当前进度继续，遵守原任务行为红线，末行使用 RESULT: 协议。"
        )
    else:
        message = (
            "请从当前进度继续完成本次投递，不要重复已完成的步骤；仍遵守原任务消息中的"
            "行为红线，最后必须以恰好一行 RESULT: 协议行结束"
        )
    timeout = float(auto.get("submit_timeout_s", 600))
    kind, payload = invoke_openclaw(message, thread=entry["thread"], timeout=timeout)
    line = apply_result(entry, "continue", kind, payload)
    save_submissions(data)
    print(line)
    return 0


def verify_job(job: Path) -> int:
    verdict = load_verdict(job)
    data = load_submissions()
    entry = find_entry(data, verdict["jd_key"])
    if not entry:
        raise SubmitError("该职位没有投递记录，无法核实")
    config = load_object(DEFAULT_CONFIG, "配置")
    timeout = float(config.get("auto_submit", {}).get("verify_timeout_s", 240))
    kind, payload = invoke_openclaw(
        verify_message(verdict), thread=None, timeout=timeout
    )
    line = apply_verify(entry, kind, payload)
    save_submissions(data)
    print(line)
    return 0


def print_status(show_all: bool) -> int:
    data = load_submissions()
    entries = [item for item in data["submissions"] if isinstance(item, dict)]
    if not entries:
        print("尚无投递记录。")
        return 0
    order = ("submitted", "needs_user", "blocked", "manual", "unknown", "failed")
    labels = {
        "submitted": "✅ 已提交",
        "needs_user": "⏸ 需要用户",
        "blocked": "🧱 被阻断",
        "manual": "🖐 手动",
        "unknown": "❓ 待核实",
        "failed": "✗ 失败",
    }
    for status in order:
        selected = [entry for entry in entries if entry.get("status") == status]
        if not selected and not show_all:
            continue
        print(f"{labels[status]} ({len(selected)})")
        for entry in selected:
            evidence = f" — {entry.get('evidence')}" if entry.get("evidence") else ""
            print(f"  {entry.get('jd_key')}{evidence}")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bole OpenClaw 投递桥接")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="新建投递会话")
    run.add_argument("--job", required=True, type=Path)
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--facts", required=True, type=Path)
    run.add_argument(
        "--force",
        action="store_true",
        help="强制越过 submitted/unknown 去重保护；可能造成双投，请仅在人工核实后使用",
    )
    cont = sub.add_parser("continue", help="沿原 thread 续跑")
    cont.add_argument("--job", required=True, type=Path)
    cont.add_argument("--answer", help="一次性补料；严禁传密码或凭据")
    verify = sub.add_parser("verify", help="新开只读会话核实状态")
    verify.add_argument("--job", required=True, type=Path)
    status = sub.add_parser("status", help="打印中文投递台账")
    status.add_argument("--all", action="store_true", help="连空分组也显示")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        if args.command == "run":
            return run_job(args.job, args.config, args.facts, args.force)
        if args.command == "continue":
            return continue_job(args.job, args.answer)
        if args.command == "verify":
            return verify_job(args.job)
        return print_status(args.all)
    except SubmitError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
