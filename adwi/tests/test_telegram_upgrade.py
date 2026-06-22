"""
test_telegram_upgrade.py — Tests for Wave 4 Telegram bridge additions.

Covers:
  - New Safe API commands: /services /obsidian /git /git_diff /git_log
  - Background job commands: /test_quick /test_nlu /test_obsidian /test_all
  - Job management: /jobs /job /cancel /tests_status
  - Learn/capture: /capture /idea /plan /obsidian_review /obsidian_plan
                   /obsidian_validate /memory_scan
  - Repair gate: /repair_plan /repair_ok
  - Git backup gate: /git_backup /backup_ok
  - UX: /menu MENU_TEXT
  - Job runner: submit / status / list_recent / cancel / tail_log
  - Text helpers: _redact _sanitize_text
  - Confirmation gate: _make_token _consume_token expiry
"""

from __future__ import annotations

import importlib.util
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Module loader helpers ─────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent.parent  # SuneelWorkSpace
_BOT_PATH = _ROOT / "adwi" / "services" / "telegram-bridge" / "bot.py"
_JR_PATH  = _ROOT / "adwi" / "services" / "telegram-bridge" / "job_runner.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)   # type: ignore[arg-type]
    spec.loader.exec_module(mod)                    # type: ignore[union-attr]
    return mod


bridge = _load("bridge", _BOT_PATH)
jr     = _load("job_runner_mod", _JR_PATH)

# ── Test helpers ──────────────────────────────────────────────────────────────

TOKEN       = "test-token"
ALLOWED_UID = 123456789
SECRET      = "test-secret"


def _make_update(uid: int, text: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "chat": {"id": uid},
            "from": {"id": uid},
            "text": text,
        },
    }


def _replies(update: dict) -> list[str]:
    """Capture all replies for a given update (mocks both _call_adwi and _send_reply)."""
    sent: list[str] = []
    with patch.object(bridge, "_call_adwi", return_value="mock-api-response"), \
         patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
        bridge._handle_update(update, TOKEN, ALLOWED_UID, SECRET)
    return sent


def _api_calls(update: dict) -> list[str]:
    """Return the list of Safe API routes called for the update."""
    routes: list[str] = []
    with patch.object(bridge, "_call_adwi",
                      side_effect=lambda r, s: routes.append(r) or "mock") as m, \
         patch.object(bridge, "_send_reply", lambda *a: None):
        bridge._handle_update(update, TOKEN, ALLOWED_UID, SECRET)
    return routes


def _local_reply(cmd: str, args: str = "", mock_runner=None) -> str:
    """Run a local command and return the first reply."""
    sent: list[str] = []
    runner = mock_runner or MagicMock()
    with patch.object(bridge, "_JOB_RUNNER", runner), \
         patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
        text = f"{cmd} {args}".strip()
        bridge._handle_local_cmd(cmd, args, TOKEN, ALLOWED_UID, SECRET)
    return sent[0] if sent else ""


