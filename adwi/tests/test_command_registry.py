"""
tests/test_command_registry.py — Unit tests for CommandRegistry.

Run:
    python3 -m pytest adwi/tests/test_command_registry.py -v
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add workspace root so `adwi` package imports work when run directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from adwi.command_registry import CommandRegistry, CommandSpec


# ── Helpers ───────────────────────────────────────────────────────────────────


def _noop(args: str, ctx: dict) -> None:  # noqa: ANN001
    pass


def _make_spec(**kwargs) -> CommandSpec:
    defaults = dict(
        name="/test",
        handler=_noop,
        description="test command",
        aliases=(),
        category="misc",
        intents=(),
        args_schema={},
        source_module="test",
    )
    defaults.update(kwargs)
    return CommandSpec(**defaults)


# ── CommandSpec validation ────────────────────────────────────────────────────


class TestCommandSpec(unittest.TestCase):
    def test_valid_spec_accepted(self):
        spec = _make_spec()
        self.assertEqual(spec.name, "/test")

    def test_name_must_start_with_slash(self):
        with self.assertRaises(ValueError):
            _make_spec(name="no-slash")

    def test_description_required(self):
        with self.assertRaises(ValueError):
            _make_spec(description="")

    def test_handler_must_be_callable(self):
        with self.assertRaises(TypeError):
            _make_spec(handler="not-callable")

    def test_alias_must_start_with_slash(self):
        with self.assertRaises(ValueError):
            _make_spec(aliases=("bad-alias",))


# ── Registration ──────────────────────────────────────────────────────────────


class TestRegistration(unittest.TestCase):
    def setUp(self):
        self.reg = CommandRegistry()

    def test_register_decorator(self):
        @self.reg.register("/demo", description="demo", intents=["demo_intent"])
        def _h(args, ctx):
            pass

        self.assertIsNotNone(self.reg.get("/demo"))
        self.assertEqual(self.reg.get("/demo").handler, _h)

    def test_alias_resolves_to_same_spec(self):
        @self.reg.register("/primary", description="primary", aliases=["/alias1"])
        def _h(args, ctx):
            pass

        self.assertIs(self.reg.get("/primary"), self.reg.get("/alias1"))

    def test_intent_map_populated(self):
        @self.reg.register("/foo", description="foo", intents=["foo_intent"])
        def _h(args, ctx):
            pass

        self.assertIn("foo_intent", self.reg.intent_map())
        self.assertEqual(self.reg.intent_map()["foo_intent"], "/foo")

    def test_overwrite_logs_warning(self):
        @self.reg.register("/dup", description="first")
        def _h1(args, ctx):
            pass

        import logging
        with self.assertLogs("adwi.command_registry", level="WARNING"):
            @self.reg.register("/dup", description="second")
            def _h2(args, ctx):
                pass

    def test_add_spec(self):
        spec = _make_spec(name="/added", description="added directly")
        self.reg.add(spec)
        self.assertEqual(self.reg.get("/added").description, "added directly")

    def test_len(self):
        for i in range(5):
            spec = _make_spec(name=f"/cmd{i}", description=f"cmd {i}")
            self.reg.add(spec)
        self.assertEqual(len(self.reg), 5)


# ── Dispatch ──────────────────────────────────────────────────────────────────


class TestDispatch(unittest.TestCase):
    def setUp(self):
        self.reg = CommandRegistry()
        self.calls: list[tuple[str, dict]] = []

        @self.reg.register("/echo", description="echo args")
        def _echo(args: str, ctx: dict) -> None:
            self.calls.append((args, ctx))

    def test_dispatch_returns_true_on_match(self):
        result = self.reg.dispatch("/echo hello world", {})
        self.assertTrue(result)

    def test_dispatch_passes_args(self):
        self.reg.dispatch("/echo hello world", {"key": "val"})
        self.assertEqual(self.calls[-1][0], "hello world")

    def test_dispatch_empty_args(self):
        self.reg.dispatch("/echo", {})
        self.assertEqual(self.calls[-1][0], "")

    def test_dispatch_returns_false_for_unknown(self):
        result = self.reg.dispatch("/unknown-command", {})
        self.assertFalse(result)

    def test_dispatch_returns_false_for_non_slash(self):
        result = self.reg.dispatch("just text", {})
        self.assertFalse(result)

    def test_alias_dispatch(self):
        @self.reg.register("/parent", description="parent", aliases=["/alt"])
        def _h(args, ctx):
            self.calls.append((args, ctx))

        self.reg.dispatch("/alt some-args", {})
        self.assertEqual(self.calls[-1][0], "some-args")

    def test_handler_exception_does_not_propagate(self):
        @self.reg.register("/boom", description="raises")
        def _h(args, ctx):
            raise RuntimeError("intentional")

        # Should not raise — exception is caught and logged
        result = self.reg.dispatch("/boom", {})
        self.assertTrue(result)


# ── Intent dispatch ───────────────────────────────────────────────────────────


class TestIntentDispatch(unittest.TestCase):
    def setUp(self):
        self.reg = CommandRegistry()
        self.received: list[tuple[str, dict]] = []

        @self.reg.register(
            "/web-search",
            description="search",
            intents=["web_search"],
        )
        def _h(args: str, ctx: dict) -> None:
            self.received.append((args, ctx))

    def test_dispatch_intent_matched(self):
        result = self.reg.dispatch_intent(
            "web_search", {"query": "langchain docs"}, {}
        )
        self.assertTrue(result)
        self.assertEqual(self.received[-1][0], "langchain docs")

    def test_dispatch_intent_unknown_returns_false(self):
        result = self.reg.dispatch_intent("no_such_intent", {}, {})
        self.assertFalse(result)

    def test_dispatch_intent_uses_path_over_query(self):
        @self.reg.register("/read", description="read", intents=["file_read"])
        def _h(args, ctx):
            self.received.append((args, ctx))

        self.reg.dispatch_intent(
            "file_read", {"path": "/tmp/file.txt", "query": "ignored"}, {}
        )
        self.assertEqual(self.received[-1][0], "/tmp/file.txt")


# ── Discovery ─────────────────────────────────────────────────────────────────


class TestDiscovery(unittest.TestCase):
    def test_discover_missing_package(self):
        reg = CommandRegistry()
        count = reg.discover("no_such_package_xyz")
        self.assertEqual(count, 0)

    def test_discover_loads_real_modules(self):
        """Smoke-test: discover adwi.commands and verify no crash."""
        reg = CommandRegistry()
        # Only run if the package is importable (in the real repo)
        try:
            import adwi.commands  # noqa: F401
        except ImportError:
            self.skipTest("adwi package not on sys.path")
        count = reg.discover("adwi.commands")
        self.assertGreater(count, 0)
        self.assertGreater(len(reg), 0)

    def test_discover_skips_module_without_register(self):
        """A module that has no register() function is skipped without error."""
        fake_pkg = types.ModuleType("fake_commands")
        fake_pkg.__path__ = []  # type: ignore[attr-defined]
        fake_pkg.__name__ = "fake_commands"

        sub = types.ModuleType("fake_commands.no_reg")
        # No register() function — discovery should warn but not fail

        with patch.dict(sys.modules, {
            "fake_commands": fake_pkg,
            "fake_commands.no_reg": sub,
        }):
            with patch("pkgutil.iter_modules", return_value=[
                (None, "no_reg", False),
            ]):
                reg = CommandRegistry()
                count = reg.discover("fake_commands")
                self.assertEqual(count, 0)


# ── Help text ─────────────────────────────────────────────────────────────────


class TestHelpText(unittest.TestCase):
    def test_help_text_groups_by_category(self):
        reg = CommandRegistry()
        for name, cat in [("/a", "alpha"), ("/b", "alpha"), ("/c", "beta")]:
            reg.add(_make_spec(name=name, description=f"cmd {name}", category=cat))
        txt = reg.help_text()
        self.assertIn("ALPHA", txt)
        self.assertIn("BETA", txt)
        self.assertIn("/a", txt)
        self.assertIn("/c", txt)


# ── Phase 1 wiring verification ───────────────────────────────────────────────


class TestPhase1WiringCommands(unittest.TestCase):
    """
    Verify the 3 Phase 1 pilot commands are registered via discover() and that
    dispatch() returns the right boolean for each case.

    These are the first commands wired through registry-first dispatch in handle().
    The elif chain remains as fallback for unregistered commands.
    """

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_help_registered(self):
        self.assertIsNotNone(self.reg.get("/help"), "/help must be in the registry")

    def test_status_registered(self):
        self.assertIsNotNone(self.reg.get("/status"), "/status must be in the registry")

    def test_memory_stats_registered(self):
        self.assertIsNotNone(self.reg.get("/memory-stats"), "/memory-stats must be in the registry")

    def test_dispatch_true_for_phase1_commands(self):
        """dispatch() returns True when spec found (handler may log/fail — that is OK)."""
        for cmd in ["/help", "/status", "/memory-stats"]:
            with self.subTest(cmd=cmd):
                result = self.reg.dispatch(cmd, {})
                self.assertTrue(result, f"dispatch('{cmd}') must return True")

    def test_dispatch_false_for_unregistered_is_fallback_signal(self):
        """Unregistered commands must return False so the elif chain fires."""
        result = self.reg.dispatch("/not-a-real-command-xyz", {})
        self.assertFalse(result)

    def test_dispatch_false_for_natural_language(self):
        """Non-slash input must return False (NLU path handles it, not registry)."""
        result = self.reg.dispatch("check my setup", {})
        self.assertFalse(result)

    def test_phase1_commands_have_descriptions(self):
        for cmd in ["/help", "/status", "/memory-stats"]:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_discover_count_covers_all_plugin_modules(self):
        """discover() must load at least the 4 known modules (including eval)."""
        fresh = CommandRegistry()
        count = fresh.discover("adwi.commands")
        self.assertGreaterEqual(count, 4, "system + knowledge + disk + eval must all load")


# ── Phase 2 wiring verification ───────────────────────────────────────────────


class TestPhase2EvalCommands(unittest.TestCase):
    """
    Verify Phase 2 eval/backup/routing commands are registered via discover()
    and that dispatch() returns True for each.

    These are read-only inspection commands migrated to registry-first dispatch.
    The elif chain remains as fallback.
    """

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_eval_routing_registered(self):
        self.assertIsNotNone(self.reg.get("/eval-routing"))

    def test_test_adwi_registered(self):
        self.assertIsNotNone(self.reg.get("/test-adwi"))

    def test_backup_status_registered(self):
        self.assertIsNotNone(self.reg.get("/backup-status"))

    def test_backup_log_registered(self):
        self.assertIsNotNone(self.reg.get("/backup-log"))

    def test_backup_audit_registered(self):
        self.assertIsNotNone(self.reg.get("/backup-audit"))

    def test_route_registered(self):
        self.assertIsNotNone(self.reg.get("/route"))

    def test_watcher_status_registered(self):
        self.assertIsNotNone(self.reg.get("/watcher-status"))

    def test_phase2_commands_have_descriptions(self):
        phase2 = [
            "/eval-routing", "/test-adwi", "/backup-status",
            "/backup-log", "/backup-audit", "/route", "/watcher-status",
        ]
        for cmd in phase2:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_phase2_commands_dispatch_true(self):
        """dispatch() returns True (found + called) for all Phase 2 commands."""
        phase2 = [
            "/eval-routing", "/test-adwi", "/backup-status",
            "/backup-log", "/backup-audit", "/route", "/watcher-status",
        ]
        for cmd in phase2:
            with self.subTest(cmd=cmd):
                result = self.reg.dispatch(cmd, {})
                self.assertTrue(result, f"dispatch('{cmd}') must return True")

    def test_eval_routing_intent_wired(self):
        self.assertIn("eval_routing", self.reg.intent_map())

    def test_test_adwi_intent_wired(self):
        self.assertIn("test_adwi", self.reg.intent_map())

    def test_backup_status_intent_wired(self):
        self.assertIn("backup_status", self.reg.intent_map())

    def test_eval_module_loaded_via_discover(self):
        """discover() must find all 4 modules including the new eval module."""
        fresh = CommandRegistry()
        count = fresh.discover("adwi.commands")
        self.assertGreaterEqual(count, 4, "eval module must be auto-discovered")
        self.assertIsNotNone(fresh.get("/eval-routing"), "eval module commands must register")


# ── Phase 3 wiring verification ───────────────────────────────────────────────


class TestPhase3DiagnosticsCommands(unittest.TestCase):
    """
    Verify Phase 3 system-diagnostics commands are registered via discover()
    and that dispatch() returns True for each.

    All Phase 3 commands are read-only inspection commands.
    /eval-adwi and /capability-audit are intentionally excluded (they auto-write
    to capabilities.json via update_capabilities_json()).
    """

    PHASE3 = [
        "/models",
        "/mcp",
        "/inspect-system",
        "/trusted-roots",
        "/tool-roadmap",
        "/trace-log",
        "/training-plan",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase3_commands_registered(self):
        for cmd in self.PHASE3:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase3_commands_dispatch_true(self):
        for cmd in self.PHASE3:
            with self.subTest(cmd=cmd):
                result = self.reg.dispatch(cmd, {})
                self.assertTrue(result, f"dispatch('{cmd}') must return True")

    def test_all_phase3_commands_have_descriptions(self):
        for cmd in self.PHASE3:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_trusted_roots_intent_wired(self):
        self.assertIn("trusted_roots", self.reg.intent_map())
        self.assertEqual(self.reg.intent_map()["trusted_roots"], "/trusted-roots")

    def test_tool_roadmap_intent_wired(self):
        self.assertIn("tool_roadmap", self.reg.intent_map())
        self.assertEqual(self.reg.intent_map()["tool_roadmap"], "/tool-roadmap")

    def test_trace_log_passes_numeric_args(self):
        """dispatch('/trace-log 2', {}) must reach the handler (returns True)."""
        result = self.reg.dispatch("/trace-log 2", {})
        self.assertTrue(result)

    def test_diagnostics_module_loaded_via_discover(self):
        fresh = CommandRegistry()
        count = fresh.discover("adwi.commands")
        self.assertGreaterEqual(count, 5, "5 modules: system + knowledge + disk + eval + diagnostics")
        self.assertIsNotNone(fresh.get("/models"), "diagnostics module must register /models")

    def test_total_unique_commands_grows(self):
        """Registry must now cover at least 61 unique command names."""
        self.assertGreaterEqual(len(set(self.reg.all_names())), 61)

    def test_mutating_commands_not_in_phase3(self):
        """eval-adwi and capability-audit were intentionally excluded (they write capabilities.json)."""
        # They may be registered by a future phase — this test just confirms Phase 3 didn't add them
        # (they are absent from the diagnostics module)
        import adwi.commands.diagnostics as diag_mod
        import inspect
        source = inspect.getsource(diag_mod)
        self.assertNotIn("cmd_eval_adwi", source)
        self.assertNotIn("cmd_capability_audit", source)


# ── Phase 4 wiring verification ───────────────────────────────────────────────


class TestPhase4AssistantCommands(unittest.TestCase):
    """
    Verify Phase 4 assistant/reporting commands are registered via discover()
    and dispatch correctly.

    /daily-brief --n8n arg-passing and /research-save inclusion are explicitly
    tested here since they required special handler logic.
    """

    PHASE4 = [
        "/research",
        "/research-save",
        "/daily-brief",
        "/tech-radar",
        "/assistant-upgrade-status",
        "/e2e-auto-loop-status",
        "/e2e-auto-loop-report",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase4_commands_registered(self):
        for cmd in self.PHASE4:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase4_commands_dispatch_true(self):
        for cmd in self.PHASE4:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase4_commands_have_descriptions(self):
        for cmd in self.PHASE4:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_research_intent_wired(self):
        self.assertIn("research", self.reg.intent_map())
        self.assertEqual(self.reg.intent_map()["research"], "/research")

    def test_daily_brief_intent_wired(self):
        self.assertIn("daily_brief", self.reg.intent_map())
        self.assertEqual(self.reg.intent_map()["daily_brief"], "/daily-brief")

    def test_tech_radar_intent_wired(self):
        self.assertIn("tech_radar", self.reg.intent_map())
        self.assertEqual(self.reg.intent_map()["tech_radar"], "/tech-radar")

    def test_assistant_upgrade_status_intent_wired(self):
        self.assertIn("assistant_upgrade_status", self.reg.intent_map())

    def test_daily_brief_n8n_dispatches_to_same_handler(self):
        """'/daily-brief --n8n' must be caught by /daily-brief registry entry (args='--n8n')."""
        result = self.reg.dispatch("/daily-brief --n8n", {})
        self.assertTrue(result, "registry must intercept /daily-brief --n8n before the elif chain")

    def test_research_with_question_dispatches(self):
        """'/research some question' must dispatch to /research (args='some question')."""
        result = self.reg.dispatch("/research what is MCP", {})
        self.assertTrue(result)

    def test_research_save_registered_separately(self):
        """'/research-save' is a distinct command from '/research'."""
        spec_r = self.reg.get("/research")
        spec_rs = self.reg.get("/research-save")
        self.assertIsNotNone(spec_rs)
        self.assertIsNot(spec_r, spec_rs)

    def test_e2e_status_and_report_in_eval_category(self):
        for cmd in ["/e2e-auto-loop-status", "/e2e-auto-loop-report"]:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertEqual(spec.category, "eval")

    def test_assistant_module_loaded_via_discover(self):
        fresh = CommandRegistry()
        count = fresh.discover("adwi.commands")
        self.assertGreaterEqual(count, 6, "6 modules including assistant")
        self.assertIsNotNone(fresh.get("/research"), "assistant module must register /research")

    def test_total_unique_commands_at_phase4(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 68)


# ── Phase 5 wiring verification ───────────────────────────────────────────────


class TestPhase5GmailReadOnlyCommands(unittest.TestCase):
    """
    Verify Phase 5A Gmail listing/display commands are registered via discover()
    and dispatch correctly.

    Phase 5A = read-only Gmail commands only (no send/compose/archive/trash/mark).
    Mutating Gmail commands are deferred to Phase 6.

    Note on _GMAIL_CTX writes: list_drafts and list_attachments write in-memory
    cache entries (_GMAIL_CTX["draft_list"] / ["attachments"]) — that is their
    expected behavior, identical to the elif chain. They do NOT mutate Gmail state.
    """

    PHASE5A = [
        "/gmail-show-draft",
        "/gmail-followups",
        "/gmail-scheduled",
        "/gmail-drafts",
        "/gmail-rules",
        "/gmail-promos",
        "/gmail-spam",
        "/gmail-social",
        "/gmail-attachments",
    ]

    # Commands still deferred after Phase 7 (Phase 8+)
    PHASE8_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase5a_commands_registered(self):
        for cmd in self.PHASE5A:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase5a_commands_dispatch_true(self):
        for cmd in self.PHASE5A:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase5a_commands_have_descriptions(self):
        for cmd in self.PHASE5A:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_all_phase5a_commands_in_gmail_category(self):
        for cmd in self.PHASE5A:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertEqual(spec.category, "gmail")

    def test_gmail_intents_wired(self):
        expected = {
            "gmail_show_draft": "/gmail-show-draft",
            "gmail_list_followups": "/gmail-followups",
            "gmail_list_scheduled": "/gmail-scheduled",
            "gmail_list_drafts": "/gmail-drafts",
            "gmail_filter_list": "/gmail-rules",
            "gmail_list_category": "/gmail-promos",
            "gmail_list_attachments": "/gmail-attachments",
        }
        for intent, cmd in expected.items():
            with self.subTest(intent=intent):
                self.assertIn(intent, self.reg.intent_map())
                self.assertEqual(self.reg.intent_map()[intent], cmd)

    def test_drafts_passes_args(self):
        """/gmail-drafts <filter> must reach handler (dispatch returns True)."""
        result = self.reg.dispatch("/gmail-drafts invoice", {})
        self.assertTrue(result)

    def test_attachments_passes_args(self):
        result = self.reg.dispatch("/gmail-attachments thread", {})
        self.assertTrue(result)

    def test_rules_passes_args(self):
        result = self.reg.dispatch("/gmail-rules finance", {})
        self.assertTrue(result)

    def test_phase8_deferred_commands_not_in_registry(self):
        """Schedule/followup commands must NOT be in the registry (deferred to Phase 8+)."""
        for cmd in self.PHASE8_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 8",
                )

    def test_phase8_deferred_commands_still_return_false(self):
        for cmd in self.PHASE8_DEFERRED:
            with self.subTest(cmd=cmd):
                result = self.reg.dispatch(cmd, {})
                self.assertFalse(result, f"{cmd} must fall through to elif chain")

    def test_gmail_module_loaded_via_discover(self):
        fresh = CommandRegistry()
        count = fresh.discover("adwi.commands")
        self.assertGreaterEqual(count, 7, "7 modules including gmail")
        self.assertIsNotNone(fresh.get("/gmail-show-draft"))

    def test_total_unique_commands_at_phase5(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 77)


# ── Phase 6 wiring verification ───────────────────────────────────────────────


class TestPhase6GmailMutatingCommands(unittest.TestCase):
    """
    Verify Phase 6 Gmail mutating commands are registered via discover() and
    dispatch correctly.

    Phase 6A: archive/trash/mark-read/mark-unread preview commands + confirm
    (with /confirm alias) + cancel + undo. These are preview-first mutations —
    archive/trash/mark only stage to _GMAIL_CTX["pending"]; no live Gmail API
    call until /gmail-confirm is issued.

    Phase 6B: filter rule build/apply/cancel. Rule preview → apply flow uses
    _GMAIL_CTX["pending_rule"], parallel to the Cluster A pending pattern.

    Deferred to Phase 8+: schedule, followup, extract-tasks, triage, attachment
    mutations, draft-reply, rewrite, add-cc/bcc, open-draft, delete-draft.
    """

    PHASE6A = [
        "/gmail-archive",
        "/gmail-trash",
        "/gmail-mark-read",
        "/gmail-mark-unread",
        "/gmail-confirm",
        "/gmail-cancel",
        "/gmail-undo",
    ]

    PHASE6B = [
        "/gmail-rule",
        "/gmail-rule-apply",
        "/gmail-rule-cancel",
    ]

    # Commands still deferred after Phase 7 (Phase 8+)
    PHASE8_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase6a_commands_registered(self):
        for cmd in self.PHASE6A:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase6b_commands_registered(self):
        for cmd in self.PHASE6B:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase6_commands_dispatch_true(self):
        for cmd in self.PHASE6A + self.PHASE6B:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase6_commands_have_descriptions(self):
        for cmd in self.PHASE6A + self.PHASE6B:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_all_phase6_commands_in_gmail_category(self):
        for cmd in self.PHASE6A + self.PHASE6B:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reg.get(cmd).category, "gmail")

    def test_gmail_mutating_intents_wired(self):
        expected = {
            "gmail_archive": "/gmail-archive",
            "gmail_trash": "/gmail-trash",
            "gmail_mark_read": "/gmail-mark-read",
            "gmail_mark_unread": "/gmail-mark-unread",
            "gmail_confirm": "/gmail-confirm",
            "gmail_cancel": "/gmail-cancel",
            "gmail_undo": "/gmail-undo",
            "gmail_filter_build": "/gmail-rule",
            "gmail_filter_apply": "/gmail-rule-apply",
            "gmail_filter_cancel": "/gmail-rule-cancel",
        }
        for intent, cmd in expected.items():
            with self.subTest(intent=intent):
                self.assertIn(intent, self.reg.intent_map())
                self.assertEqual(self.reg.intent_map()[intent], cmd)

    def test_confirm_alias_resolves_to_gmail_confirm_spec(self):
        """/confirm alias must resolve to the same spec object as /gmail-confirm."""
        spec_primary = self.reg.get("/gmail-confirm")
        spec_alias = self.reg.get("/confirm")
        self.assertIsNotNone(spec_alias, "/confirm alias must be registered")
        self.assertIs(spec_primary, spec_alias, "/confirm must resolve to /gmail-confirm spec")

    def test_confirm_alias_dispatches(self):
        """/confirm must be intercepted by the registry before the elif chain."""
        result = self.reg.dispatch("/confirm", {})
        self.assertTrue(result)

    def test_archive_passes_args(self):
        result = self.reg.dispatch("/gmail-archive newsletter", {})
        self.assertTrue(result)

    def test_trash_passes_args(self):
        result = self.reg.dispatch("/gmail-trash promo", {})
        self.assertTrue(result)

    def test_mark_read_passes_args(self):
        result = self.reg.dispatch("/gmail-mark-read inbox", {})
        self.assertTrue(result)

    def test_mark_unread_passes_args(self):
        result = self.reg.dispatch("/gmail-mark-unread starred", {})
        self.assertTrue(result)

    def test_rule_passes_args(self):
        result = self.reg.dispatch("/gmail-rule archive newsletters from noreply", {})
        self.assertTrue(result)

    def test_phase8_deferred_commands_not_in_registry(self):
        """Schedule/followup commands must NOT be in the registry (deferred to Phase 8+)."""
        for cmd in self.PHASE8_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 8",
                )

    def test_phase8_deferred_commands_still_return_false(self):
        for cmd in self.PHASE8_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.reg.dispatch(cmd, {}),
                    f"{cmd} must fall through to elif chain",
                )

    def test_total_unique_commands_at_phase6(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 88)


# ── Phase 7 wiring verification ───────────────────────────────────────────────


class TestPhase7GmailDraftLifecycleCommands(unittest.TestCase):
    """
    Verify Phase 7 Gmail draft lifecycle commands are registered via discover()
    and dispatch correctly.

    Cluster: compose, send-draft, cancel-draft, forward.
    - compose and forward accept NL text args (contact resolution, recipient regex)
    - send-draft and cancel-draft take no args; inline input() confirmations live
      inside the function bodies and are fully preserved by _cli() delegation
    - forward requires _GMAIL_CTX["current_email"]; returns early if unset
    - send-draft requires _GMAIL_CTX["draft"]; returns early if unset

    Deferred to Phase 8+: draft-reply, rewrite, update-subject, add-cc/bcc,
    open-draft, delete-draft, schedule-send, cancel-scheduled, reschedule,
    followup-reminder, extract-tasks, triage, attachment mutations.
    """

    PHASE7 = [
        "/gmail-compose",
        "/gmail-send-draft",
        "/gmail-cancel-draft",
        "/gmail-forward",
    ]

    PHASE8_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase7_commands_registered(self):
        for cmd in self.PHASE7:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase7_commands_dispatch_true(self):
        for cmd in self.PHASE7:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase7_commands_have_descriptions(self):
        for cmd in self.PHASE7:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_all_phase7_commands_in_gmail_category(self):
        for cmd in self.PHASE7:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reg.get(cmd).category, "gmail")

    def test_draft_lifecycle_intents_wired(self):
        expected = {
            "gmail_compose": "/gmail-compose",
            "gmail_send_draft": "/gmail-send-draft",
            "gmail_cancel_draft": "/gmail-cancel-draft",
            "gmail_forward": "/gmail-forward",
        }
        for intent, cmd in expected.items():
            with self.subTest(intent=intent):
                self.assertIn(intent, self.reg.intent_map())
                self.assertEqual(self.reg.intent_map()[intent], cmd)

    def test_compose_passes_nl_args(self):
        """/gmail-compose with NL text dispatches correctly (args forwarded to handler)."""
        result = self.reg.dispatch("/gmail-compose email Rahul saying hello", {})
        self.assertTrue(result)

    def test_forward_passes_nl_args(self):
        """/gmail-forward with recipient text dispatches correctly."""
        result = self.reg.dispatch("/gmail-forward to Rahul", {})
        self.assertTrue(result)

    def test_send_draft_no_args_dispatches(self):
        """/gmail-send-draft takes no args; dispatch returns True, handler reads _GMAIL_CTX."""
        result = self.reg.dispatch("/gmail-send-draft", {})
        self.assertTrue(result)

    def test_cancel_draft_no_args_dispatches(self):
        result = self.reg.dispatch("/gmail-cancel-draft", {})
        self.assertTrue(result)

    def test_phase8_deferred_not_in_registry(self):
        """Schedule/followup commands remain in elif chain (deferred to Phase 8+)."""
        for cmd in self.PHASE8_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 8",
                )

    def test_phase8_deferred_still_return_false(self):
        for cmd in self.PHASE8_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.reg.dispatch(cmd, {}),
                    f"{cmd} must fall through to elif chain",
                )

    def test_total_unique_commands_at_phase7(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 92)


# ── Phase 8 wiring verification ───────────────────────────────────────────────


class TestPhase8GmailDraftEditingCommands(unittest.TestCase):
    """
    Verify Phase 8 Gmail draft-editing commands are registered via discover()
    and dispatch correctly.

    Cluster: rewrite, update-subject, add-cc, add-bcc.
    All 4 operate on _GMAIL_CTX["draft"] in-place via gh.update_draft():
    - rewrite: calls _llm_generate() then gh.update_draft(); writes draft["body"]
    - update-subject: calls _llm_generate() + input() confirm; writes draft["subject"]
    - add-cc: contact resolution + gh.update_draft(); writes draft["cc"]
    - add-bcc: contact resolution + gh.update_draft(); writes draft["bcc"]

    No live send, no draft creation, no draft deletion in this cluster.
    All safety gates (early-return on missing draft, input() fallbacks, y/n confirm)
    are inside the function bodies and fully preserved by _cli() delegation.

    Deferred to Phase 9+: draft-reply, open-draft, delete-draft, schedule-send,
    cancel-scheduled, reschedule, followup-reminder, extract-tasks, triage,
    attachment mutations.
    """

    PHASE8 = [
        "/gmail-rewrite",
        "/gmail-update-subject",
        "/gmail-add-cc",
        "/gmail-add-bcc",
    ]

    PHASE12_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase8_commands_registered(self):
        for cmd in self.PHASE8:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase8_commands_dispatch_true(self):
        for cmd in self.PHASE8:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase8_commands_have_descriptions(self):
        for cmd in self.PHASE8:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_all_phase8_commands_in_gmail_category(self):
        for cmd in self.PHASE8:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reg.get(cmd).category, "gmail")

    def test_draft_editing_intents_wired(self):
        expected = {
            "gmail_rewrite_draft": "/gmail-rewrite",
            "gmail_update_subject": "/gmail-update-subject",
            "gmail_add_cc": "/gmail-add-cc",
            "gmail_add_bcc": "/gmail-add-bcc",
        }
        for intent, cmd in expected.items():
            with self.subTest(intent=intent):
                self.assertIn(intent, self.reg.intent_map())
                self.assertEqual(self.reg.intent_map()[intent], cmd)

    def test_rewrite_passes_nl_args(self):
        """/gmail-rewrite with instruction dispatches correctly."""
        result = self.reg.dispatch("/gmail-rewrite make it shorter", {})
        self.assertTrue(result)

    def test_update_subject_passes_nl_args(self):
        result = self.reg.dispatch("/gmail-update-subject make it clearer", {})
        self.assertTrue(result)

    def test_add_cc_passes_contact_args(self):
        result = self.reg.dispatch("/gmail-add-cc Rahul", {})
        self.assertTrue(result)

    def test_add_bcc_passes_contact_args(self):
        result = self.reg.dispatch("/gmail-add-bcc me", {})
        self.assertTrue(result)

    def test_rewrite_no_args_dispatches(self):
        """/gmail-rewrite with no args dispatches (handler prompts via input())."""
        result = self.reg.dispatch("/gmail-rewrite", {})
        self.assertTrue(result)

    def test_phase12_deferred_not_in_registry(self):
        """Followup/triage commands remain in elif chain (deferred to Phase 12+)."""
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 12",
                )

    def test_phase12_deferred_still_return_false(self):
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.reg.dispatch(cmd, {}),
                    f"{cmd} must fall through to elif chain",
                )

    def test_total_unique_commands_at_phase8(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 96)


# ── Phase 9 wiring verification ───────────────────────────────────────────────


class TestPhase9GmailDraftManagementCommands(unittest.TestCase):
    """
    Verify Phase 9 Gmail draft-management commands are registered via discover()
    and dispatch correctly.

    Cluster: open-draft, delete-draft.
    - open-draft: uses _resolve_draft_ref(text) for ordinal/name disambiguation;
      auto-populates _GMAIL_CTX["draft_list"] if empty; sets _GMAIL_CTX["draft"].
      No input() calls — returns disambiguation message if ambiguous. Internally
      calls cmd_gmail_send_draft() when text contains "send".
    - delete-draft: uses _resolve_draft_ref(text) or falls back to current draft;
      shows preview + "Permanently delete? y/n" input() before gh.delete_draft().
      Clears _GMAIL_CTX["draft_list"] entry and _GMAIL_CTX["draft"] if current.

    All draft-list population, disambiguation, and API calls are inside function
    bodies — fully preserved by _cli() delegation.

    Deferred to Phase 10+: draft-reply, schedule-send, cancel-scheduled,
    reschedule, followup-reminder, extract-tasks, triage, attachment mutations.
    """

    PHASE9 = [
        "/gmail-open-draft",
        "/gmail-delete-draft",
    ]

    PHASE12_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase9_commands_registered(self):
        for cmd in self.PHASE9:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase9_commands_dispatch_true(self):
        for cmd in self.PHASE9:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase9_commands_have_descriptions(self):
        for cmd in self.PHASE9:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_all_phase9_commands_in_gmail_category(self):
        for cmd in self.PHASE9:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reg.get(cmd).category, "gmail")

    def test_draft_management_intents_wired(self):
        expected = {
            "gmail_open_draft": "/gmail-open-draft",
            "gmail_delete_draft": "/gmail-delete-draft",
        }
        for intent, cmd in expected.items():
            with self.subTest(intent=intent):
                self.assertIn(intent, self.reg.intent_map())
                self.assertEqual(self.reg.intent_map()[intent], cmd)

    def test_open_draft_passes_ref_args(self):
        """/gmail-open-draft with ordinal ref dispatches correctly."""
        result = self.reg.dispatch("/gmail-open-draft 2", {})
        self.assertTrue(result)

    def test_open_draft_no_args_dispatches(self):
        """/gmail-open-draft with no args dispatches (handler handles empty ref)."""
        result = self.reg.dispatch("/gmail-open-draft", {})
        self.assertTrue(result)

    def test_delete_draft_passes_ref_args(self):
        result = self.reg.dispatch("/gmail-delete-draft 1", {})
        self.assertTrue(result)

    def test_delete_draft_no_args_dispatches(self):
        """/gmail-delete-draft with no args dispatches (handler falls back to current draft)."""
        result = self.reg.dispatch("/gmail-delete-draft", {})
        self.assertTrue(result)

    def test_phase12_deferred_not_in_registry(self):
        """Followup/triage commands remain in elif chain (deferred to Phase 12+)."""
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 12",
                )

    def test_phase12_deferred_still_return_false(self):
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.reg.dispatch(cmd, {}),
                    f"{cmd} must fall through to elif chain",
                )

    def test_total_unique_commands_at_phase9(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 98)


# ── Phase 10 wiring verification ──────────────────────────────────────────────


class TestPhase10GmailDraftReply(unittest.TestCase):
    """
    Verify Phase 10 /gmail-draft-reply is registered via discover() and
    dispatches correctly.

    /gmail-draft-reply: requires _GMAIL_CTX["current_email"]; optionally uses
    current_thread for context-aware "reply to the latest ask" mode. LLM
    generates the reply body, calls gh.create_draft_reply(), shows preview.
    No live send. Returns early with a hint if current_email is None or if no
    instruction given on the standard path.

    The function strips "draft a reply saying…" prefixes internally — the
    registry args path (raw text after the slash command) is handled identically
    to the elif chain: cmd_gmail_draft_reply(line[19:].strip()).

    Deferred to Phase 12+: followup-reminder, extract-tasks, triage, attachment
    mutations. Schedule cluster migrated in Phase 11.
    """

    PHASE12_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_draft_reply_registered(self):
        self.assertIsNotNone(self.reg.get("/gmail-draft-reply"))

    def test_draft_reply_dispatches_true(self):
        result = self.reg.dispatch("/gmail-draft-reply", {})
        self.assertTrue(result)

    def test_draft_reply_has_description(self):
        spec = self.reg.get("/gmail-draft-reply")
        self.assertIsNotNone(spec)
        self.assertGreater(len(spec.description), 0)

    def test_draft_reply_in_gmail_category(self):
        self.assertEqual(self.reg.get("/gmail-draft-reply").category, "gmail")

    def test_draft_reply_intent_wired(self):
        self.assertIn("gmail_draft_reply", self.reg.intent_map())
        self.assertEqual(self.reg.intent_map()["gmail_draft_reply"], "/gmail-draft-reply")

    def test_draft_reply_passes_instruction_args(self):
        """'/gmail-draft-reply I can do Friday' must dispatch correctly."""
        result = self.reg.dispatch("/gmail-draft-reply I can do Friday", {})
        self.assertTrue(result)

    def test_draft_reply_passes_context_mode_args(self):
        """'/gmail-draft-reply reply to the latest ask' must dispatch correctly."""
        result = self.reg.dispatch("/gmail-draft-reply reply to the latest ask", {})
        self.assertTrue(result)

    def test_phase12_deferred_not_in_registry(self):
        """Followup/triage commands remain in elif chain (deferred to Phase 12+)."""
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 12",
                )

    def test_phase12_deferred_still_return_false(self):
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.reg.dispatch(cmd, {}),
                    f"{cmd} must fall through to elif chain",
                )

    def test_total_unique_commands_at_phase10(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 99)


# ── Phase 11 wiring verification ──────────────────────────────────────────────


class TestPhase11GmailScheduleCluster(unittest.TestCase):
    """
    Verify Phase 11 schedule cluster is registered via discover() and dispatches
    correctly.

    Commands migrated in this phase:
      /gmail-schedule        — schedule current draft for future send (preview+confirm, local queue)
      /gmail-cancel-scheduled — cancel a pending scheduled send (confirm required)
      /gmail-reschedule      — move a pending scheduled send to a new time (preview+confirm)
      /gmail-open-scheduled  — load draft from a pending scheduled send into session ctx

    No live send on schedule/reschedule/cancel paths. open-scheduled makes a
    read-only gh.get_draft() call. All input() confirmations are preserved inside
    adwi_cli.py handlers — the registry delegation is identical to the elif chain.

    Deferred to Phase 12+: followup-reminder, extract-tasks, triage, attachment
    mutations.
    """

    PHASE11 = [
        "/gmail-schedule",
        "/gmail-cancel-scheduled",
        "/gmail-reschedule",
        "/gmail-open-scheduled",
    ]

    PHASE12_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase11_commands_registered(self):
        for cmd in self.PHASE11:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase11_commands_dispatch_true(self):
        for cmd in self.PHASE11:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase11_commands_have_descriptions(self):
        for cmd in self.PHASE11:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_all_phase11_commands_in_gmail_category(self):
        for cmd in self.PHASE11:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reg.get(cmd).category, "gmail")

    def test_schedule_cluster_intents_wired(self):
        expected = {
            "gmail_schedule_send": "/gmail-schedule",
            "gmail_cancel_scheduled": "/gmail-cancel-scheduled",
            "gmail_reschedule_send": "/gmail-reschedule",
            "gmail_open_scheduled": "/gmail-open-scheduled",
        }
        for intent, cmd in expected.items():
            with self.subTest(intent=intent):
                self.assertIn(intent, self.reg.intent_map())
                self.assertEqual(self.reg.intent_map()[intent], cmd)

    def test_schedule_passes_time_args(self):
        """/gmail-schedule with time text dispatches correctly."""
        result = self.reg.dispatch("/gmail-schedule tomorrow at 9am", {})
        self.assertTrue(result)

    def test_schedule_no_args_dispatches(self):
        """/gmail-schedule with no args dispatches (handler shows time-parse error)."""
        result = self.reg.dispatch("/gmail-schedule", {})
        self.assertTrue(result)

    def test_cancel_scheduled_passes_ref_args(self):
        result = self.reg.dispatch("/gmail-cancel-scheduled 1", {})
        self.assertTrue(result)

    def test_cancel_scheduled_no_args_dispatches(self):
        result = self.reg.dispatch("/gmail-cancel-scheduled", {})
        self.assertTrue(result)

    def test_reschedule_passes_time_args(self):
        result = self.reg.dispatch("/gmail-reschedule to Friday at 9am", {})
        self.assertTrue(result)

    def test_reschedule_no_args_dispatches(self):
        result = self.reg.dispatch("/gmail-reschedule", {})
        self.assertTrue(result)

    def test_open_scheduled_passes_ref_args(self):
        result = self.reg.dispatch("/gmail-open-scheduled 2", {})
        self.assertTrue(result)

    def test_open_scheduled_no_args_dispatches(self):
        result = self.reg.dispatch("/gmail-open-scheduled", {})
        self.assertTrue(result)

    def test_phase12_deferred_not_in_registry(self):
        """Followup/triage commands remain in elif chain (deferred to Phase 12+)."""
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 12",
                )

    def test_phase12_deferred_still_return_false(self):
        for cmd in self.PHASE12_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.reg.dispatch(cmd, {}),
                    f"{cmd} must fall through to elif chain",
                )

    def test_total_unique_commands_at_phase11(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 103)


# ── Phase 12 wiring verification ──────────────────────────────────────────────


class TestPhase12GmailFollowupCluster(unittest.TestCase):
    """
    Verify Phase 12 follow-up reminder cluster is registered via discover()
    and dispatches correctly.

    Commands migrated in this phase:
      /gmail-followup        — set a follow-up reminder on last-sent or current thread
                               (shows preview + confirm, writes local reminder store,
                               no live send, no auto-send)
      /gmail-cancel-followup — cancel an active reminder by ordinal or most recent
                               (confirm required, marks status=cancelled in store)

    Note: /gmail-followups (list) was already registered in Phase 5A. No duplicate.

    Both commands operate on the local follow-up reminder store
    (_load/_save_followup_reminders) only. input() confirmations are preserved
    inside adwi_cli.py handlers — delegation is identical to the elif chain.

    Deferred to Phase 13+: extract-tasks, triage, attachment mutations.
    """

    PHASE12 = [
        "/gmail-followup",
        "/gmail-cancel-followup",
    ]

    PHASE13_DEFERRED = [
        "/gmail-extract-tasks",
        "/gmail-triage",
    ]

    @classmethod
    def setUpClass(cls):
        cls.reg = CommandRegistry()
        cls.reg.discover("adwi.commands")

    def test_all_phase12_commands_registered(self):
        for cmd in self.PHASE12:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.reg.get(cmd), f"{cmd} must be registered")

    def test_all_phase12_commands_dispatch_true(self):
        for cmd in self.PHASE12:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    self.reg.dispatch(cmd, {}),
                    f"dispatch('{cmd}') must return True",
                )

    def test_all_phase12_commands_have_descriptions(self):
        for cmd in self.PHASE12:
            with self.subTest(cmd=cmd):
                spec = self.reg.get(cmd)
                self.assertIsNotNone(spec)
                self.assertGreater(len(spec.description), 0)

    def test_all_phase12_commands_in_gmail_category(self):
        for cmd in self.PHASE12:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reg.get(cmd).category, "gmail")

    def test_followup_cluster_intents_wired(self):
        expected = {
            "gmail_followup_reminder": "/gmail-followup",
            "gmail_cancel_followup":   "/gmail-cancel-followup",
        }
        for intent, cmd in expected.items():
            with self.subTest(intent=intent):
                self.assertIn(intent, self.reg.intent_map())
                self.assertEqual(self.reg.intent_map()[intent], cmd)

    def test_followup_passes_time_args(self):
        """/gmail-followup with time text dispatches correctly."""
        result = self.reg.dispatch("/gmail-followup in 3 days", {})
        self.assertTrue(result)

    def test_followup_no_args_dispatches(self):
        """/gmail-followup with no args dispatches (handler defaults to 3-day reminder)."""
        result = self.reg.dispatch("/gmail-followup", {})
        self.assertTrue(result)

    def test_cancel_followup_passes_ref_args(self):
        result = self.reg.dispatch("/gmail-cancel-followup 1", {})
        self.assertTrue(result)

    def test_cancel_followup_no_args_dispatches(self):
        result = self.reg.dispatch("/gmail-cancel-followup", {})
        self.assertTrue(result)

    def test_followups_list_still_registered_from_phase5(self):
        """/gmail-followups was registered in Phase 5A and must remain registered."""
        self.assertIsNotNone(self.reg.get("/gmail-followups"))

    def test_followups_list_dispatches(self):
        result = self.reg.dispatch("/gmail-followups", {})
        self.assertTrue(result)

    def test_phase13_deferred_not_in_registry(self):
        """Extract-tasks and triage remain in elif chain (deferred to Phase 13+)."""
        for cmd in self.PHASE13_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(
                    self.reg.get(cmd),
                    f"{cmd} must remain deferred until Phase 13",
                )

    def test_phase13_deferred_still_return_false(self):
        for cmd in self.PHASE13_DEFERRED:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.reg.dispatch(cmd, {}),
                    f"{cmd} must fall through to elif chain",
                )

    def test_total_unique_commands_at_phase12(self):
        self.assertGreaterEqual(len(set(self.reg.all_names())), 105)


if __name__ == "__main__":
    unittest.main()
