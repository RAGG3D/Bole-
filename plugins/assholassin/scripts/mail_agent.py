#!/usr/bin/env python3
"""assHOLassin 的本地 IMAP 确定层：配置、只读扫描与按计划执行。"""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import imaplib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVIDERS = PLUGIN_ROOT / "providers.json"
DEFAULT_MAILBOXES = PLUGIN_ROOT / "profile" / "mailbox.json"
DEFAULT_RULES = PLUGIN_ROOT / "profile" / "rules.json"
DEFAULT_STATE = PLUGIN_ROOT / "state"
SOFT_FOLDER = "assHOLassin-标记"
ACTIONS = ("soft", "trash", "purge")
ACTION_RANK = {name: index for index, name in enumerate(ACTIONS)}
HEADER_QUERY = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
PROVIDER_FIELDS = {
    "imap_host",
    "imap_port",
    "auth_label",
    "setup_guide_zh",
    "trash_folder",
    "quirks",
}


class MailAgentError(RuntimeError):
    """可安全展示给用户、且不包含服务端原始响应的错误。"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MailAgentError(f"未找到{label}：{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise MailAgentError(f"{label}无法读取或不是合法 JSON：{path}") from exc


def atomic_write_json(path: Path, payload: Any, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.chmod(mode)
        os.replace(temp_path, path)
        path.chmod(mode)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise MailAgentError(f"无法安全写入本地文件：{path}") from exc


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def load_providers(path: Path = DEFAULT_PROVIDERS) -> dict[str, dict[str, Any]]:
    payload = read_json(path, "服务商配置")
    providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(providers, dict) or not providers:
        raise MailAgentError("providers.json 的 providers 必须是非空对象")
    for domain, entry in providers.items():
        if not isinstance(domain, str) or not domain or not isinstance(entry, dict):
            raise MailAgentError("providers.json 含无效服务商条目")
        missing = PROVIDER_FIELDS - set(entry)
        if missing:
            raise MailAgentError(
                f"providers.json 的 {domain} 缺少字段：{', '.join(sorted(missing))}"
            )
        if (
            not isinstance(entry["imap_host"], str)
            or not entry["imap_host"]
            or not isinstance(entry["imap_port"], int)
            or not 1 <= entry["imap_port"] <= 65535
            or not isinstance(entry["auth_label"], str)
            or not isinstance(entry["setup_guide_zh"], str)
            or not isinstance(entry["trash_folder"], str)
            or not isinstance(entry["quirks"], list)
            or not all(isinstance(item, str) and item for item in entry["quirks"])
        ):
            raise MailAgentError(f"providers.json 的 {domain} 字段类型无效")
    return {str(key).casefold(): value for key, value in providers.items()}


def mailbox_domain(address: str) -> str:
    if "@" not in address:
        return ""
    return address.rsplit("@", 1)[1].strip().casefold()


def normalize_mailbox(
    raw: dict[str, Any], providers: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    email_address = str(raw.get("email", "")).strip()
    provider_key = str(raw.get("provider") or mailbox_domain(email_address)).casefold()
    provider = providers.get(provider_key)
    if provider is None:
        raise MailAgentError(f"暂不支持邮箱服务商：{provider_key or '未知'}")
    auth_code = raw.get("auth_code")
    if not isinstance(auth_code, str) or not auth_code:
        raise MailAgentError(f"{email_address or '邮箱'} 尚未配置授权码")
    host = str(raw.get("imap_host") or provider["imap_host"]).strip()
    port = raw.get("imap_port", provider["imap_port"])
    if not email_address or not host or not isinstance(port, int):
        raise MailAgentError("mailbox.json 含不完整的邮箱配置")
    return {
        "provider": provider_key,
        "email": email_address,
        "imap_host": host,
        "imap_port": port,
        "auth_code": auth_code,
        "provider_config": provider,
    }


def load_mailboxes(
    path: Path, providers: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    payload = read_json(path, "邮箱配置")
    values = payload.get("mailboxes") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        raise MailAgentError("mailbox.json 的 mailboxes 必须是非空数组")
    result: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, dict):
            raise MailAgentError("mailbox.json 含无效邮箱条目")
        result.append(normalize_mailbox(raw, providers))
    return result


def provider_help(mailbox: dict[str, Any]) -> str:
    provider = mailbox["provider_config"]
    tips = "；".join(provider.get("quirks", []))
    return f"{provider['setup_guide_zh']} 排查：{tips}"


def imap_utf7_encode(value: str) -> bytes:
    """将邮箱文件夹名编码为 IMAP modified UTF-7。"""
    output = bytearray()
    non_ascii: list[str] = []

    def flush() -> None:
        if not non_ascii:
            return
        raw = "".join(non_ascii).encode("utf-16be")
        encoded = base64.b64encode(raw).rstrip(b"=").replace(b"/", b",")
        output.extend(b"&" + encoded + b"-")
        non_ascii.clear()

    for character in value:
        codepoint = ord(character)
        if 0x20 <= codepoint <= 0x7E:
            flush()
            output.extend(b"&-" if character == "&" else character.encode("ascii"))
        else:
            non_ascii.append(character)
    flush()
    return bytes(output)


def imap_utf7_decode(value: bytes | str) -> str:
    raw = value.encode("ascii", errors="replace") if isinstance(value, str) else value
    output: list[str] = []
    index = 0
    while index < len(raw):
        if raw[index : index + 1] != b"&":
            end = raw.find(b"&", index)
            end = len(raw) if end < 0 else end
            output.append(raw[index:end].decode("ascii", errors="replace"))
            index = end
            continue
        end = raw.find(b"-", index)
        if end < 0:
            output.append(raw[index:].decode("ascii", errors="replace"))
            break
        token = raw[index + 1 : end]
        if not token:
            output.append("&")
        else:
            padding = b"=" * ((4 - len(token) % 4) % 4)
            try:
                decoded = base64.b64decode(token.replace(b",", b"/") + padding)
                output.append(decoded.decode("utf-16be"))
            except (binascii.Error, UnicodeDecodeError):
                output.append(raw[index : end + 1].decode("ascii", errors="replace"))
        index = end + 1
    return "".join(output)


def mailbox_argument(folder: str) -> bytes:
    encoded = imap_utf7_encode(folder).replace(b"\\", b"\\\\").replace(b'"', b'\\"')
    return b'"' + encoded + b'"'


def parse_list_line(raw: bytes | str) -> tuple[set[str], str] | None:
    value = raw if isinstance(raw, bytes) else raw.encode("ascii", errors="replace")
    match = re.match(rb"^\s*\(([^)]*)\)\s+(?:\"[^\"]*\"|NIL)\s+(.+?)\s*$", value)
    if not match:
        return None
    flags = {
        item.decode("ascii", errors="ignore").casefold()
        for item in match.group(1).split()
    }
    mailbox_raw = match.group(2).strip()
    if mailbox_raw.startswith(b'"') and mailbox_raw.endswith(b'"'):
        mailbox_raw = mailbox_raw[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
    return flags, imap_utf7_decode(mailbox_raw)


class ImapMailbox:
    """薄封装，便于离线 mock 并集中屏蔽敏感错误。"""

    def __init__(
        self,
        mailbox: dict[str, Any],
        factory: Callable[..., Any] = imaplib.IMAP4_SSL,
    ) -> None:
        self.mailbox = mailbox
        self.factory = factory
        self.connection: Any | None = None

    def __enter__(self) -> "ImapMailbox":
        try:
            self.connection = self.factory(
                self.mailbox["imap_host"], self.mailbox["imap_port"]
            )
            status, _ = self.connection.login(
                self.mailbox["email"], self.mailbox["auth_code"]
            )
            if str(status).upper() != "OK":
                raise imaplib.IMAP4.error("login rejected")
        except imaplib.IMAP4.error as exc:
            self._close_quietly()
            raise MailAgentError(
                f"邮箱授权失败。请重新生成{self.mailbox['provider_config']['auth_label']}。"
                f"{provider_help(self.mailbox)}"
            ) from exc
        except (OSError, TimeoutError) as exc:
            self._close_quietly()
            raise MailAgentError("无法连接 IMAP 服务器；请检查网络、主机与端口设置") from exc
        return self

    def __exit__(self, *_: object) -> None:
        self._close_quietly()

    def _close_quietly(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.logout()
        except Exception:
            pass
        self.connection = None

    def _call(self, label: str, method: Callable[..., Any], *args: Any) -> list[Any]:
        try:
            status, data = method(*args)
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
            raise MailAgentError(f"IMAP {label}失败；请核对审计日志后再续跑") from exc
        if str(status).upper() != "OK":
            raise MailAgentError(f"IMAP {label}失败；请核对审计日志后再续跑")
        return data or []

    def select(self, *, readonly: bool) -> int:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        data = self._call(
            "选择收件箱", self.connection.select, "INBOX", readonly
        )
        try:
            return int(data[0])
        except (IndexError, TypeError, ValueError):
            return 0

    def search_since(self, since: datetime) -> list[bytes]:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        data = self._call(
            "搜索",
            self.connection.uid,
            "SEARCH",
            None,
            "SINCE",
            since.strftime("%d-%b-%Y"),
        )
        if not data:
            return []
        first = data[0]
        if isinstance(first, str):
            first = first.encode("ascii", errors="ignore")
        return list(first.split()) if isinstance(first, bytes) else []

    def fetch_header(self, uid: bytes | str) -> bytes:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        data = self._call(
            "读取邮件头", self.connection.uid, "FETCH", uid, HEADER_QUERY
        )
        chunks: list[bytes] = []
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                chunks.append(item[1])
            elif isinstance(item, bytes) and b":" in item:
                chunks.append(item)
        if not chunks:
            raise MailAgentError("服务器未返回可解析的邮件头")
        return b"\r\n".join(chunks)

    def folders(self) -> list[tuple[set[str], str]]:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        data = self._call("列出文件夹", self.connection.list)
        parsed = [parse_list_line(item) for item in data if item is not None]
        return [item for item in parsed if item is not None]

    def trash_folder(self) -> str:
        folders = self.folders()
        for flags, name in folders:
            if "\\trash" in flags:
                return name
        preferred = str(self.mailbox["provider_config"]["trash_folder"])
        for _, name in folders:
            if name.casefold() == preferred.casefold():
                return name
        return preferred

    def ensure_folder(self, folder: str) -> None:
        if any(name.casefold() == folder.casefold() for _, name in self.folders()):
            return
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        self._call("创建标记文件夹", self.connection.create, mailbox_argument(folder))

    def copy(self, uid: str, folder: str) -> None:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        self._call(
            "复制邮件",
            self.connection.uid,
            "COPY",
            uid,
            mailbox_argument(folder),
        )

    def mark_seen(self, uid: str) -> None:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        self._call(
            "标记已读",
            self.connection.uid,
            "STORE",
            uid,
            "+FLAGS.SILENT",
            r"(\Seen)",
        )

    def mark_deleted(self, uid: str) -> None:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        self._call(
            "标记删除",
            self.connection.uid,
            "STORE",
            uid,
            "+FLAGS.SILENT",
            r"(\Deleted)",
        )

    def require_targeted_expunge(self) -> None:
        """拒绝可能顺带清除其他 ``\\Deleted`` 邮件的普通 EXPUNGE。"""
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        capabilities = getattr(self.connection, "capabilities", ())
        normalized = {
            (
                item.decode("ascii", errors="ignore")
                if isinstance(item, bytes)
                else str(item)
            ).upper()
            for item in capabilities
        }
        if "UIDPLUS" not in normalized:
            raise MailAgentError(
                "服务器不支持定向 UID EXPUNGE；为避免误删计划外邮件，本轮停止"
            )

    def expunge(self, uid: str) -> None:
        if self.connection is None:
            raise MailAgentError("IMAP 连接尚未建立")
        self._call(
            "定向提交删除",
            self.connection.uid,
            "EXPUNGE",
            uid,
        )


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            candidates = [charset, "utf-8", "gb18030", "latin-1"]
            decoded = ""
            for candidate in candidates:
                if not candidate:
                    continue
                try:
                    decoded = chunk.decode(candidate)
                    break
                except (LookupError, UnicodeDecodeError):
                    continue
            parts.append(decoded or chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def parse_header(raw: bytes) -> dict[str, Any]:
    message = BytesParser(policy=policy.compat32).parsebytes(raw, headersonly=True)
    sender = decode_mime_header(message.get("From"))
    subject = decode_mime_header(message.get("Subject"))
    date_raw = str(message.get("Date") or "").strip()
    parsed: datetime | None = None
    if date_raw:
        try:
            parsed = parsedate_to_datetime(date_raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            parsed = None
    return {
        "from": sender,
        "subject": subject,
        "date": parsed,
        "date_raw": date_raw,
    }


def string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MailAgentError(f"{label} 必须是字符串数组")
    return [item.strip() for item in value if item.strip()]


def load_rules(path: Path = DEFAULT_RULES) -> dict[str, Any]:
    payload = read_json(path, "规则配置")
    if not isinstance(payload, dict):
        raise MailAgentError("rules.json 必须是对象")
    rules = payload.get("rules")
    whitelist = payload.get("whitelist", {})
    if not isinstance(rules, list) or not isinstance(whitelist, dict):
        raise MailAgentError("rules.json 的 rules/whitelist 结构无效")
    default_days = payload.get("default_window_days", 30)
    maximum = payload.get("max_actions_per_run", 200)
    if not isinstance(default_days, int) or default_days <= 0:
        raise MailAgentError("default_window_days 必须是正整数")
    if not isinstance(maximum, int) or maximum <= 0:
        raise MailAgentError("max_actions_per_run 必须是正整数")
    normalized_rules: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(rules):
        if not isinstance(raw, dict):
            raise MailAgentError(f"第 {index + 1} 条规则不是对象")
        rule_id = str(raw.get("id", "")).strip()
        if not rule_id or rule_id in seen_ids:
            raise MailAgentError("每条规则必须有唯一且非空的 id")
        seen_ids.add(rule_id)
        match = raw.get("match")
        if not isinstance(match, dict):
            raise MailAgentError(f"规则 {rule_id} 缺少 match")
        logic = str(match.get("logic", "any")).casefold()
        action = str(raw.get("action", "")).casefold()
        window_days = raw.get("window_days", default_days)
        if logic not in {"any", "all"}:
            raise MailAgentError(f"规则 {rule_id} 的 logic 必须为 any 或 all")
        if action not in ACTIONS:
            raise MailAgentError(f"规则 {rule_id} 的 action 无效")
        if not isinstance(window_days, int) or window_days <= 0:
            raise MailAgentError(f"规则 {rule_id} 的 window_days 必须是正整数")
        from_terms = string_list(
            match.get("from_contains", []), f"规则 {rule_id}.from_contains"
        )
        subject_terms = string_list(
            match.get("subject_contains", []), f"规则 {rule_id}.subject_contains"
        )
        if not from_terms and not subject_terms:
            raise MailAgentError(f"规则 {rule_id} 至少需要一个关键词")
        normalized_rules.append(
            {
                "id": rule_id,
                "enabled": bool(raw.get("enabled", True)),
                "match": {
                    "from_contains": from_terms,
                    "subject_contains": subject_terms,
                    "logic": logic,
                },
                "action": action,
                "window_days": window_days,
            }
        )
    return {
        "rules": normalized_rules,
        "whitelist": {
            "senders": string_list(whitelist.get("senders", []), "whitelist.senders"),
            "domains": string_list(whitelist.get("domains", []), "whitelist.domains"),
            "subject_contains": string_list(
                whitelist.get("subject_contains", []),
                "whitelist.subject_contains",
            ),
        },
        "default_window_days": default_days,
        "max_actions_per_run": maximum,
    }


def is_whitelisted(
    sender: str, subject: str, whitelist: dict[str, list[str]]
) -> bool:
    sender_folded = sender.casefold()
    subject_folded = subject.casefold()
    if any(term.casefold() in sender_folded for term in whitelist["senders"]):
        return True
    if any(term.casefold() in subject_folded for term in whitelist["subject_contains"]):
        return True
    domains = {
        address.rsplit("@", 1)[1].casefold()
        for _, address in getaddresses([sender])
        if "@" in address
    }
    for allowed in whitelist["domains"]:
        allowed_folded = allowed.lstrip("@").casefold()
        if any(
            domain == allowed_folded or domain.endswith("." + allowed_folded)
            for domain in domains
        ):
            return True
    return False


def rule_matches(rule: dict[str, Any], sender: str, subject: str) -> bool:
    match = rule["match"]
    sender_folded = sender.casefold()
    subject_folded = subject.casefold()
    checks = [
        term.casefold() in sender_folded for term in match["from_contains"]
    ] + [
        term.casefold() in subject_folded for term in match["subject_contains"]
    ]
    if not checks:
        return False
    return all(checks) if match["logic"] == "all" else any(checks)


def within_window(value: datetime | None, days: int, now: datetime) -> bool:
    if value is None:
        return False
    cutoff = (now - timedelta(days=max(days - 1, 0))).date()
    return value.astimezone(timezone.utc).date() >= cutoff


def filter_mailboxes(
    mailboxes: list[dict[str, Any]], selector: str | None
) -> list[dict[str, Any]]:
    if not selector:
        return mailboxes
    selector_folded = selector.casefold()
    selected = [
        mailbox
        for mailbox in mailboxes
        if selector_folded
        in {
            mailbox["email"].casefold(),
            mailbox["provider"].casefold(),
        }
    ]
    if not selected:
        raise MailAgentError(f"未找到邮箱选择器：{selector}")
    return selected


def probe_mailboxes(
    mailboxes: Iterable[dict[str, Any]],
    *,
    imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for mailbox in mailboxes:
        try:
            with ImapMailbox(mailbox, imap_factory) as remote:
                count = remote.select(readonly=True)
            results.append(
                {
                    "email": mailbox["email"],
                    "provider": mailbox["provider"],
                    "status": "ok",
                    "message_count": count,
                }
            )
        except MailAgentError as exc:
            results.append(
                {
                    "email": mailbox["email"],
                    "provider": mailbox["provider"],
                    "status": "error",
                    "message": str(exc),
                }
            )
    return {
        "status": "ok" if all(item["status"] == "ok" for item in results) else "error",
        "mailboxes": results,
    }


def scan_mailboxes(
    mailboxes: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    days_override: int | None = None,
    output_path: Path | None = None,
    state_dir: Path = DEFAULT_STATE,
    imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    enabled_rules = [rule for rule in rules["rules"] if rule["enabled"]]
    if not enabled_rules:
        raise MailAgentError("没有启用的清理规则")
    server_days = days_override or max(rule["window_days"] for rule in enabled_rules)
    maximum = rules["max_actions_per_run"]
    items: list[dict[str, Any]] = []
    truncated = False

    for mailbox in mailboxes:
        with ImapMailbox(mailbox, imap_factory) as remote:
            remote.select(readonly=True)
            since = current - timedelta(days=max(server_days - 1, 0))
            for raw_uid in remote.search_since(since):
                uid = raw_uid.decode("ascii", errors="ignore")
                if not uid.isdigit():
                    continue
                header = parse_header(remote.fetch_header(raw_uid))
                if is_whitelisted(
                    header["from"], header["subject"], rules["whitelist"]
                ):
                    continue
                matched: dict[str, Any] | None = None
                for rule in enabled_rules:
                    window = days_override or rule["window_days"]
                    if not within_window(header["date"], window, current):
                        continue
                    if rule_matches(rule, header["from"], header["subject"]):
                        matched = rule
                        break
                if matched is None:
                    continue
                if len(items) >= maximum:
                    truncated = True
                    break
                items.append(
                    {
                        "mailbox": mailbox["email"],
                        "provider": mailbox["provider"],
                        "uid": uid,
                        "date": (
                            header["date"].isoformat()
                            if header["date"] is not None
                            else header["date_raw"]
                        ),
                        "from": header["from"],
                        "subject": header["subject"],
                        "rule_id": matched["id"],
                        "action": matched["action"],
                        "source_folder": "INBOX",
                    }
                )
        if truncated:
            break

    timestamp = current.strftime("%Y%m%dT%H%M%SZ")
    plan_id = f"scan-{timestamp}"
    destination = output_path or state_dir / f"scan_plan_{timestamp}.json"
    plan = {
        "schema_version": 1,
        "plan_id": plan_id,
        "created_at": current.isoformat(),
        "dry_run": True,
        "days_override": days_override,
        "max_actions_per_run": maximum,
        "truncated": truncated,
        "count": len(items),
        "items": items,
        "plan_file": str(destination),
    }
    atomic_write_json(destination, plan)
    return plan


def downgrade_action(action: str, level_limit: str) -> str:
    if action not in ACTION_RANK or level_limit not in ACTION_RANK:
        raise MailAgentError("计划含无效处理等级")
    return (
        level_limit
        if ACTION_RANK[action] > ACTION_RANK[level_limit]
        else action
    )


def validate_plan(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise MailAgentError("计划文件结构无效")
    plan_id = payload.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise MailAgentError("计划文件缺少 plan_id")
    maximum = payload.get("max_actions_per_run")
    if not isinstance(maximum, int) or maximum <= 0:
        raise MailAgentError("计划文件缺少有效的单轮动作上限")
    if len(payload["items"]) > maximum:
        raise MailAgentError("计划条目超过单轮动作上限，拒绝执行")
    if payload.get("dry_run") is not True:
        raise MailAgentError("只能执行由 dry-run 生成的计划")
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise MailAgentError("计划含无效条目")
        if (
            not isinstance(item.get("mailbox"), str)
            or not str(item.get("uid", "")).isdigit()
            or item.get("action") not in ACTIONS
            or item.get("source_folder") != "INBOX"
            or not isinstance(item.get("from"), str)
            or not isinstance(item.get("subject"), str)
        ):
            raise MailAgentError("计划含不安全或不完整的条目")
    return payload


def audit_path(state_dir: Path, now: datetime) -> Path:
    return state_dir / f"clean_log_{now.strftime('%Y-%m-%d')}.json"


def read_audit_records(state_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not state_dir.is_dir():
        return records
    for path in sorted(state_dir.glob("clean_log_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values = payload.get("records") if isinstance(payload, dict) else None
        if isinstance(values, list):
            records.extend(item for item in values if isinstance(item, dict))
    return records


def completed_keys(state_dir: Path) -> set[tuple[str, str, str]]:
    return {
        (str(item.get("plan_id")), str(item.get("mailbox")), str(item.get("uid")))
        for item in read_audit_records(state_dir)
        if item.get("status") == "applied"
    }


def append_audit(path: Path, record: dict[str, Any]) -> None:
    if path.exists():
        payload = read_json(path, "审计日志")
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise MailAgentError("审计日志结构无效；停止执行以避免重放")
    else:
        payload = {"schema_version": 1, "records": []}
    payload["records"].append(record)
    atomic_write_json(path, payload)


def apply_plan(
    plan: dict[str, Any],
    mailboxes: list[dict[str, Any]],
    *,
    confirm: bool,
    confirm_purge: bool,
    level_limit: str,
    state_dir: Path = DEFAULT_STATE,
    imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not confirm:
        raise MailAgentError("尚未确认执行；请先检查 dry-run 完整清单")
    current = now or utc_now()
    items = plan["items"]
    effective = [
        {**item, "effective_action": downgrade_action(item["action"], level_limit)}
        for item in items
    ]
    if any(item["effective_action"] == "purge" for item in effective) and not confirm_purge:
        raise MailAgentError("计划含不可恢复的 purge；必须单独再次确认")

    mailbox_by_email = {item["email"].casefold(): item for item in mailboxes}
    done = completed_keys(state_dir)
    log_path = audit_path(state_dir, current)
    applied = 0
    skipped = 0

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in effective:
        grouped.setdefault(item["mailbox"].casefold(), []).append(item)

    for email_key, mailbox_items in grouped.items():
        mailbox = mailbox_by_email.get(email_key)
        if mailbox is None:
            raise MailAgentError("计划引用了当前配置中不存在的邮箱")
        with ImapMailbox(mailbox, imap_factory) as remote:
            remote.select(readonly=False)
            needs_soft = any(
                item["effective_action"] == "soft" for item in mailbox_items
            )
            needs_trash = any(
                item["effective_action"] == "trash" for item in mailbox_items
            )
            needs_delete = any(
                item["effective_action"] in {"trash", "purge"}
                for item in mailbox_items
            )
            if needs_delete:
                remote.require_targeted_expunge()
            if needs_soft:
                remote.ensure_folder(SOFT_FOLDER)
            trash_folder = remote.trash_folder() if needs_trash else ""

            for item in mailbox_items:
                key = (plan["plan_id"], item["mailbox"], item["uid"])
                if key in done:
                    skipped += 1
                    continue
                action = item["effective_action"]
                target_folder = ""
                if action == "soft":
                    remote.mark_seen(item["uid"])
                    remote.copy(item["uid"], SOFT_FOLDER)
                    target_folder = SOFT_FOLDER
                elif action == "trash":
                    remote.copy(item["uid"], trash_folder)
                    remote.mark_deleted(item["uid"])
                    remote.expunge(item["uid"])
                    target_folder = trash_folder
                else:
                    remote.mark_deleted(item["uid"])
                    remote.expunge(item["uid"])
                    target_folder = "永久删除"

                append_audit(
                    log_path,
                    {
                        "plan_id": plan["plan_id"],
                        "mailbox": item["mailbox"],
                        "uid": item["uid"],
                        "from": item["from"],
                        "subject": item["subject"],
                        "requested_action": item["action"],
                        "action": action,
                        "folder": target_folder,
                        "time": current.isoformat(),
                        "status": "applied",
                    },
                )
                done.add(key)
                applied += 1

    return {
        "status": "ok",
        "plan_id": plan["plan_id"],
        "applied": applied,
        "skipped_already_applied": skipped,
        "audit_log": str(log_path),
    }


def configure_mailbox(
    *,
    provider_key: str,
    email_address: str,
    config_path: Path,
    providers: dict[str, dict[str, Any]],
    auth_reader: Callable[[str], str] = getpass.getpass,
    imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
) -> dict[str, Any]:
    key = provider_key.casefold()
    provider = providers.get(key)
    if provider is None:
        raise MailAgentError(f"暂不支持邮箱服务商：{provider_key}")
    if mailbox_domain(email_address) != key:
        raise MailAgentError("邮箱域名与所选服务商不一致")
    print(provider["setup_guide_zh"], file=sys.stderr)
    print("只输入授权码/应用专用密码，绝不要输入邮箱登录密码。", file=sys.stderr)
    auth_code = auth_reader(f"{provider['auth_label']}（隐藏输入）: ").strip()
    if key in {"gmail.com", "qq.com", "foxmail.com"}:
        auth_code = auth_code.replace(" ", "")
    if not auth_code:
        raise MailAgentError("未输入授权码，配置未写入")

    if config_path.exists():
        existing = read_json(config_path, "邮箱配置")
        values = existing.get("mailboxes") if isinstance(existing, dict) else None
        if not isinstance(values, list):
            raise MailAgentError("现有 mailbox.json 结构无效")
    else:
        existing = {"mailboxes": []}
        values = existing["mailboxes"]
    record = {
        "provider": key,
        "email": email_address,
        "imap_host": provider["imap_host"],
        "imap_port": provider["imap_port"],
        "auth_code": auth_code,
    }
    for index, value in enumerate(values):
        if (
            isinstance(value, dict)
            and str(value.get("email", "")).casefold() == email_address.casefold()
        ):
            values[index] = record
            break
    else:
        values.append(record)
    atomic_write_json(config_path, existing)
    normalized = normalize_mailbox(record, providers)
    return probe_mailboxes([normalized], imap_factory=imap_factory)


def positive_days(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("天数必须为正整数")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="assHOLassin：本地 IMAP 邮件清理确定层"
    )
    parser.add_argument(
        "--providers", type=Path, default=DEFAULT_PROVIDERS, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_MAILBOXES, help=argparse.SUPPRESS
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure", help="隐藏输入授权码并只读验证")
    configure.add_argument("--provider", required=True)
    configure.add_argument("--email", required=True)

    probe = subparsers.add_parser("probe", help="只读验证全部邮箱")
    probe.add_argument("--mailbox")

    scan = subparsers.add_parser("scan", help="只读扫描并生成 dry-run 计划")
    scan.add_argument("--days", type=positive_days)
    scan.add_argument("--mailbox")
    scan.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    scan.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    scan.add_argument("--output", type=Path)

    apply_parser = subparsers.add_parser("apply", help="按已确认计划执行")
    apply_parser.add_argument("--plan", type=Path, required=True)
    apply_parser.add_argument(
        "--level-limit", choices=ACTIONS, default="purge"
    )
    apply_parser.add_argument("--confirm", action="store_true")
    apply_parser.add_argument("--confirm-purge", action="store_true")
    apply_parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        providers = load_providers(args.providers)
        if args.command == "configure":
            result = configure_mailbox(
                provider_key=args.provider,
                email_address=args.email,
                config_path=args.config,
                providers=providers,
            )
        else:
            mailboxes = load_mailboxes(args.config, providers)
            if args.command == "probe":
                selected = filter_mailboxes(mailboxes, args.mailbox)
                result = probe_mailboxes(selected)
            elif args.command == "scan":
                selected = filter_mailboxes(mailboxes, args.mailbox)
                rules = load_rules(args.rules)
                result = scan_mailboxes(
                    selected,
                    rules,
                    days_override=args.days,
                    output_path=args.output,
                    state_dir=args.state_dir,
                )
            else:
                plan = validate_plan(read_json(args.plan, "扫描计划"))
                result = apply_plan(
                    plan,
                    mailboxes,
                    confirm=args.confirm,
                    confirm_purge=args.confirm_purge,
                    level_limit=args.level_limit,
                    state_dir=args.state_dir,
                )
        print_json(result)
        return 0 if result.get("status") == "ok" else 2
    except (MailAgentError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