# ═══════════════════════════════════════════════════════════════════════════════
# New Safe API commands
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewSafeApiCommands(unittest.TestCase):
    """Wave 4 commands that route through the Safe API (/services, /obsidian, /git, etc.)"""

    def test_services_in_command_table(self):
        self.assertIn("/services", bridge.TELEGRAM_COMMANDS)

    def test_services_routes_to_adwi_services(self):
        self.assertEqual(bridge.TELEGRAM_COMMANDS["/services"], "/adwi-services")

    def test_obsidian_in_command_table(self):
        self.assertIn("/obsidian", bridge.TELEGRAM_COMMANDS)

    def test_obsidian_routes_to_obsidian_status(self):
        self.assertEqual(bridge.TELEGRAM_COMMANDS["/obsidian"], "/adwi-obsidian-status")

    def test_git_alias_in_command_table(self):
        self.assertIn("/git", bridge.TELEGRAM_COMMANDS)

    def test_git_alias_routes_to_workspace_status(self):
        self.assertEqual(bridge.TELEGRAM_COMMANDS["/git"], "/git-status-workspace")

    def test_git_diff_in_command_table(self):
        self.assertIn("/git_diff", bridge.TELEGRAM_COMMANDS)

    def test_git_diff_routes_to_adwi_git_diff(self):
        self.assertEqual(bridge.TELEGRAM_COMMANDS["/git_diff"], "/adwi-git-diff")

    def test_git_log_in_command_table(self):
        self.assertIn("/git_log", bridge.TELEGRAM_COMMANDS)

    def test_git_log_routes_to_adwi_git_log(self):
        self.assertEqual(bridge.TELEGRAM_COMMANDS["/git_log"], "/adwi-git-log")

    def test_services_reaches_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/services"))
        self.assertEqual(calls, ["/adwi-services"])

    def test_obsidian_reaches_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/obsidian"))
        self.assertEqual(calls, ["/adwi-obsidian-status"])

    def test_git_reaches_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/git"))
        self.assertEqual(calls, ["/git-status-workspace"])

    def test_git_diff_reaches_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/git_diff"))
        self.assertEqual(calls, ["/adwi-git-diff"])

    def test_git_log_reaches_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/git_log"))
        self.assertEqual(calls, ["/adwi-git-log"])

    def test_new_routes_not_dangerous(self):
        dangerous = [
            "run-bash", "run-python", "patch-adwi", "self-heal",
            "git-commit", "git-push", "obsidian-write", "backup-now",
        ]
        new_routes = ["/adwi-services", "/adwi-obsidian-status", "/adwi-git-diff", "/adwi-git-log"]
        for route in new_routes:
            for pat in dangerous:
                self.assertNotIn(pat, route, f"Route {route!r} contains dangerous pattern {pat!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# Menu / UX
# ═══════════════════════════════════════════════════════════════════════════════

class TestMenuCommand(unittest.TestCase):
    def test_menu_in_command_table(self):
        self.assertIn("/menu", bridge.TELEGRAM_COMMANDS)

    def test_menu_is_locally_handled(self):
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/menu"])

    def test_menu_does_not_call_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/menu"))
        self.assertEqual(calls, [])

    def test_menu_returns_reply(self):
        replies = _replies(_make_update(ALLOWED_UID, "/menu"))
        self.assertGreater(len(replies), 0)

    def test_menu_text_mentions_key_sections(self):
        text = bridge.MENU_TEXT
        for section in ["STATUS", "TESTS", "CAPTURE", "REPAIR", "GIT BACKUP"]:
            self.assertIn(section.upper(), text.upper(),
                          f"MENU_TEXT missing section: {section!r}")

    def test_menu_text_mentions_test_commands(self):
        text = bridge.MENU_TEXT
        for cmd in ["/test_quick", "/test_nlu", "/tests_status"]:
            self.assertIn(cmd, text)

    def test_menu_text_mentions_capture(self):
        self.assertIn("/capture", bridge.MENU_TEXT)

    def test_menu_text_shows_command_count(self):
        # MENU_TEXT header should include the total count
        n = str(len(bridge.TELEGRAM_COMMANDS))
        self.assertIn(n, bridge.MENU_TEXT)

    def test_total_command_count_wave4(self):
        self.assertGreaterEqual(len(bridge.TELEGRAM_COMMANDS), 39)


# ═══════════════════════════════════════════════════════════════════════════════
# Test background job commands
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackgroundTestCommands(unittest.TestCase):
    def setUp(self):
        self.mock_runner = MagicMock()
        self.mock_runner.submit.return_value = "test-quick-20260622-101234-ab12"

    def _run_job_cmd(self, cmd: str) -> list[str]:
        sent: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", self.mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, cmd), TOKEN, ALLOWED_UID, SECRET)
        return sent

    def test_test_quick_in_table(self):
        self.assertIn("/test_quick", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/test_quick"])

    def test_test_nlu_in_table(self):
        self.assertIn("/test_nlu", bridge.TELEGRAM_COMMANDS)

    def test_test_obsidian_in_table(self):
        self.assertIn("/test_obsidian", bridge.TELEGRAM_COMMANDS)

    def test_test_all_in_table(self):
        self.assertIn("/test_all", bridge.TELEGRAM_COMMANDS)

    def test_tests_status_in_table(self):
        self.assertIn("/tests_status", bridge.TELEGRAM_COMMANDS)

    def test_test_quick_submits_job(self):
        self._run_job_cmd("/test_quick")
        self.mock_runner.submit.assert_called_once()
        name, argv = self.mock_runner.submit.call_args[0]
        self.assertEqual(name, "test-quick")
        self.assertIsInstance(argv, list)

    def test_test_nlu_submits_job(self):
        self._run_job_cmd("/test_nlu")
        self.mock_runner.submit.assert_called_once()
        name, _ = self.mock_runner.submit.call_args[0]
        self.assertEqual(name, "test-nlu")

    def test_test_obsidian_submits_job(self):
        self._run_job_cmd("/test_obsidian")
        self.mock_runner.submit.assert_called_once()
        name, _ = self.mock_runner.submit.call_args[0]
        self.assertEqual(name, "test-obsidian")

    def test_test_all_submits_job(self):
        self._run_job_cmd("/test_all")
        self.mock_runner.submit.assert_called_once()
        name, _ = self.mock_runner.submit.call_args[0]
        self.assertEqual(name, "test-all")

    def test_test_quick_reply_contains_job_id(self):
        replies = self._run_job_cmd("/test_quick")
        job_id  = self.mock_runner.submit.return_value
        self.assertTrue(any(job_id in r for r in replies),
                        f"No reply contained job ID {job_id!r}")

    def test_test_commands_do_not_call_safe_api(self):
        calls = _api_calls(_make_update(ALLOWED_UID, "/test_quick"))
        self.assertEqual(calls, [])

    def test_no_runner_returns_error(self):
        sent: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", None), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/test_quick"),
                                  TOKEN, ALLOWED_UID, SECRET)
        self.assertTrue(any("error" in r.lower() for r in sent))


