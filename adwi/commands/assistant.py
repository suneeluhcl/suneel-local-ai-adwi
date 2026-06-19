"""
commands/assistant.py — Assistant Upgrade Pack + E2E loop inspection commands.

Commands in this module may call external services (web search, LLM) and write
output files to notes/ — that is their expected behavior, identical to the elif
chain they replace in handle(). No new side effects are introduced.
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


def _research(args: str, ctx: dict) -> None:
    _cli().cmd_research(args)


def _research_save(args: str, ctx: dict) -> None:
    _cli().cmd_research(args, save=True)


def _daily_brief(args: str, ctx: dict) -> None:
    _cli().cmd_daily_brief(n8n_mode=(args.strip() == "--n8n"))


def _tech_radar(args: str, ctx: dict) -> None:
    _cli().cmd_tech_radar()


def _assistant_upgrade_status(args: str, ctx: dict) -> None:
    _cli().cmd_assistant_upgrade_status()


def _e2e_status(args: str, ctx: dict) -> None:
    _cli().cmd_e2e_auto_loop_status()


def _e2e_report(args: str, ctx: dict) -> None:
    _cli().cmd_e2e_auto_loop_report()


# ── Registration ──────────────────────────────────────────────────────────────


def register(registry: "CommandRegistry") -> None:
    registry.register(
        "/research",
        description="Deep multi-source research with fetched-source citations",
        category="assistant",
        intents=["research"],
        args_schema={"question": "str?"},
    )(_research)

    registry.register(
        "/research-save",
        description="Research + save brief to Obsidian daily note",
        category="assistant",
        args_schema={"question": "str"},
    )(_research_save)

    registry.register(
        "/daily-brief",
        description="Proactive daily assistant brief (pass --n8n for JSON output)",
        category="assistant",
        intents=["daily_brief"],
        args_schema={"flag": "str?"},
    )(_daily_brief)

    registry.register(
        "/tech-radar",
        description="Scan trending AI/dev technologies (try-now / watch / ignore)",
        category="assistant",
        intents=["tech_radar"],
    )(_tech_radar)

    registry.register(
        "/assistant-upgrade-status",
        description="Show status of all Assistant Upgrade Pack commands and integrations",
        category="assistant",
        intents=["assistant_upgrade_status"],
    )(_assistant_upgrade_status)

    registry.register(
        "/e2e-auto-loop-status",
        description="Show current/last E2E auto-loop job status and master NLU score",
        category="eval",
    )(_e2e_status)

    registry.register(
        "/e2e-auto-loop-report",
        description="Show the latest E2E auto-loop cycle or final report",
        category="eval",
    )(_e2e_report)
