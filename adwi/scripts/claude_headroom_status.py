#!/usr/bin/env python3
"""
claude_headroom_status.py — Compact Headroom + Claude integration status.

Stdlib-only, read-only, no network calls except a fast port-check on :8787.
Never prints secrets or token values.

Usage:
  python3 adwi/scripts/claude_headroom_status.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

WORKSPACE    = Path(__file__).resolve().parent.parent.parent
HEADROOM_BIN = shutil.which("headroom")
CLAUDE_BIN   = shutil.which("claude")
_PROXY_PORT  = 8787


def _headroom_version() -> str:
    if not HEADROOM_BIN:
        return "not installed"
    try:
        r = subprocess.run(
            [HEADROOM_BIN, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        line = (r.stdout + r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else ""
        return line[:60] or "installed (no version)"
    except Exception:
        return "installed (version check failed)"


def _proxy_reachable() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{_PROXY_PORT}/health", timeout=2)
        return True
    except Exception:
        return False


def _claude_wrapped() -> str:
    """Return 'yes', 'no', or 'unknown'."""
    project_settings = WORKSPACE / ".claude" / "settings.local.json"
    if not project_settings.exists():
        return "unknown (settings.local.json not found)"
    try:
        payload = json.loads(project_settings.read_text(encoding="utf-8"))
        env_map = payload.get("env") or {}
        base_url = env_map.get("ANTHROPIC_BASE_URL", "")
        if "8787" in base_url or "headroom" in base_url.lower():
            return f"yes (ANTHROPIC_BASE_URL→proxy)"
        return "no (not routed)"
    except Exception:
        return "unknown (parse error)"


def _doctor_status() -> str:
    """Run headroom doctor and return a one-line summary."""
    if not HEADROOM_BIN:
        return "SKIP (not installed)"
    try:
        r = subprocess.run(
            [HEADROOM_BIN, "doctor"],
            capture_output=True, text=True, timeout=15,
        )
        out = (r.stdout + r.stderr)
        if "0 failure" in out and "0 warning" in out:
            return "OK"
        failures = out.count("✗ fail")
        warnings = out.count("⚠ warn")
        proxy_reachable = _proxy_reachable()
        if failures == 0:
            return f"WARN ({warnings} warning(s))"
        if failures == 1 and not proxy_reachable and "not reachable" in out:
            return f"WARN (proxy not running — expected outside wrap session)"
        return f"FAIL ({failures} failure(s), {warnings} warning(s))"
    except Exception as exc:
        return f"ERROR: {exc}"


def main() -> int:
    headroom_ver = _headroom_version()
    installed    = HEADROOM_BIN is not None
    claude_ok    = CLAUDE_BIN is not None
    proxy_ok     = _proxy_reachable()
    wrapped      = _claude_wrapped()
    doctor       = _doctor_status()

    lines = [
        "Claude + Headroom Status",
        f"  Claude installed:    {'yes — ' + str(CLAUDE_BIN) if claude_ok else 'NO — claude not found'}",
        f"  Headroom installed:  {'yes — ' + headroom_ver if installed else 'NO'}",
        f"  Claude wrapped:      {wrapped}",
        f"  Proxy reachable:     {'yes (:' + str(_PROXY_PORT) + ')' if proxy_ok else 'no (not running)'}",
        f"  Doctor:              {doctor}",
        "",
        "NOTE: Headroom active only inside `headroom wrap claude` sessions.",
        "      Outside a wrap session, Claude uses the direct Anthropic API.",
        "      `headroom perf` shows no data until after the first wrapped session.",
        "",
    ]

    if not installed:
        lines += [
            "Next: install Headroom",
            "  pipx install --python /opt/homebrew/bin/python3.12 'headroom-ai[proxy]'",
        ]
    elif not proxy_ok:
        lines += [
            "Next: start Claude through Headroom",
            "  headroom wrap claude          # or: adwi/bin/claude-headroom",
            "  (starts proxy on :8787 + routes Claude through it)",
        ]
    elif "yes" not in wrapped:
        lines += [
            "Next: proxy is running but Claude session not wrapped",
            "  restart Claude with: headroom wrap claude",
        ]
    else:
        lines += [
            "Status: Headroom active for this Claude session.",
            "  Run `headroom perf` to see token savings.",
        ]

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
