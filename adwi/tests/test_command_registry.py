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
        """discover() must load at least the 3 known modules."""
        fresh = CommandRegistry()
        count = fresh.discover("adwi.commands")
        self.assertGreaterEqual(count, 3, "system + knowledge + disk must all load")


if __name__ == "__main__":
    unittest.main()