# ═══════════════════════════════════════════════════════════════════════════════
# Job management
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobManagement(unittest.TestCase):
    def setUp(self):
        self.mock_runner = MagicMock()

    def _run(self, cmd: str) -> list[str]:
        sent: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", self.mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, cmd), TOKEN, ALLOWED_UID, SECRET)
        return sent

    def test_jobs_in_table(self):
        self.assertIn("/jobs", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/jobs"])

    def test_job_in_table(self):
        self.assertIn("/job", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/job"])

    def test_cancel_in_table(self):
        self.assertIn("/cancel", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/cancel"])

    def test_jobs_calls_list_recent(self):
        self.mock_runner.list_recent.return_value = []
        self._run("/jobs")
        self.mock_runner.list_recent.assert_called_once()

    def test_jobs_no_jobs_message(self):
        self.mock_runner.list_recent.return_value = []
        replies = self._run("/jobs")
        self.assertTrue(any("no jobs" in r.lower() for r in replies))

    def test_job_calls_status(self):
        self.mock_runner.status.return_value = {
            "id": "test-123", "type": "test-quick", "status": "succeeded",
            "start_time": "2026-06-22T10:00:00", "end_time": "2026-06-22T10:01:00",
            "returncode": 0, "log_path": "/tmp/test.log",
        }
        self.mock_runner.tail_log.return_value = "all tests passed"
        self._run("/job test-123")
        self.mock_runner.status.assert_called_once_with("test-123")

    def test_job_no_id_returns_usage(self):
        replies = self._run("/job")
        self.assertTrue(any("usage" in r.lower() for r in replies))

    def test_cancel_calls_cancel(self):
        self.mock_runner.cancel.return_value = True
        self._run("/cancel abc-123")
        self.mock_runner.cancel.assert_called_once_with("abc-123")

    def test_cancel_no_id_returns_usage(self):
        replies = self._run("/cancel")
        self.assertTrue(any("usage" in r.lower() for r in replies))

    def test_cancel_success_message(self):
        self.mock_runner.cancel.return_value = True
        replies = self._run("/cancel abc-123")
        self.assertTrue(any("cancel" in r.lower() for r in replies))

    def test_cancel_fail_message(self):
        self.mock_runner.cancel.return_value = False
        replies = self._run("/cancel abc-123")
        self.assertTrue(any("not" in r.lower() or "found" in r.lower() for r in replies))


# ═══════════════════════════════════════════════════════════════════════════════
# Capture command
# ═══════════════════════════════════════════════════════════════════════════════

class TestCaptureCommand(unittest.TestCase):
    def setUp(self):
        self.mock_runner = MagicMock()

    def _run(self, text: str) -> list[str]:
        sent: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", self.mock_runner), \
             patch.object(bridge, "_run_quick", return_value="captured."), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, text), TOKEN, ALLOWED_UID, SECRET)
        return sent

    def test_capture_in_table(self):
        self.assertIn("/capture", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/capture"])

    def test_capture_no_args_shows_usage(self):
        replies = self._run("/capture")
        self.assertTrue(any("usage" in r.lower() or "type" in r.lower() for r in replies))

    def test_capture_invalid_type_shows_error(self):
        replies = self._run("/capture widget some text")
        self.assertTrue(any("unknown" in r.lower() or "invalid" in r.lower() or "type" in r.lower()
                            for r in replies))

    def test_capture_idea_invokes_run_quick(self):
        called = []
        def fake_run_quick(argv, **kw):
            called.append(argv)
            return "ok"
        sent: list[str] = []
        with patch.object(bridge, "_run_quick", fake_run_quick), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/capture idea Fast PDF summarizer"),
                                  TOKEN, ALLOWED_UID, SECRET)
        self.assertTrue(len(called) > 0)
        argv = called[0]
        self.assertIn("/obsidian-capture", argv)
        self.assertIn("idea", argv)
        self.assertIn("Fast PDF summarizer", argv)

    def test_capture_no_text_shows_usage(self):
        replies = self._run("/capture idea")
        self.assertTrue(any("usage" in r.lower() for r in replies))

    def test_capture_valid_types(self):
        valid_types = ["idea", "decision", "bug", "fix", "note", "approval"]
        for t in valid_types:
            with self.subTest(type=t):
                called = []
                def fake_run(argv, **kw):
                    called.append(argv)
                    return "ok"
                with patch.object(bridge, "_run_quick", fake_run), \
                     patch.object(bridge, "_send_reply", lambda *a: None):
                    bridge._handle_update(_make_update(ALLOWED_UID, f"/capture {t} some text"),
                                          TOKEN, ALLOWED_UID, SECRET)
                self.assertTrue(len(called) > 0, f"No subprocess for type={t!r}")

    def test_capture_sanitizes_control_chars(self):
        captured_argv = []
        def fake_run(argv, **kw):
            captured_argv.extend(argv)
            return "ok"
        with patch.object(bridge, "_run_quick", fake_run), \
             patch.object(bridge, "_send_reply", lambda *a: None):
            bridge._handle_update(
                _make_update(ALLOWED_UID, "/capture idea hello\x00world\x01test"),
                TOKEN, ALLOWED_UID, SECRET,
            )
        # null bytes should be stripped from the argument
        for arg in captured_argv:
            self.assertNotIn("\x00", arg)


# ═══════════════════════════════════════════════════════════════════════════════
# Idea and plan commands
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdeaAndPlanCommands(unittest.TestCase):
    def test_idea_in_table(self):
        self.assertIn("/idea", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/idea"])

    def test_plan_in_table(self):
        self.assertIn("/plan", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/plan"])

    def test_idea_no_text_shows_usage(self):
        sent: list[str] = []
        with patch.object(bridge, "_run_quick", return_value="ok"), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/idea"), TOKEN, ALLOWED_UID, SECRET)
        self.assertTrue(any("usage" in r.lower() for r in sent))

    def test_plan_no_text_shows_usage(self):
        sent: list[str] = []
        with patch.object(bridge, "_run_quick", return_value="ok"), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/plan"), TOKEN, ALLOWED_UID, SECRET)
        self.assertTrue(any("usage" in r.lower() for r in sent))

    def test_idea_calls_obsidian_capture(self):
        called = []
        def fake_run(argv, **kw):
            called.append(argv)
            return "captured"
        with patch.object(bridge, "_run_quick", fake_run), \
             patch.object(bridge, "_send_reply", lambda *a: None):
            bridge._handle_update(
                _make_update(ALLOWED_UID, "/idea Build a PDF summarizer"),
                TOKEN, ALLOWED_UID, SECRET,
            )
        self.assertTrue(any("/obsidian-capture" in str(a) for a in called))
        self.assertTrue(any("idea" in str(a) for a in called))


# ═══════════════════════════════════════════════════════════════════════════════
# Obsidian background commands
# ═══════════════════════════════════════════════════════════════════════════════

class TestObsidianBackgroundCommands(unittest.TestCase):
    def setUp(self):
        self.mock_runner = MagicMock()
        self.mock_runner.submit.return_value = "obsidian-review-20260622-101234-ab12"

    def _run(self, cmd: str) -> list[str]:
        sent: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", self.mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, cmd), TOKEN, ALLOWED_UID, SECRET)
        return sent

    def test_obsidian_review_in_table(self):
        self.assertIn("/obsidian_review", bridge.TELEGRAM_COMMANDS)

    def test_obsidian_plan_in_table(self):
        self.assertIn("/obsidian_plan", bridge.TELEGRAM_COMMANDS)

    def test_obsidian_validate_in_table(self):
        self.assertIn("/obsidian_validate", bridge.TELEGRAM_COMMANDS)

    def test_memory_scan_in_table(self):
        self.assertIn("/memory_scan", bridge.TELEGRAM_COMMANDS)

    def test_obsidian_review_submits_job(self):
        self._run("/obsidian_review")
        self.mock_runner.submit.assert_called_once()
        name, _ = self.mock_runner.submit.call_args[0]
        self.assertEqual(name, "obsidian-review")

    def test_obsidian_plan_submits_job(self):
        self._run("/obsidian_plan")
        self.mock_runner.submit.assert_called_once()
        name, _ = self.mock_runner.submit.call_args[0]
        self.assertEqual(name, "obsidian-plan")

    def test_obsidian_validate_submits_job(self):
        self._run("/obsidian_validate")
        self.mock_runner.submit.assert_called_once()
        name, _ = self.mock_runner.submit.call_args[0]
        self.assertEqual(name, "obsidian-validate")

    def test_memory_scan_calls_run_quick(self):
        called = []
        with patch.object(bridge, "_run_quick", lambda *a, **k: called.append(a) or "ok"), \
             patch.object(bridge, "_send_reply", lambda *a: None):
            bridge._handle_update(_make_update(ALLOWED_UID, "/memory_scan"),
                                  TOKEN, ALLOWED_UID, SECRET)
        self.assertTrue(len(called) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Repair gate
# ═══════════════════════════════════════════════════════════════════════════════

class TestRepairGate(unittest.TestCase):
    def test_repair_plan_in_table(self):
        self.assertIn("/repair_plan", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/repair_plan"])

    def test_repair_ok_in_table(self):
        self.assertIn("/repair_ok", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/repair_ok"])

    def test_repair_plan_generates_token(self):
        sent: list[str] = []
        mock_runner = MagicMock()
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)), \
             patch("py_compile.compile"):
            bridge._handle_update(_make_update(ALLOWED_UID, "/repair_plan"),
                                  TOKEN, ALLOWED_UID, SECRET)
        combined = " ".join(sent)
        self.assertIn("/repair_ok", combined)
        # Should contain an 8-char hex token
        import re
        tokens = re.findall(r'/repair_ok\s+([0-9a-f]{8})', combined)
        self.assertTrue(len(tokens) > 0, f"No token found in: {combined!r}")

    def test_repair_ok_invalid_token_rejected(self):
        sent: list[str] = []
        mock_runner = MagicMock()
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/repair_ok badtoken"),
                                  TOKEN, ALLOWED_UID, SECRET)
        combined = " ".join(sent).lower()
        self.assertTrue("invalid" in combined or "expired" in combined,
                        f"Expected rejection message, got: {combined!r}")

    def test_repair_ok_without_token_shows_usage(self):
        sent: list[str] = []
        mock_runner = MagicMock()
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/repair_ok"),
                                  TOKEN, ALLOWED_UID, SECRET)
        combined = " ".join(sent).lower()
        self.assertTrue("usage" in combined or "token" in combined)

    def test_repair_ok_valid_token_starts_job(self):
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "repair-20260622-ab12"

        # First get a valid token
        sent_plan: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent_plan.append(msg)), \
             patch("py_compile.compile"):
            bridge._handle_update(_make_update(ALLOWED_UID, "/repair_plan"),
                                  TOKEN, ALLOWED_UID, SECRET)

        import re
        tokens = re.findall(r'/repair_ok\s+([0-9a-f]{8})', " ".join(sent_plan))
        self.assertTrue(tokens, "repair_plan did not produce a token")
        token = tokens[0]

        # Now confirm with the token
        sent_confirm: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent_confirm.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, f"/repair_ok {token}"),
                                  TOKEN, ALLOWED_UID, SECRET)

        mock_runner.submit.assert_called_once()
        combined = " ".join(sent_confirm).lower()
        self.assertTrue("repair" in combined or "job" in combined)

    def test_repair_ok_token_single_use(self):
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "repair-20260622-ab12"

        sent_plan: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent_plan.append(msg)), \
             patch("py_compile.compile"):
            bridge._handle_update(_make_update(ALLOWED_UID, "/repair_plan"),
                                  TOKEN, ALLOWED_UID, SECRET)

        import re
        tokens = re.findall(r'/repair_ok\s+([0-9a-f]{8})', " ".join(sent_plan))
        self.assertTrue(tokens)
        token = tokens[0]

        # First use — should succeed
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda *a: None):
            bridge._handle_update(_make_update(ALLOWED_UID, f"/repair_ok {token}"),
                                  TOKEN, ALLOWED_UID, SECRET)

        # Second use — token consumed, should be rejected
        sent2: list[str] = []
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent2.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, f"/repair_ok {token}"),
                                  TOKEN, ALLOWED_UID, SECRET)
        combined = " ".join(sent2).lower()
        self.assertTrue("invalid" in combined or "expired" in combined)

    def test_repair_does_not_call_safe_api(self):
        routes = _api_calls(_make_update(ALLOWED_UID, "/repair_plan"))
        self.assertEqual(routes, [])

        routes2 = _api_calls(_make_update(ALLOWED_UID, "/repair_ok badtoken"))
        self.assertEqual(routes2, [])


