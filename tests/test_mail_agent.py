from __future__ import annotations

import importlib.util
import imaplib
import json
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.utils import format_datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins" / "assholassin" / "scripts" / "mail_agent.py"
PROVIDERS = ROOT / "plugins" / "assholassin" / "providers.json"
SECRET = "DO_NOT_LEAK_SECRET_42"


def load_module():
    spec = importlib.util.spec_from_file_location("assholassin_mail_agent", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 mail_agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encoded_header(
    sender_name: str,
    sender_address: str,
    subject: str,
    date: datetime,
) -> bytes:
    sender = f"{Header(sender_name, 'utf-8').encode()} <{sender_address}>"
    value = (
        f"From: {sender}\r\n"
        f"Subject: {Header(subject, 'utf-8').encode()}\r\n"
        f"Date: {format_datetime(date)}\r\n"
        "\r\n"
    )
    return value.encode("ascii")


class FakeImap:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        headers: dict[bytes, bytes] | None = None,
        login_error: Exception | None = None,
    ) -> None:
        self.capabilities = ("IMAP4REV1", "UIDPLUS")
        self.host = host
        self.port = port
        self.headers = headers or {}
        self.login_error = login_error
        self.calls: list[tuple[Any, ...]] = []

    def login(self, email: str, auth_code: str):
        self.calls.append(("login", email, auth_code))
        if self.login_error is not None:
            raise self.login_error
        return "OK", [b"authenticated"]

    def select(self, mailbox: str, readonly: bool = False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [str(len(self.headers)).encode()]

    def uid(self, command: str, *args: Any):
        self.calls.append(("uid", command, *args))
        command = command.upper()
        if command == "SEARCH":
            return "OK", [b" ".join(sorted(self.headers))]
        if command == "FETCH":
            uid = args[0]
            uid_bytes = uid.encode() if isinstance(uid, str) else uid
            return "OK", [(b"header", self.headers[uid_bytes])]
        return "OK", [b"done"]

    def list(self):
        self.calls.append(("list",))
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren \\Trash) "/" "Trash"',
        ]

    def create(self, folder: bytes):
        self.calls.append(("create", folder))
        return "OK", [b"created"]

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b"closed"]


class FakeFactory:
    def __init__(
        self,
        headers: dict[bytes, bytes] | None = None,
        login_error: Exception | None = None,
    ) -> None:
        self.headers = headers or {}
        self.login_error = login_error
        self.instances: list[FakeImap] = []

    def __call__(self, host: str, port: int) -> FakeImap:
        instance = FakeImap(
            host,
            port,
            headers=self.headers,
            login_error=self.login_error,
        )
        self.instances.append(instance)
        return instance


class MailAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        providers = self.module.load_providers(PROVIDERS)
        provider = providers["gmail.com"]
        self.mailbox = {
            "provider": "gmail.com",
            "email": "tester@example.test",
            "imap_host": provider["imap_host"],
            "imap_port": provider["imap_port"],
            "auth_code": SECRET,
            "provider_config": provider,
        }
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)

    def rules(
        self,
        *,
        action: str = "trash",
        logic: str = "any",
        maximum: int = 200,
    ) -> dict[str, Any]:
        return {
            "rules": [
                {
                    "id": "r1",
                    "enabled": True,
                    "match": {
                        "from_contains": ["marketing"],
                        "subject_contains": ["促销"],
                        "logic": logic,
                    },
                    "action": action,
                    "window_days": 30,
                }
            ],
            "whitelist": {
                "senders": [],
                "domains": [],
                "subject_contains": [],
            },
            "default_window_days": 30,
            "max_actions_per_run": maximum,
        }

    def plan(self, action: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "plan_id": f"plan-{action}",
            "dry_run": True,
            "max_actions_per_run": 200,
            "items": [
                {
                    "mailbox": self.mailbox["email"],
                    "provider": "gmail.com",
                    "uid": "1",
                    "date": self.now.isoformat(),
                    "from": "Marketing <promo@example.test>",
                    "subject": "促销活动",
                    "rule_id": "r1",
                    "action": action,
                    "source_folder": "INBOX",
                }
            ],
        }

    def test_rule_matching_from_subject_any_all(self) -> None:
        any_rule = self.rules(logic="any")["rules"][0]
        all_rule = self.rules(logic="all")["rules"][0]
        self.assertTrue(
            self.module.rule_matches(
                any_rule, "Marketing <promo@example.test>", "普通通知"
            )
        )
        self.assertTrue(
            self.module.rule_matches(
                any_rule, "Other <other@example.test>", "本周促销"
            )
        )
        self.assertFalse(
            self.module.rule_matches(
                all_rule, "Marketing <promo@example.test>", "普通通知"
            )
        )
        self.assertTrue(
            self.module.rule_matches(
                all_rule, "Marketing <promo@example.test>", "本周促销"
            )
        )

    def test_rfc2047_chinese_header_is_decoded(self) -> None:
        raw = encoded_header(
            "营销中心",
            "marketing@example.test",
            "七月促销活动",
            self.now,
        )
        parsed = self.module.parse_header(raw)
        self.assertIn("营销中心", parsed["from"])
        self.assertEqual(parsed["subject"], "七月促销活动")

    def test_window_and_whitelist_take_priority(self) -> None:
        self.assertTrue(
            self.module.within_window(self.now - timedelta(days=6), 7, self.now)
        )
        self.assertFalse(
            self.module.within_window(self.now - timedelta(days=7), 7, self.now)
        )
        whitelist = {
            "senders": ["trusted"],
            "domains": ["important.example"],
            "subject_contains": ["保留"],
        }
        self.assertTrue(
            self.module.is_whitelisted(
                "Trusted Team <promo@elsewhere.test>", "促销", whitelist
            )
        )
        self.assertTrue(
            self.module.is_whitelisted(
                "Sender <notice@sub.important.example>", "促销", whitelist
            )
        )
        self.assertTrue(
            self.module.is_whitelisted(
                "Marketing <promo@elsewhere.test>", "请保留此邮件", whitelist
            )
        )

    def test_scan_is_peek_only_and_never_leaks_auth_code(self) -> None:
        headers = {
            b"1": encoded_header(
                "Marketing",
                "marketing@example.test",
                "七月促销",
                self.now - timedelta(days=1),
            )
        }
        factory = FakeFactory(headers)
        with tempfile.TemporaryDirectory() as temp:
            plan = self.module.scan_mailboxes(
                [self.mailbox],
                self.rules(),
                state_dir=Path(temp),
                imap_factory=factory,
                now=self.now,
            )
            serialized = json.dumps(plan, ensure_ascii=False)
            self.assertNotIn(SECRET, serialized)
            self.assertEqual(plan["count"], 1)
            self.assertEqual(plan["items"][0]["subject"], "七月促销")
        calls = factory.instances[0].calls
        self.assertIn(("select", "INBOX", True), calls)
        uid_calls = [call for call in calls if call[0] == "uid"]
        self.assertTrue(any(call[1] == "SEARCH" for call in uid_calls))
        fetches = [call for call in uid_calls if call[1] == "FETCH"]
        self.assertEqual(fetches[0][-1], self.module.HEADER_QUERY)
        self.assertFalse(any(call[1] in {"COPY", "STORE"} for call in uid_calls))
        self.assertFalse(any(call[0] in {"create", "expunge"} for call in calls))

    def test_scan_respects_action_limit(self) -> None:
        headers = {
            b"1": encoded_header(
                "Marketing", "a@example.test", "促销一", self.now
            ),
            b"2": encoded_header(
                "Marketing", "b@example.test", "促销二", self.now
            ),
        }
        with tempfile.TemporaryDirectory() as temp:
            plan = self.module.scan_mailboxes(
                [self.mailbox],
                self.rules(maximum=1),
                state_dir=Path(temp),
                imap_factory=FakeFactory(headers),
                now=self.now,
            )
        self.assertEqual(plan["count"], 1)
        self.assertTrue(plan["truncated"])

    def test_plan_over_action_limit_is_rejected(self) -> None:
        plan = self.plan("trash")
        plan["max_actions_per_run"] = 0
        with self.assertRaisesRegex(
            self.module.MailAgentError, "单轮动作上限"
        ):
            self.module.validate_plan(plan)

        plan = self.plan("trash")
        plan["items"].append({**plan["items"][0], "uid": "2"})
        plan["max_actions_per_run"] = 1
        with self.assertRaisesRegex(
            self.module.MailAgentError, "超过单轮动作上限"
        ):
            self.module.validate_plan(plan)

    def test_soft_marks_seen_and_copies_without_deleted(self) -> None:
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as temp:
            result = self.module.apply_plan(
                self.plan("soft"),
                [self.mailbox],
                confirm=True,
                confirm_purge=False,
                level_limit="purge",
                state_dir=Path(temp),
                imap_factory=factory,
                now=self.now,
            )
        self.assertEqual(result["applied"], 1)
        calls = factory.instances[0].calls
        uid_calls = [call for call in calls if call[0] == "uid"]
        self.assertTrue(any(call[1] == "COPY" for call in uid_calls))
        self.assertTrue(
            any(call[1] == "STORE" and r"(\Seen)" in call for call in uid_calls)
        )
        self.assertFalse(
            any(call[1] == "STORE" and r"(\Deleted)" in call for call in uid_calls)
        )
        self.assertFalse(
            any(call[0] == "uid" and call[1] == "EXPUNGE" for call in calls)
        )

    def test_trash_copies_then_deletes_and_expunges(self) -> None:
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as temp:
            self.module.apply_plan(
                self.plan("trash"),
                [self.mailbox],
                confirm=True,
                confirm_purge=False,
                level_limit="purge",
                state_dir=Path(temp),
                imap_factory=factory,
                now=self.now,
            )
            log_text = next(Path(temp).glob("clean_log_*.json")).read_text()
        self.assertNotIn(SECRET, log_text)
        calls = factory.instances[0].calls
        copy_index = next(
            index
            for index, call in enumerate(calls)
            if call[0] == "uid" and call[1] == "COPY"
        )
        delete_index = next(
            index
            for index, call in enumerate(calls)
            if call[0] == "uid"
            and call[1] == "STORE"
            and r"(\Deleted)" in call
        )
        expunge_index = next(
            index
            for index, call in enumerate(calls)
            if call[0] == "uid" and call[1] == "EXPUNGE"
        )
        self.assertLess(copy_index, delete_index)
        self.assertLess(delete_index, expunge_index)

    def test_purge_requires_separate_confirmation(self) -> None:
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(
                self.module.MailAgentError, "必须单独再次确认"
            ):
                self.module.apply_plan(
                    self.plan("purge"),
                    [self.mailbox],
                    confirm=True,
                    confirm_purge=False,
                    level_limit="purge",
                    state_dir=Path(temp),
                    imap_factory=factory,
                    now=self.now,
                )
            self.assertEqual(factory.instances, [])

            self.module.apply_plan(
                self.plan("purge"),
                [self.mailbox],
                confirm=True,
                confirm_purge=True,
                level_limit="purge",
                state_dir=Path(temp),
                imap_factory=factory,
                now=self.now,
            )
        calls = factory.instances[0].calls
        self.assertFalse(
            any(call[0] == "uid" and call[1] == "COPY" for call in calls)
        )
        self.assertTrue(
            any(call[0] == "uid" and call[1] == "EXPUNGE" for call in calls)
        )

    def test_delete_stops_before_writes_without_uidplus(self) -> None:
        factory = FakeFactory()

        def no_uidplus_factory(host: str, port: int) -> FakeImap:
            instance = factory(host, port)
            instance.capabilities = ("IMAP4REV1",)
            return instance

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(
                self.module.MailAgentError, "UID EXPUNGE"
            ):
                self.module.apply_plan(
                    self.plan("trash"),
                    [self.mailbox],
                    confirm=True,
                    confirm_purge=False,
                    level_limit="trash",
                    state_dir=Path(temp),
                    imap_factory=no_uidplus_factory,
                    now=self.now,
                )
        uid_calls = [
            call for call in factory.instances[0].calls if call[0] == "uid"
        ]
        self.assertFalse(
            any(call[1] in {"COPY", "STORE", "EXPUNGE"} for call in uid_calls)
        )

    def test_level_limit_downgrades_purge_to_trash(self) -> None:
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as temp:
            result = self.module.apply_plan(
                self.plan("purge"),
                [self.mailbox],
                confirm=True,
                confirm_purge=False,
                level_limit="trash",
                state_dir=Path(temp),
                imap_factory=factory,
                now=self.now,
            )
            log = json.loads(Path(result["audit_log"]).read_text())
        self.assertEqual(log["records"][0]["requested_action"], "purge")
        self.assertEqual(log["records"][0]["action"], "trash")

    def test_reapplying_plan_skips_audited_uid(self) -> None:
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            first = self.module.apply_plan(
                self.plan("trash"),
                [self.mailbox],
                confirm=True,
                confirm_purge=False,
                level_limit="trash",
                state_dir=state,
                imap_factory=factory,
                now=self.now,
            )
            second = self.module.apply_plan(
                self.plan("trash"),
                [self.mailbox],
                confirm=True,
                confirm_purge=False,
                level_limit="trash",
                state_dir=state,
                imap_factory=factory,
                now=self.now,
            )
        self.assertEqual(first["applied"], 1)
        self.assertEqual(second["applied"], 0)
        self.assertEqual(second["skipped_already_applied"], 1)

    def test_configure_uses_private_file_and_safe_result(self) -> None:
        providers = self.module.load_providers(PROVIDERS)
        factory = FakeFactory()
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "mailbox.json"
            result = self.module.configure_mailbox(
                provider_key="gmail.com",
                email_address="person@gmail.com",
                config_path=config,
                providers=providers,
                auth_reader=lambda _: SECRET,
                imap_factory=factory,
            )
            stored = json.loads(config.read_text())
            mode = stat.S_IMODE(config.stat().st_mode)
        self.assertEqual(stored["mailboxes"][0]["auth_code"], SECRET)
        self.assertEqual(mode, 0o600)
        self.assertNotIn(SECRET, json.dumps(result, ensure_ascii=False))

    def test_login_error_does_not_echo_server_or_auth_secret(self) -> None:
        factory = FakeFactory(login_error=imaplib.IMAP4.error(SECRET))
        result = self.module.probe_mailboxes(
            [self.mailbox], imap_factory=factory
        )
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "error")
        self.assertNotIn(SECRET, serialized)

    def test_providers_schema_and_expected_domains(self) -> None:
        providers = self.module.load_providers(PROVIDERS)
        expected = {
            "gmail.com",
            "outlook.com",
            "hotmail.com",
            "163.com",
            "126.com",
            "yeah.net",
            "qq.com",
            "foxmail.com",
        }
        self.assertEqual(set(providers), expected)
        for provider in providers.values():
            self.assertEqual(provider["imap_port"], 993)
            self.assertTrue(provider["trash_folder"])
            self.assertTrue(provider["quirks"])


if __name__ == "__main__":
    unittest.main()
