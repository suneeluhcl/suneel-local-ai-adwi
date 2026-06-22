#!/usr/bin/env python3
"""
validate_claude_headroom.py — Read-only validator for the Headroom + Claude integration.

Checks the local environment to confirm Headroom is installed, Claude is present,
and (if the proxy has been started via `headroom wrap claude`) that routing is active.
Stdlib-only. Never prints secrets or token values.

Checks:
  1. Python >= 3.10
  2. headroom command exists
  3. headroom --help works
  4. claude command exists
  5. headroom proxy reachable at :8787
     (WARN if not — expected unless inside a `headroom wrap claude` session)
  6. Claude project settings route through Headroom proxy
     (WARN if not — expected unless inside a `headroom wrap claude` session)
  7. headroom --version returns a version string
  8. No secret patterns in headroom --help output

Exits 0 only if all PASS checks pass. WARN lines are informational and do not
cause failure — checks 5 and 6 are only active during a wrap session.

Install note: headroom-ai[proxy] is installed. ML Kompress-base (for text/prose
compression) requires `headroom-ai[ml]` (adds torch/onnxruntime) and is NOT
currently installed. SmartCrusher (JSON) and CodeCompressor (AST) are available.

Usage:
  python3 adwi/scripts/validate_claude_headroom.py
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
_PROXY_URL   = "http://127.0.0.1:8787"

_pass_count = 0
_fail_count = 0
_warn_count = 0


def _check(label: str, cond: bool, detail: str = "") -> bool:
    global _pass_count, _fail_count
    status = "PASS" if cond else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {status}  {label}{suffix}")
    if cond:
        _pass_count += 1
    else:
        _fail_count += 1
    return cond


def _warn(label: str, detail: str = "") -> None:
    global _warn_count
    suffix = f"  ({detail})" if detail else ""
    print(f"  WARN  {label}{suffix}")
    _warn_count += 1


def main() -> int:
    print("validate_claude_headroom.py — Headroom + Claude integration validator")
    print()

    # 1. Python version
    vi = sys.version_info
    _check(
        "Python >= 3.10",
        (vi.major, vi.minor) >= (3, 10),
        detail=f"{vi.major}.{vi.minor}.{vi.micro}",
    )

    # 2. headroom command exists
    installed = HEADROOM_BIN is not None
    _check(
        "headroom command exists",
        installed,
        detail=f"found: {HEADROOM_BIN}" if installed else "not found — run: pipx install headroom-ai[proxy]",
    )

    # 3. headroom --help works
    help_output = ""
    if installed:
        try:
            r = subprocess.run(
                [HEADROOM_BIN, "--help"],
                capture_output=True, text=True, timeout=10,
            )
            help_output = r.stdout + r.stderr
            ok = r.returncode == 0 or "headroom" in help_output.lower()
            _check("headroom --help works", ok, detail=f"exit {r.returncode}" if not ok else "")
        except Exception as exc:
            _check("headroom --help works", False, detail=str(exc)[:80])
    else:
        _check("headroom --help works", False, detail="skipped — headroom not installed")

    # 4. claude command exists
    _check(
        "claude command exists",
        CLAUDE_BIN is not None,
        detail=f"found: {CLAUDE_BIN}" if CLAUDE_BIN else "not found",
    )

    # 5. Headroom proxy reachable at :8787
    proxy_ok = False
    try:
        urllib.request.urlopen(f"{_PROXY_URL}/health", timeout=2)
        proxy_ok = True
    except Exception:
        pass
    if proxy_ok:
        _check("Headroom proxy reachable at :8787", True, detail="proxy is running")
    else:
        _warn(
            "Headroom proxy reachable at :8787",
            detail="expected WARN unless inside `headroom wrap claude` session",
        )

    # 6. Claude project settings route through Headroom
    # Check project-local settings (written by `headroom wrap claude`)
    project_settings = WORKSPACE / ".claude" / "settings.local.json"
    routed = False
    if project_settings.exists():
        try:
            payload = json.loads(project_settings.read_text(encoding="utf-8"))
            env_map = payload.get("env") or {}
            base_url = env_map.get("ANTHROPIC_BASE_URL", "")
            routed = "8787" in base_url or "headroom" in base_url.lower()
        except Exception:
            pass
    if routed:
        _check("Project settings route Claude through Headroom proxy", True,
               detail="ANTHROPIC_BASE_URL set in .claude/settings.local.json")
    else:
        _warn(
            "Project settings route Claude through Headroom proxy",
            detail="expected WARN unless inside `headroom wrap claude` session",
        )

    # 7. headroom --version returns a version string
    if installed:
        try:
            r = subprocess.run(
                [HEADROOM_BIN, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            ver_output = (r.stdout + r.stderr).strip()
            ok = bool(ver_output) and r.returncode == 0
            _check(
                "headroom --version returns version",
                ok,
                detail=ver_output.splitlines()[0][:60] if ver_output else "no output",
            )
        except Exception as exc:
            _check("headroom --version returns version", False, detail=str(exc)[:80])
    else:
        _check("headroom --version returns version", False, detail="skipped — not installed")

    # 8. headroom --help output does not expose secrets
    if help_output:
        secret_patterns = [
            "TELEGRAM_BOT_TOKEN", "ADWI_LOCAL_SECRET",
            "sk-ant-", "sk-proj-", "Bearer ",
            "eyJ",  # JWT prefix
        ]
        found = [p for p in secret_patterns if p in help_output]
        _check(
            "headroom --help output contains no secret patterns",
            not found,
            detail=f"found patterns: {found}" if found else "",
        )
    else:
        _check(
            "headroom --help output contains no secret patterns",
            False,
            detail="skipped — no output to check",
        )

    # Extra info: installed extra
    print()
    print("  INFO  Package: headroom-ai[proxy] — SmartCrusher (JSON) + CodeCompressor (AST) available")
    print("  INFO  ML Kompress-base (prose/text): NOT installed (needs headroom-ai[ml] + torch)")

    # Summary
    total = _pass_count + _fail_count
    print(f"\n{_pass_count}/{total} checks passed"
          + (f", {_warn_count} warning(s)" if _warn_count else ""))
    if _warn_count:
        print("NOTE: WARN lines are expected — checks 5/6 only pass inside `headroom wrap claude`")
    if _fail_count == 0:
        print("PASS")
        return 0
    if not installed:
        print("Install with: pipx install --python /opt/homebrew/bin/python3.12 'headroom-ai[proxy]'")
    print("FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
