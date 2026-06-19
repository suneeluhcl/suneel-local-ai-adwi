"""
commands/system.py — System status, self-heal, benchmarks, and nightly commands.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adwi.command_registry import CommandRegistry


def _cli():
    import importlib.util
    from pathlib import Path
    if "adwi_cli" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "adwi_cli",
            Path(__file__).parent.parent / "adwi_cli.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["adwi_cli"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules["adwi_cli"]


# ── Handlers ──────────────────────────────────────────────────────────────────


def _status(args: str, ctx: dict) -> None:
    _cli().run_cmd("status", ["status-ai"])


def _self_heal(args: str, ctx: dict) -> None:
    _cli().run_cmd("self-heal", ["adwi-self-heal"], timeout=1200)


def _fix_error(args: str, ctx: dict) -> None:
    _cli().cmd_fix_error(args)


def _doctor(args: str, ctx: dict) -> None:
    _cli().cmd_doctor()


def _benchmark(args: str, ctx: dict) -> None:
    _cli().cmd_benchmark()


def _what_next(args: str, ctx: dict) -> None:
    _cli().cmd_what_next()


def _daily_improve(args: str, ctx: dict) -> None:
    _cli().cmd_daily_improve()


def _nightly_status(args: str, ctx: dict) -> None:
    _cli().cmd_nightly_status()


def _nightly_run(args: str, ctx: dict) -> None:
    _cli().cmd_nightly_run()


def _capabilities(args: str, ctx: dict) -> None:
    _cli().print_capabilities()


def _patch_adwi(args: str, ctx: dict) -> None:
    _cli().cmd_patch_adwi(args)


def _help(args: str, ctx: dict) -> None:
    print(_cli().HELP)


# ── Registration ──────────────────────────────────────────────────────────────


def register(registry: "CommandRegistry") -> None:
    registry.register(
        "/help",
        description="Show all commands and usage",
        category="meta",
    )(_help)

    registry.register(
        "/status",
        description="Check all services are running",
        aliases=["/status-ai", "/health"],
        category="system",
        intents=["status"],
    )(_status)

    registry.register(
        "/self-heal",
        description="Run full self-healing maintenance cycle",
        category="system",
        intents=["self_heal"],
    )(_self_heal)

    registry.register(
        "/fix-error",
        description="Paste an error → auto-classify → patch → test",
        category="system",
        intents=["fix_error"],
        args_schema={"query": "str"},
    )(_fix_error)

    registry.register(
        "/doctor",
        description="Full diagnostic health check",
        category="system",
        intents=["doctor"],
    )(_doctor)

    registry.register(
        "/benchmark",
        description="Benchmark local model inference speed",
        category="system",
        intents=["benchmark"],
    )(_benchmark)

    registry.register(
        "/what-next",
        description="Ask Adwi what to build next",
        aliases=["/roadmap"],
        category="system",
        intents=["what_next"],
    )(_what_next)

    registry.register(
        "/daily-improve",
        description="Run daily self-improvement routine",
        category="system",
        intents=["daily_improve"],
    )(_daily_improve)

    registry.register(
        "/nightly-status",
        description="Show last nightly run outcome",
        category="system",
        intents=["nightly_status"],
    )(_nightly_status)

    registry.register(
        "/nightly-run",
        description="Trigger nightly maintenance loop now",
        category="system",
        intents=["nightly_run"],
    )(_nightly_run)

    registry.register(
        "/capabilities",
        description="List all Adwi capabilities",
        aliases=["/caps"],
        category="system",
        intents=["capabilities"],
    )(_capabilities)

    registry.register(
        "/patch-adwi",
        description="Run aider to patch Adwi source",
        category="system",
        intents=["patch_adwi"],
        args_schema={"query": "str?"},
    )(_patch_adwi)