# ═══════════════════════════════════════════════════════════════════════════════
# Git backup gate
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitBackupGate(unittest.TestCase):
    def test_git_backup_in_table(self):
        self.assertIn("/git_backup", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/git_backup"])

    def test_backup_ok_in_table(self):
        self.assertIn("/backup_ok", bridge.TELEGRAM_COMMANDS)
        self.assertIsNone(bridge.TELEGRAM_COMMANDS["/backup_ok"])

    def test_git_backup_generates_token(self):
        sent: list[str] = []
        mock_runner = MagicMock()
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)), \
             patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(stdout="M file.py\n", returncode=0)
            bridge._handle_update(_make_update(ALLOWED_UID, "/git_backup"),
                                  TOKEN, ALLOWED_UID, SECRET)
        combined = " ".join(sent)
        self.assertIn("/backup_ok", combined)

    def test_backup_ok_invalid_token_rejected(self):
        sent: list[str] = []
        mock_runner = MagicMock()
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/backup_ok badbad"),
                                  TOKEN, ALLOWED_UID, SECRET)
        combined = " ".join(sent).lower()
        self.assertTrue("invalid" in combined or "expired" in combined)

    def test_backup_ok_without_token_shows_usage(self):
        sent: list[str] = []
        mock_runner = MagicMock()
        with patch.object(bridge, "_JOB_RUNNER", mock_runner), \
             patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(ALLOWED_UID, "/backup_ok"),
                                  TOKEN, ALLOWED_UID, SECRET)
        combined = " ".join(sent).lower()
        self.assertTrue("usage" in combined or "token" in combined)

    def test_backup_gate_names_not_dangerous(self):
        dangerous = ["backup-now", "git-push", "git-commit"]
        for key in ["/git_backup", "/backup_ok"]:
            for pat in dangerous:
                self.assertNotIn(pat, key,
                                 f"Command {key!r} contains dangerous pattern {pat!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# Confirmation gate internals
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfirmationGate(unittest.TestCase):
    def setUp(self):
        bridge._PENDING.clear()

    def test_make_token_returns_8_hex(self):
        token = bridge._make_token("test_action")
        self.assertRegex(token, r'^[0-9a-f]{8}$')

    def test_consume_token_valid(self):
        token = bridge._make_token("my_action", {"k": "v"})
        result = bridge._consume_token(token)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "my_action")
        self.assertEqual(result["meta"], {"k": "v"})

    def test_consume_token_single_use(self):
        token = bridge._make_token("my_action")
        bridge._consume_token(token)
        result2 = bridge._consume_token(token)
        self.assertIsNone(result2)

    def test_consume_token_invalid_returns_none(self):
        result = bridge._consume_token("deadbeef")
        self.assertIsNone(result)

    def test_consume_token_expired(self):
        # Artificially create an expired entry
        bridge._PENDING["expiredtok"] = {
            "action":     "test",
            "expires_at": time.time() - 10,   # already expired
            "meta":       {},
        }
        result = bridge._consume_token("expiredtok")
        self.assertIsNone(result, "Expired token should be rejected")

    def test_expire_tokens_cleans_up(self):
        bridge._PENDING["old1"] = {"action": "x", "expires_at": time.time() - 100, "meta": {}}
        bridge._PENDING["old2"] = {"action": "x", "expires_at": time.time() - 100, "meta": {}}
        tok = bridge._make_token("fresh")
        bridge._expire_tokens()
        self.assertNotIn("old1", bridge._PENDING)
        self.assertNotIn("old2", bridge._PENDING)
        self.assertIn(tok, bridge._PENDING)


