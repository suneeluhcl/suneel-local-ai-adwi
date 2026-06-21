"""
tests/test_remote_control_surface.py — Static regression suite for remote-control surface.

Verifies that the Safe Command API (server.py) and Telegram bridge (bot.py) route
exposure stays within the repo's safety model.  All tests are purely static —
no network calls, no subprocesses, no live services required.

Design intent:
  - Tests fail immediately if someone adds a dangerous route to either allowlist.
  - Tests fail if Telegram gains access to a mutation/execution/E2E route.
  - Tests fail if server.py gains a public-interface binding.

Run:
    python3 -m unittest adwi/tests/test_remote_control_surface.py
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

# ── Load service modules via importlib ─────────────────────────────────────────
# Using unique module names so these don't conflict with test_telegram_bridge.py.

_SVC_DIR = Path(__file__).parent.parent / "services"
_CMD_API_PATH = _SVC_DIR / "command-api" / "server.py"
_TG_BOT_PATH  = _SVC_DIR / "telegram-bridge" / "bot.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)   # type: ignore[arg-type]
    spec.loader.exec_module(mod)                   # type: ignore[union-attr]
    return mod


_server = _load_module(_CMD_API_PATH, "rcs_server")
_bridge = _load_module(_TG_BOT_PATH,  "rcs_bridge")

# These two dicts are the entire security-relevant surface.
ALLOWED_COMMANDS: dict[str, list] = _server.ALLOWED_COMMANDS
TELEGRAM_COMMANDS: dict[str, "str | None"] = _bridge.TELEGRAM_COMMANDS

# Server source text for static source tripwires.
_SERVER_SRC: str = _CMD_API_PATH.read_text()


# ── 1. Server bind-address tripwire ───────────────────────────────────────────


class TestServerBindAddress(unittest.TestCase):
    """Hard-fail if server.py source ever gains a public-interface binding."""

    def test_no_any_interface_binding(self):
        # Catches both: host = "0.0.0.0" and ThreadingHTTPServer(("0.0.0.0", ...)) forms
        self.assertNotIn(
            '"0.0.0.0"', _SERVER_SRC,
            "server.py must never bind to 0.0.0.0 — only 127.0.0.1 is permitted",
        )
        self.assertNotIn(
            "'0.0.0.0'", _SERVER_SRC,
            "server.py must never bind to 0.0.0.0 (single-quote form) — only 127.0.0.1 is permitted",
        )

    def test_loopback_binding_confirmed(self):
        self.assertIn(
            'host = "127.0.0.1"', _SERVER_SRC,
            "server.py must explicitly bind to 127.0.0.1",
        )


# ── 2. Safe Command API allowlist shape ───────────────────────────────────────


class TestCommandApiAllowlistShape(unittest.TestCase):
    """Guard the structural invariants of ALLOWED_COMMANDS."""

    def test_allowed_commands_is_dict(self):
        self.assertIsInstance(ALLOWED_COMMANDS, dict)

    def test_every_route_starts_with_slash(self):
        for route in ALLOWED_COMMANDS:
            with self.subTest(route=route):
                self.assertTrue(
                    route.startswith("/"),
                    f"ALLOWED_COMMANDS key {route!r} must start with '/'",
                )

    def test_every_command_is_a_list(self):
        # All commands must be lists (subprocess-safe explicit argv).
        # A bare string would allow shell=True style abuse.
        for route, cmd in ALLOWED_COMMANDS.items():
            with self.subTest(route=route):
                self.assertIsInstance(
                    cmd, list,
                    f"{route}: command value must be a list, not {type(cmd).__name__}",
                )

    def test_no_free_form_shell_patterns_in_commands(self):
        # No element in any command list should be a free-form shell invocation.
        danger = ("bash -c", "sh -c", "python3 -c", "python -c", "eval ", "/bin/sh -c")
        for route, cmd_list in ALLOWED_COMMANDS.items():
            joined = " ".join(str(c) for c in cmd_list)
            for pat in danger:
                with self.subTest(route=route, pattern=pat):
                    self.assertNotIn(
                        pat, joined,
                        f"{route} command list contains free-form shell pattern {pat!r}",
                    )


# ── 3. Telegram → API route consistency ───────────────────────────────────────


class TestTelegramApiConsistency(unittest.TestCase):
    """Every non-None Telegram route must exist in ALLOWED_COMMANDS."""

    def test_all_telegram_routes_exist_in_allowed_commands(self):
        for tg_cmd, api_route in TELEGRAM_COMMANDS.items():
            if api_route is None:
                continue  # locally-handled commands (e.g. /help) — no API call
            with self.subTest(tg_cmd=tg_cmd, api_route=api_route):
                self.assertIn(
                    api_route,
                    ALLOWED_COMMANDS,
                    f"Telegram {tg_cmd!r} targets {api_route!r} which is NOT in "
                    f"ALLOWED_COMMANDS — add the server.py route or fix the mapping",
                )

    def test_e2e_start_not_reachable_via_telegram(self):
        # /adwi-e2e-auto-loop-start uses a separate Popen path in server.py and
        # is intentionally absent from ALLOWED_COMMANDS. Telegram must not target it.
        tg_routes = set(TELEGRAM_COMMANDS.values())
        self.assertNotIn(
            "/adwi-e2e-auto-loop-start",
            tg_routes,
            "Telegram must not map to /adwi-e2e-auto-loop-start (launches E2E loop)",
        )


# ── 4. Mutation routes must not be accessible via Telegram ────────────────────


class TestTelegramMutationBlock(unittest.TestCase):
    """
    These routes exist in ALLOWED_COMMANDS for n8n/HA use only.
    Telegram must never map to them — they are mutation or E2E operations.
    """

    FORBIDDEN_FROM_TELEGRAM = {
        "/adwi-e2e-auto-loop-start",    # Popen path — explicit guard
        "/adwi-e2e-auto-loop-cancel",   # E2E control plane
        "/adwi-backup",                 # triggers git commit/push
        "/adwi-nightly",                # runs nightly maintenance loop
        "/adwi-self-heal",              # triggers aider patching
        "/auto-ai-maintenance",         # maintenance script
    }

    def test_mutation_routes_absent_from_telegram(self):
        tg_routes = set(TELEGRAM_COMMANDS.values())
        for route in self.FORBIDDEN_FROM_TELEGRAM:
            with self.subTest(route=route):
                self.assertNotIn(
                    route,
                    tg_routes,
                    f"Mutation route {route!r} must NOT be accessible via Telegram",
                )


# ── 5. Dangerous execution patterns absent from Telegram ──────────────────────


class TestTelegramDangerousPatterns(unittest.TestCase):
    """No Telegram command key or route value should contain dangerous patterns."""

    # Patterns that must never appear in any Telegram command key or route value.
    DANGEROUS = [
        "run-bash", "run-python",
        "patch-adwi", "self-heal", "implement",
        "git-commit", "git-push",
        "gmail-send", "gmail-confirm", "gmail-archive", "gmail-trash",
        "file-write", "obsidian-write",
        "nightly-run", "backup-now",
        "e2e-auto-loop-start",
    ]

    def test_no_dangerous_pattern_in_telegram_command_keys(self):
        for tg_cmd in TELEGRAM_COMMANDS:
            for pat in self.DANGEROUS:
                with self.subTest(tg_cmd=tg_cmd, pattern=pat):
                    self.assertNotIn(
                        pat, tg_cmd,
                        f"Telegram command key {tg_cmd!r} contains dangerous pattern {pat!r}",
                    )

    def test_no_dangerous_pattern_in_telegram_route_values(self):
        for tg_cmd, api_route in TELEGRAM_COMMANDS.items():
            if api_route is None:
                continue
            for pat in self.DANGEROUS:
                with self.subTest(tg_cmd=tg_cmd, api_route=api_route, pattern=pat):
                    self.assertNotIn(
                        pat, api_route,
                        f"Telegram {tg_cmd!r}→{api_route!r} contains dangerous pattern {pat!r}",
                    )


# ── 6. Telegram structural invariants ─────────────────────────────────────────


class TestTelegramStructure(unittest.TestCase):
    """Structural checks on the Telegram command table."""

    def test_telegram_commands_is_dict(self):
        self.assertIsInstance(TELEGRAM_COMMANDS, dict)

    def test_telegram_commands_nonempty(self):
        self.assertGreater(len(TELEGRAM_COMMANDS), 0)

    def test_help_is_locally_handled(self):
        # /help must be locally handled (None route) — lists commands without an API call.
        self.assertIn("/help", TELEGRAM_COMMANDS)
        self.assertIsNone(TELEGRAM_COMMANDS["/help"],
                          "/help must map to None (locally handled), not an API route")

    def test_all_telegram_keys_start_with_slash(self):
        for cmd in TELEGRAM_COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    cmd.startswith("/"),
                    f"Telegram command key {cmd!r} must start with '/'",
                )

    def test_all_route_values_are_string_or_none(self):
        for tg_cmd, route in TELEGRAM_COMMANDS.items():
            with self.subTest(tg_cmd=tg_cmd):
                self.assertTrue(
                    route is None or isinstance(route, str),
                    f"{tg_cmd!r}: route must be str or None, got {type(route).__name__}",
                )

    def test_non_none_routes_start_with_slash(self):
        for tg_cmd, route in TELEGRAM_COMMANDS.items():
            if route is None:
                continue
            with self.subTest(tg_cmd=tg_cmd):
                self.assertTrue(
                    route.startswith("/"),
                    f"{tg_cmd!r} route {route!r} must start with '/'",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
