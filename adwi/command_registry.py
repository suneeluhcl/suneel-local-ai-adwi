"""
command_registry.py — Plugin-based command provider for Adwi.

Architecture:
  Each module under adwi/commands/ exposes:
    register(registry: CommandRegistry) -> None
  The REPL loop calls registry.dispatch(line, ctx) before the legacy elif chain,
  enabling incremental migration without breaking existing behavior.

CommandSpec contract
  handler(args: str, ctx: dict) -> None
    args : everything after the slash-name on the input line (may be "")
    ctx  : mutable runtime dict (HOME, WORKSPACE, MODEL_*, etc.)

Thread-safety: registry is written only during startup discovery; reads are safe
from any thread after that.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# ── Value types ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CommandSpec:
    """Immutable descriptor for one registered command."""

    name: str                              # canonical slash-name e.g. "/disk"
    handler: Callable                      # fn(args: str, ctx: dict) -> None
    description: str                       # one-line help text
    aliases: tuple[str, ...] = ()          # alternate slash names
    category: str = "misc"                 # for /help grouping
    intents: tuple[str, ...] = ()          # NLU intent names → this command
    args_schema: dict = field(            # optional slot metadata
        default_factory=dict,
        compare=False,
        hash=False,
    )
    source_module: str = ""                # set by registry during discovery

    def __post_init__(self) -> None:
        if not self.name.startswith("/"):
            raise ValueError(f"Command name must start with '/': {self.name!r}")
        if not callable(self.handler):
            raise TypeError(f"Handler for {self.name!r} is not callable")
        if not self.description:
            raise ValueError(f"Command {self.name!r} must have a description")
        for alias in self.aliases:
            if not alias.startswith("/"):
                raise ValueError(f"Alias must start with '/': {alias!r}")


class CommandLoadError(Exception):
    """Raised when a command module fails to load cleanly."""


# ── Core registry ─────────────────────────────────────────────────────────────


class CommandRegistry:
    """
    Central read-after-write registry.

    Lifecycle:
      registry = CommandRegistry()
      registry.discover("adwi.commands")   # load all plugins
      # REPL loop:
      if not registry.dispatch(line, ctx):
          _legacy_handle(line, ctx)         # fallback to existing elif chain
    """

    def __init__(self) -> None:
        # Maps every name/alias → its CommandSpec
        self._commands: dict[str, CommandSpec] = {}
        # Maps NLU intent names → canonical command name
        self._intents: dict[str, str] = {}
        # Category → [canonical names] for /help
        self._categories: dict[str, list[str]] = {}
        # Load errors accumulated during discover()
        self._load_errors: list[str] = []

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        *,
        description: str,
        aliases: Optional[list[str]] = None,
        category: str = "misc",
        intents: Optional[list[str]] = None,
        args_schema: Optional[dict] = None,
        source_module: str = "",
    ) -> Callable:
        """
        Decorator factory.

            @registry.register("/disk", description="...", category="filesystem",
                               intents=["disk_usage"])
            def _cmd_disk(args: str, ctx: dict) -> None:
                ...
        """

        def decorator(fn: Callable) -> Callable:
            spec = CommandSpec(
                name=name,
                handler=fn,
                description=description,
                aliases=tuple(aliases or []),
                category=category,
                intents=tuple(intents or []),
                args_schema=args_schema or {},
                source_module=source_module or getattr(fn, "__module__", ""),
            )
            self._add(spec)
            return fn

        return decorator

    def add(self, spec: CommandSpec) -> None:
        """Register a pre-built CommandSpec (used inside register() functions)."""
        self._add(spec)

    def _add(self, spec: CommandSpec) -> None:
        if spec.name in self._commands:
            log.warning("Overwriting existing command %r", spec.name)
        self._commands[spec.name] = spec
        for alias in spec.aliases:
            self._commands[alias] = spec
        for intent in spec.intents:
            self._intents[intent] = spec.name
        cat_list = self._categories.setdefault(spec.category, [])
        if spec.name not in cat_list:
            cat_list.append(spec.name)

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover(self, package: str = "adwi.commands") -> int:
        """
        Import every submodule of `package` and call its register(registry).
        Returns the count of successfully loaded modules.
        Failures are recorded in self.load_errors and never propagate.
        """
        try:
            pkg = importlib.import_module(package)
        except ModuleNotFoundError:
            log.error("Command package %r not importable; check sys.path", package)
            return 0

        pkg_path: list[str] = getattr(pkg, "__path__", [])
        loaded = 0
        for _finder, mod_name, _is_pkg in pkgutil.iter_modules(pkg_path):
            full = f"{package}.{mod_name}"
            try:
                mod = importlib.import_module(full)
            except Exception:
                tb = traceback.format_exc()
                self._load_errors.append(f"[import] {full}: {tb}")
                log.error("Failed to import command module %s", full)
                continue
            if not hasattr(mod, "register") or not callable(mod.register):
                log.warning("Module %s has no register() function — skipping", full)
                continue
            try:
                mod.register(self)
                loaded += 1
                log.debug("Loaded command module: %s", full)
            except Exception:
                tb = traceback.format_exc()
                self._load_errors.append(f"[register] {full}: {tb}")
                log.error("register() raised in %s", full)
        return loaded

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def dispatch(self, line: str, ctx: dict) -> bool:
        """
        Dispatch a raw REPL input line to its registered handler.

        Parsing rules:
          "/disk"          → name="/disk", args=""
          "/disk /tmp 200" → name="/disk", args="/tmp 200"
          "/disk-usage"    → looked up as alias

        Returns True if a handler was found and called (even if it raised),
        False if no matching command exists (caller should fall through).
        """
        stripped = line.strip()
        if not stripped or stripped[0] != "/":
            return False

        tokens = stripped.split(None, 1)
        name   = tokens[0].lower()
        args   = tokens[1] if len(tokens) > 1 else ""

        spec = self._lookup(name)
        if spec is None:
            return False

        self._call(spec, args, ctx)
        return True

    def dispatch_intent(
        self,
        intent: str,
        args: dict,   # typed slots from Phase-6 NLU: path, query, url, etc.
        ctx: dict,
    ) -> bool:
        """
        Dispatch from an NLU-resolved intent.
        Builds a best-effort args string from typed slots for backward compat.
        Returns True if handled.
        """
        canonical = self._intents.get(intent)
        if not canonical:
            return False
        spec = self._commands.get(canonical)
        if not spec:
            return False
        # Flatten typed slots to a positional args string
        args_str = (
            args.get("path") or args.get("url") or
            args.get("query") or args.get("description") or
            args.get("target") or ""
        )
        self._call(spec, args_str, ctx)
        return True

    def _lookup(self, name: str) -> Optional[CommandSpec]:
        """Exact match first, then try stripping trailing args from longer names."""
        spec = self._commands.get(name)
        if spec:
            return spec
        # Allow prefix: "/fix-error some text" when command is "/fix-error"
        for cmd_name in self._commands:
            if name.startswith(cmd_name + "-") or name == cmd_name:
                return self._commands[cmd_name]
        return None

    @staticmethod
    def _call(spec: CommandSpec, args: str, ctx: dict) -> None:
        try:
            spec.handler(args.strip(), ctx)
        except Exception:
            log.exception("Unhandled error in command handler %r", spec.name)

    # ── Introspection ─────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[CommandSpec]:
        return self._commands.get(name)

    def all_specs(self) -> list[CommandSpec]:
        """Deduplicated list of all specs, sorted by name."""
        seen: set[str] = set()
        out: list[CommandSpec] = []
        for spec in self._commands.values():
            if spec.name not in seen:
                seen.add(spec.name)
                out.append(spec)
        return sorted(out, key=lambda s: s.name)

    def all_names(self) -> list[str]:
        return sorted(self._commands.keys())

    def help_text(self) -> str:
        """HELP string grouped by category, suitable for /help display."""
        lines: list[str] = []
        for cat, cmd_names in sorted(self._categories.items()):
            lines.append(f"\n  ── {cat.upper()} ──")
            for name in sorted(cmd_names):
                spec = self._commands.get(name)
                if spec:
                    aliases = "  " + ", ".join(spec.aliases) if spec.aliases else ""
                    lines.append(f"  {spec.name:<28}{spec.description}{aliases}")
        return "\n".join(lines)

    def intent_map(self) -> dict[str, str]:
        """Returns copy of {intent_name → canonical_command_name}."""
        return dict(self._intents)

    @property
    def load_errors(self) -> list[str]:
        return list(self._load_errors)

    def __len__(self) -> int:
        return len({s.name for s in self._commands.values()})

    def __repr__(self) -> str:
        return f"<CommandRegistry commands={len(self)} intents={len(self._intents)}>"


# ── Module-level singleton (imported by command modules and adwi_cli.py) ──────

registry = CommandRegistry()