# ═══════════════════════════════════════════════════════════════════════════════
# Text helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestTextHelpers(unittest.TestCase):
    def test_redact_tg_token(self):
        text = "Token: 1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        result = bridge._redact(text)
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", result)
        self.assertIn("[TOKEN-REDACTED]", result)

    def test_redact_api_key_env_pattern(self):
        text = "API_KEY=supersecretvalue123"
        result = bridge._redact(text)
        self.assertIn("[REDACTED]", result)
        self.assertNotIn("supersecretvalue123", result)

    def test_redact_secret_env_pattern(self):
        text = "ADWI_LOCAL=mypassword"
        result = bridge._redact(text)
        self.assertIn("[REDACTED]", result)

    def test_redact_passes_normal_text(self):
        text = "Adwi status: all systems nominal"
        self.assertEqual(bridge._redact(text), text)

    def test_sanitize_text_strips_null(self):
        result = bridge._sanitize_text("hello\x00world")
        self.assertNotIn("\x00", result)

    def test_sanitize_text_strips_control_chars(self):
        result = bridge._sanitize_text("hello\x01\x02world")
        self.assertNotIn("\x01", result)
        self.assertNotIn("\x02", result)

    def test_sanitize_text_truncates(self):
        long_text = "a" * 1000
        result    = bridge._sanitize_text(long_text)
        self.assertLessEqual(len(result), bridge._MAX_ARG_LEN + 10)

    def test_sanitize_text_preserves_normal(self):
        text   = "Build a fast PDF summarizer"
        result = bridge._sanitize_text(text)
        self.assertEqual(result, text)


