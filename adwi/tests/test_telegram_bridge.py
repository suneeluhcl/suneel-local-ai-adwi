"""
tests/test_telegram_bridge.py — Unit tests for the Telegram bridge.

Tests run entirely offline — no real Telegram token, no live API calls.
Safe to run in CI or any environment.

Run:
    python3 -m unittest adwi/tests/test_telegram_bridge.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Load bridge module without executing main() ───────────────────────────────
_BRIDGE_PATH = Path(__file__).parent.parent / "services" / "telegram-bridge" / "bot.py"
_spec = importlib.util.spec_from_file_location("telegram_bridge", _BRIDGE_PATH)
_mod  = importlib.util.module_from_spec(_spec)   # type: ignore[arg-type]
_spec.loader.exec_module(_mod)                    # type: ignore[union-attr]
bridge = _mod

TOKEN       = "1234567890:fake_token_for_tests"
ALLOWED_UID = 123456789
SECRET      = "test-secret-value"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_update(sender_id: int, text: str, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": sender_id, "first_name": "Test"},
            "chat": {"id": sender_id},
            "text": text,
        },
    }


def _replies(update: dict) -> list[str]:
    """Collect all _send_reply texts triggered by handling update."""
    sent: list[str] = []
    with patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)), \
         patch.object(bridge, "_call_adwi", return_value="mock-api-result"):
        bridge._handle_update(update, TOKEN, ALLOWED_UID, SECRET)
    return sent


def _api_calls(update: dict) -> list[str]:
    """Collect all _call_adwi route arguments triggered by handling update."""
    calls: list[str] = []
    with patch.object(bridge, "_call_adwi", side_effect=lambda r, s: calls.append(r) or "ok"), \
         patch.object(bridge, "_send_reply", lambda *a, **k: None):
        bridge._handle_update(update, TOKEN, ALLOWED_UID, SECRET)
    return calls


# ── 1. Sender allowlist ───────────────────────────────────────────────────────

class TestSenderAllowlist(unittest.TestCase):

    def test_known_sender_gets_response(self):
        replies = _replies(_make_update(ALLOWED_UID, "/help"))
        self.assertGreater(len(replies), 0, "Allowed sender must receive a reply")

    def test_unknown_sender_silently_dropped(self):
        replies = _replies(_make_update(99999, "/status"))
        self.assertEqual(replies, [], "Unknown sender must receive NO reply")

    def test_unknown_sender_cannot_trigger_api(self):
        calls = _api_calls(_make_update(88888, "/status"))
        self.assertEqual(calls, [], "Unknown sender must not reach command API")

    def test_zero_uid_rejected(self):
        # 0 is not a valid Telegram user ID and must not match ALLOWED_UID
        replies = _replies(_make_update(0, "/help"))
        self.assertEqual(replies, [])

    def test_off_by_one_uid_rejected(self):
        replies = _replies(_make_update(ALLOWED_UID + 1, "/status"))
        self.assertEqual(replies, [])

    def test_allowlist_uses_numeric_id_not_username(self):
        # Telegram message with a different ID but same name is still blocked
        update = {
            "update_id": 2,
            "message": {
                "from": {"id": 111111, "first_name": "Suneel"},
                "chat": {"id": 111111},
                "text": "/help",
            },
        }
        replies = _replies(update)
        self.assertEqual(replies, [])


# ── 2. Command allowlist ──────────────────────────────────────────────────────

class TestCommandAllowlist(unittest.TestCase):

    def test_all_listed_commands_accepted(self):
        safe_commands = [cmd for cmd, route in bridge.TELEGRAM_COMMANDS.items()
                         if route is not None]
        for cmd in safe_commands:
            with self.subTest(cmd=cmd):
                calls = _api_calls(_make_update(ALLOWED_UID, cmd))
                self.assertEqual(len(calls), 1, f"{cmd} must dispatch exactly one API call")

    def test_help_handled_locally_no_api_call(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/help"))
        self.assertEqual(calls, [], "/help must not call command API")

    def test_help_response_lists_commands(self):
        replies = _replies(_make_update(ALLOWED_UID, "/help"))
        self.assertEqual(len(replies), 1)
        self.assertIn("/status", replies[0])
        self.assertIn("/doctor", replies[0])

    def test_unlisted_command_returns_error_message(self):
        replies = _replies(_make_update(ALLOWED_UID, "/unknown-cmd"))
        self.assertTrue(any("Unknown command" in r for r in replies),
                        "Unlisted command must get an 'Unknown command' reply")

    def test_unlisted_command_does_not_reach_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/unknown-cmd"))
        self.assertEqual(calls, [])

    def test_status_routes_to_adwi_status(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/status"))
        self.assertIn("/adwi-status", calls)

    def test_doctor_routes_to_adwi_doctor(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/doctor"))
        self.assertIn("/adwi-doctor", calls)

    def test_brief_routes_to_adwi_brief(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/brief"))
        self.assertIn("/adwi-brief", calls)

    def test_daily_brief_routes_to_n8n_route(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/daily-brief"))
        self.assertIn("/adwi-daily-brief-n8n", calls)

    def test_git_status_routes_correctly(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/git-status"))
        self.assertIn("/git-status-workspace", calls)

    def test_models_routes_to_adwi_models(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/models"))
        self.assertIn("/adwi-models", calls)

    def test_watcher_status_routes_to_adwi_watcher_status(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/watcher-status"))
        self.assertIn("/adwi-watcher-status", calls)

    def test_help_lists_models_and_watcher(self):
        replies = _replies(_make_update(ALLOWED_UID, "/help"))
        self.assertEqual(len(replies), 1)
        self.assertIn("/models", replies[0])
        self.assertIn("/watcher-status", replies[0])


# ── 3. Dangerous commands rejected ───────────────────────────────────────────

class TestDangerousCommandsRejected(unittest.TestCase):
    """Every mutation / shell / patching command must be rejected by the allowlist."""

    DANGEROUS = [
        "/run-bash",
        "/run-python",
        "/patch-adwi",
        "/self-heal",
        "/fix-error",
        "/implement-idea",
        "/notify",
        "/git-commit",
        "/git-push",
        "/e2e-auto-loop",
        "/nightly-run",
        "/gmail-send",
        "/gmail-confirm",
        "/gmail-archive",
        "/gmail-trash",
        "/memory-scan",
        "/file-write",
        "/obsidian-write",
        "/benchmark",
        "/daily-improve",
    ]

    def test_dangerous_commands_never_reach_api(self):
        for cmd in self.DANGEROUS:
            with self.subTest(cmd=cmd):
                calls = _api_calls(_make_update(ALLOWED_UID, cmd))
                self.assertEqual(calls, [],
                                 f"{cmd} must not dispatch to command API")

    def test_dangerous_commands_get_unknown_reply(self):
        for cmd in self.DANGEROUS:
            with self.subTest(cmd=cmd):
                replies = _replies(_make_update(ALLOWED_UID, cmd))
                reached_api = any("mock-api-result" in r for r in replies)
                self.assertFalse(reached_api,
                                 f"{cmd} reply must not contain API output")


# ── 4. Response truncation ────────────────────────────────────────────────────

class TestResponseTruncation(unittest.TestCase):

    def _sent_texts(self, text: str) -> list[str]:
        sent: list[str] = []
        with patch.object(bridge, "_tg_post", lambda t, m, p: sent.append(p["text"])):
            bridge._send_reply(TOKEN, 1, text)
        return sent

    def test_short_reply_unchanged(self):
        sent = self._sent_texts("hello world")
        self.assertEqual(sent, ["hello world"])

    def test_reply_at_exact_limit_not_truncated(self):
        text = "x" * bridge.REPLY_MAX_LEN
        sent = self._sent_texts(text)
        self.assertEqual(sent[0], text)

    def test_reply_over_limit_is_truncated(self):
        text = "y" * (bridge.REPLY_MAX_LEN + 500)
        sent = self._sent_texts(text)
        self.assertLessEqual(len(sent[0]), bridge.REPLY_MAX_LEN + 20,
                             "Truncated reply must not exceed limit + ellipsis")
        self.assertIn("truncated", sent[0], "Truncated reply must contain 'truncated' marker")

    def test_truncation_ellipsis_appended(self):
        text = "z" * 5000
        sent = self._sent_texts(text)
        self.assertTrue(sent[0].endswith("…[truncated]") or "truncated" in sent[0])


# ── 5. Telegram @BotUsername suffix stripped ──────────────────────────────────

class TestBotUsernameSuffix(unittest.TestCase):
    """Telegram appends @BotName to commands sent in groups — must be stripped."""

    def test_at_suffix_stripped_status(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/status@MyAdwiBot"))
        self.assertIn("/adwi-status", calls)

    def test_at_suffix_stripped_doctor(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/doctor@MyAdwiBot"))
        self.assertIn("/adwi-doctor", calls)

    def test_at_suffix_stripped_help(self):
        replies = _replies(_make_update(ALLOWED_UID, "/help@MyAdwiBot"))
        self.assertGreater(len(replies), 0)
        self.assertIn("/status", replies[0])


# ── 6. Non-message update types ignored ──────────────────────────────────────

class TestNonMessageUpdates(unittest.TestCase):

    def test_update_with_no_message_field_ignored(self):
        calls = _api_calls({"update_id": 99})
        self.assertEqual(calls, [])

    def test_channel_post_no_from_ignored(self):
        # Channel posts have no "from" field
        update = {
            "update_id": 100,
            "message": {
                "chat": {"id": -1001234567},
                "text": "/status",
            },
        }
        calls = _api_calls(update)
        self.assertEqual(calls, [])

    def test_empty_text_ignored(self):
        update = _make_update(ALLOWED_UID, "")
        calls = _api_calls(update)
        self.assertEqual(calls, [])


# ── 7. Config dict shape ──────────────────────────────────────────────────────

class TestCommandTableShape(unittest.TestCase):

    def test_all_routes_start_with_slash_or_are_none(self):
        for cmd, route in bridge.TELEGRAM_COMMANDS.items():
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    route is None or route.startswith("/"),
                    f"Route for {cmd} must be None or start with '/'"
                )

    def test_all_commands_start_with_slash(self):
        for cmd in bridge.TELEGRAM_COMMANDS:
            self.assertTrue(cmd.startswith("/"), f"{cmd} must start with '/'")

    def test_telegram_commands_is_dict(self):
        self.assertIsInstance(bridge.TELEGRAM_COMMANDS, dict)

    def test_help_key_exists(self):
        self.assertIn("/help", bridge.TELEGRAM_COMMANDS)

    def test_help_has_no_route(self):
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/help"])


# ── 8. /daily-brief JSON formatter ───────────────────────────────────────────

class TestDailyBriefFormatter(unittest.TestCase):

    _VALID_PAYLOAD: dict = {
        "ok": True,
        "generated_at": "2026-06-20T10:45:30.123456",
        "mode": "n8n",
        "services": {"ollama": "up", "qdrant": "up", "safe_api": "up"},
        "gmail": {
            "available": True,
            "unread_count": 2,
            "summary": "• alice@example.com: Hello there\n• bob@example.com: Meeting notes",
            "warnings": [],
        },
        "brief": "**Priorities**\n1. Finish the NLU fixes\n2. Review PR\n\n**Inbox**\nAlice email needs reply.\n\n**Learning**\nRead the LangGraph docs.",
        "saved_to": "/tmp/2026-06-20.md",
        "warnings": [],
        "errors": [],
    }

    def _raw(self, overrides: dict | None = None) -> str:
        payload = {**self._VALID_PAYLOAD}
        if overrides:
            payload.update(overrides)
        return json.dumps(payload)

    def test_valid_json_produces_readable_text(self):
        result = bridge._format_daily_brief(self._raw())
        self.assertIn("Daily Brief", result)
        self.assertIn("2026-06-20 10:45", result)
        self.assertIn("ollama=up", result)
        self.assertIn("2 unread today", result)
        self.assertIn("alice@example.com", result)
        self.assertIn("Priorities", result)
        self.assertIn("Finish the NLU fixes", result)

    def test_bold_markers_stripped(self):
        result = bridge._format_daily_brief(self._raw())
        self.assertNotIn("**", result, "Markdown ** must be stripped for plain-text Telegram")

    def test_malformed_json_returns_raw(self):
        raw = '{"ok": true, "brief": "unterminated'
        self.assertEqual(bridge._format_daily_brief(raw), raw)

    def test_non_json_string_passthrough(self):
        raw = "This is plain text, not JSON at all."
        self.assertEqual(bridge._format_daily_brief(raw), raw)

    def test_json_without_ok_field_passthrough(self):
        raw = json.dumps({"generated_at": "2026-06-20", "brief": "hello"})
        self.assertEqual(bridge._format_daily_brief(raw), raw, "JSON without ok=true must pass through")

    def test_json_with_ok_false_passthrough(self):
        raw = json.dumps({"ok": False, "error": "something went wrong"})
        self.assertEqual(bridge._format_daily_brief(raw), raw)

    def test_inbox_clear_when_zero_unread(self):
        result = bridge._format_daily_brief(self._raw({
            "gmail": {**self._VALID_PAYLOAD["gmail"], "unread_count": 0, "summary": "Inbox clear."},
        }))
        self.assertIn("Inbox clear.", result)

    def test_gmail_warning_shown_when_unavailable(self):
        result = bridge._format_daily_brief(self._raw({
            "gmail": {**self._VALID_PAYLOAD["gmail"],
                      "available": False,
                      "warnings": ["Gmail not authorized — run /gmail-auth"]},
        }))
        self.assertIn("Gmail not authorized", result)

    def test_system_level_warnings_shown(self):
        result = bridge._format_daily_brief(self._raw({
            "warnings": ["Obsidian save skipped: connection refused"],
        }))
        self.assertIn("Obsidian save skipped", result)

    def test_system_level_errors_shown(self):
        result = bridge._format_daily_brief(self._raw({
            "errors": ["LLM timeout after 60s"],
        }))
        self.assertIn("LLM timeout", result)

    def test_empty_brief_field_handled_gracefully(self):
        result = bridge._format_daily_brief(self._raw({"brief": ""}))
        self.assertIn("Daily Brief", result)  # header always present; no crash

    def test_formatter_applied_when_daily_brief_dispatched(self):
        """_format_daily_brief must be called when /daily-brief is dispatched."""
        called_with: list[str] = []

        def mock_fmt(raw: str) -> str:
            called_with.append(raw)
            return "FORMATTED"

        with patch.object(bridge, "_format_daily_brief", mock_fmt), \
             patch.object(bridge, "_call_adwi", return_value='{"ok":true}'), \
             patch.object(bridge, "_send_reply", lambda *a: None):
            bridge._handle_update(
                _make_update(ALLOWED_UID, "/daily-brief"),
                TOKEN, ALLOWED_UID, SECRET,
            )
        self.assertGreater(len(called_with), 0, "Formatter must be called for /daily-brief")

    def test_formatter_not_applied_to_status(self):
        """/status output must never pass through the daily-brief formatter."""
        called_with: list[str] = []

        def mock_fmt(raw: str) -> str:
            called_with.append(raw)
            return "FORMATTED"

        with patch.object(bridge, "_format_daily_brief", mock_fmt), \
             patch.object(bridge, "_call_adwi", return_value="status output"), \
             patch.object(bridge, "_send_reply", lambda *a: None):
            bridge._handle_update(
                _make_update(ALLOWED_UID, "/status"),
                TOKEN, ALLOWED_UID, SECRET,
            )
        self.assertEqual(called_with, [], "Formatter must NOT be called for /status")

    def test_formatter_not_applied_to_doctor(self):
        """/doctor output must never pass through the daily-brief formatter."""
        called_with: list[str] = []

        def mock_fmt(raw: str) -> str:
            called_with.append(raw)
            return "FORMATTED"

        with patch.object(bridge, "_format_daily_brief", mock_fmt), \
             patch.object(bridge, "_call_adwi", return_value="doctor output"), \
             patch.object(bridge, "_send_reply", lambda *a: None):
            bridge._handle_update(
                _make_update(ALLOWED_UID, "/doctor"),
                TOKEN, ALLOWED_UID, SECRET,
            )
        self.assertEqual(called_with, [], "Formatter must NOT be called for /doctor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
