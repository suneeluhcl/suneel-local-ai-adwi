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


if __name__ == "__main__":
    unittest.main()