# ═══════════════════════════════════════════════════════════════════════════════
# JobRunner unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobRunner(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self._orig_jobs_dir  = jr.JOBS_DIR
        self._orig_jobs_file = jr.JOBS_FILE
        jr.JOBS_DIR  = Path(self.tmpdir.name)
        jr.JOBS_FILE = Path(self.tmpdir.name) / "jobs.json"
        self.runner  = jr.JobRunner()

    def tearDown(self):
        jr.JOBS_DIR  = self._orig_jobs_dir
        jr.JOBS_FILE = self._orig_jobs_file
        self.tmpdir.cleanup()

    def test_submit_returns_job_id(self):
        job_id = self.runner.submit("echo-test", ["/bin/echo", "hello"])
        self.assertIsInstance(job_id, str)
        self.assertTrue(job_id.startswith("echo-test-"))

    def test_submit_creates_job_record(self):
        job_id = self.runner.submit("mytest", ["/usr/bin/true"])
        time.sleep(0.2)
        j = self.runner.status(job_id)
        self.assertIsNotNone(j)
        self.assertEqual(j["type"], "mytest")
        self.assertIn(j["status"], ("queued", "running", "succeeded", "failed"))

    def test_successful_job_status(self):
        job_id = self.runner.submit("true-test", ["/usr/bin/true"])
        # Wait for completion
        for _ in range(40):
            time.sleep(0.1)
            j = self.runner.status(job_id)
            if j and j["status"] not in ("queued", "running"):
                break
        j = self.runner.status(job_id)
        self.assertEqual(j["status"], "succeeded")
        self.assertEqual(j["returncode"], 0)

    def test_failed_job_status(self):
        job_id = self.runner.submit("false-test", ["/usr/bin/false"])
        for _ in range(40):
            time.sleep(0.1)
            j = self.runner.status(job_id)
            if j and j["status"] not in ("queued", "running"):
                break
        j = self.runner.status(job_id)
        self.assertEqual(j["status"], "failed")
        self.assertNotEqual(j["returncode"], 0)

    def test_job_output_in_log(self):
        job_id = self.runner.submit("echo-test", ["/bin/echo", "hello world"])
        for _ in range(30):
            time.sleep(0.1)
            j = self.runner.status(job_id)
            if j and j["status"] not in ("queued", "running"):
                break
        tail = self.runner.tail_log(job_id)
        self.assertIn("hello world", tail)

    def test_list_recent_returns_jobs(self):
        self.runner.submit("j1", ["/bin/true"])
        self.runner.submit("j2", ["/bin/true"])
        time.sleep(0.3)
        jobs = self.runner.list_recent(5)
        self.assertGreaterEqual(len(jobs), 2)

    def test_status_unknown_id_returns_none(self):
        result = self.runner.status("no-such-job")
        self.assertIsNone(result)

    def test_tail_log_unknown_id(self):
        result = self.runner.tail_log("no-such-job")
        self.assertIn("not found", result.lower())

    def test_cancel_non_existent_returns_false(self):
        result = self.runner.cancel("no-such-job")
        self.assertFalse(result)

    def test_state_persists_to_json(self):
        job_id = self.runner.submit("persist-test", ["/bin/true"])
        time.sleep(0.3)
        self.assertTrue(jr.JOBS_FILE.exists())
        data = json.loads(jr.JOBS_FILE.read_text())
        self.assertIn(job_id, data)


import json   # already imported at top — needed here for test_state_persists_to_json


# ═══════════════════════════════════════════════════════════════════════════════
# Existing invariants still hold
# ═══════════════════════════════════════════════════════════════════════════════

class TestExistingInvariantsStillHold(unittest.TestCase):
    """Sanity-check that the safety constraints from earlier waves are untouched."""

    FORBIDDEN_FROM_TELEGRAM = {
        "/adwi-e2e-auto-loop-start",
        "/adwi-e2e-auto-loop-cancel",
        "/adwi-backup",
        "/adwi-nightly",
        "/adwi-self-heal",
        "/auto-ai-maintenance",
    }

    def test_forbidden_routes_not_in_telegram(self):
        tg_routes = set(bridge.TELEGRAM_COMMANDS.values())
        for route in self.FORBIDDEN_FROM_TELEGRAM:
            self.assertNotIn(route, tg_routes,
                             f"Forbidden route {route!r} found in TELEGRAM_COMMANDS values")

    def test_ping_still_returns_pong(self):
        replies = _replies(_make_update(ALLOWED_UID, "/ping"))
        self.assertTrue(any("pong" in r.lower() for r in replies))

    def test_help_still_lists_status(self):
        replies = _replies(_make_update(ALLOWED_UID, "/help"))
        combined = " ".join(replies)
        self.assertIn("/status", combined)
        self.assertIn("/doctor", combined)

    def test_unknown_sender_silently_dropped(self):
        sent: list[str] = []
        with patch.object(bridge, "_send_reply", lambda t, c, msg: sent.append(msg)):
            bridge._handle_update(_make_update(999999, "/status"), TOKEN, ALLOWED_UID, SECRET)
        self.assertEqual(sent, [])

    def test_new_locally_handled_cmds_do_not_call_safe_api(self):
        locally_handled = [
            "/menu", "/test_quick", "/test_nlu", "/test_obsidian", "/test_all",
            "/tests_status", "/jobs", "/repair_plan", "/repair_ok",
            "/git_backup", "/backup_ok",
        ]
        for cmd in locally_handled:
            with self.subTest(cmd=cmd):
                routes = _api_calls(_make_update(ALLOWED_UID, cmd))
                self.assertEqual(routes, [],
                                 f"{cmd} must not dispatch to Safe API")


if __name__ == "__main__":
    unittest.main()
