#!/usr/bin/env python3
"""
smoke_claude_headroom.py — Smoke check for the Headroom + Claude installation.

Fast, read-only, stdlib-only. Never launches an interactive Claude session.
Never prints secrets.

Exits 0 when the installation is structurally valid, even if the proxy is not
currently running (proxy is only up during `headroom wrap claude` sessions).

PASS = hard requirement met (install, binary, version output)
WARN = expected absent state (proxy not running, not yet routed) — not a failure
FAIL = broken install or unexpected error

Usage:
  python3 adwi/scripts/smoke_claude_headroom.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request

HEADROOM_BIN = shutil.which("headroom")
CLAUDE_BIN   = shutil.which("claude")
_PROXY_URL   = "http://127.0.0.1:8787"

_pass_count = 0
_fail_count = 0
_warn_count = 0


def _check(label: str, cond: bool, detail: str = "") -> bool:
    global _pass_count, _fail_count
    tag    = "PASS" if cond else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {tag}  {label}{suffix}")
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
    print("smoke_claude_headroom.py — Headroom + Claude smoke check")
    print()

    # 1. headroom command exists
    installed = HEADROOM_BIN is not None
    _check(
        "headroom installed",
        installed,
        detail=f"found: {HEADROOM_BIN}" if installed
               else "not found — install: pipx install --python /opt/homebrew/bin/python3.12 'headroom-ai[proxy]'",
    )

    # 2. claude command exists
    _check(
        "claude installed",
        CLAUDE_BIN is not None,
        detail=f"found: {CLAUDE_BIN}" if CLAUDE_BIN else "not found",
    )

    # 3. headroom --version returns output
    if installed:
        try:
            r = subprocess.run(
                [HEADROOM_BIN, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            ver = (r.stdout + r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else ""
            _check(
                "headroom --version",
                r.returncode == 0 and bool(ver),
                detail=ver[:60] if ver else "no output",
            )
        except Exception as exc:
            _check("headroom --version", False, detail=str(exc)[:80])
    else:
        _check("headroom --version", False, detail="skipped — not installed")

    # 4. headroom wrap --help (non-interactive, exits immediately)
    if installed:
        try:
            r = subprocess.run(
                [HEADROOM_BIN, "wrap", "--help"],
                capture_output=True, text=True, timeout=10,
            )
            out = r.stdout + r.stderr
            ok  = r.returncode == 0 and "claude" in out.lower()
            _check(
                "headroom wrap --help lists claude",
                ok,
                detail="wrap help OK" if ok else f"exit {r.returncode}",
            )
        except Exception as exc:
            _check("headroom wrap --help lists claude", False, detail=str(exc)[:80])
    else:
        _check("headroom wrap --help lists claude", False, detail="skipped — not installed")

    # 5. Proxy reachable at :8787
    # WARN only — proxy is only running during `headroom wrap claude` sessions.
    proxy_ok = False
    try:
        urllib.request.urlopen(f"{_PROXY_URL}/health", timeout=2)
        proxy_ok = True
    except Exception:
        pass
    if proxy_ok:
        _check("Headroom proxy :8787 reachable", True, detail="proxy is running")
    else:
        _warn(
            "Headroom proxy :8787 not running",
            detail="expected outside `headroom wrap claude` session — WARN, not FAIL",
        )

    # 6. headroom doctor — interpret non-wrapped state as expected
    if installed:
        try:
            r = subprocess.run(
                [HEADROOM_BIN, "doctor"],
                capture_output=True, text=True, timeout=20,
            )
            out      = r.stdout + r.stderr
            failures = out.count("✗ fail")
            warnings = out.count("⚠ warn")
            skips    = out.count("· skip")

            # Proxy-not-running is the only expected "failure" outside wrap session.
            # If proxy IS running, all should pass.
            if failures == 0:
                _check("headroom doctor",
                       True, detail=f"{warnings} warn(s), {skips} skip(s) — install OK")
            elif failures == 1 and not proxy_ok and "not reachable" in out:
                # The one expected failure is proxy not running. Treat as WARN.
                _warn(
                    "headroom doctor: proxy not running",
                    detail="1 failure (proxy), rest expected — install is valid",
                )
            else:
                # Unexpected failures beyond proxy
                _check(
                    "headroom doctor",
                    False,
                    detail=f"{failures} failure(s), {warnings} warning(s)",
                )
        except Exception as exc:
            _check("headroom doctor", False, detail=str(exc)[:80])
    else:
        _check("headroom doctor", False, detail="skipped — not installed")

    # Summary
    total = _pass_count + _fail_count
    print()
    print(f"{_pass_count}/{total} checks passed"
          + (f", {_warn_count} warning(s)" if _warn_count else ""))
    if _warn_count and not proxy_ok:
        print("NOTE: WARN lines are expected — proxy only runs inside `headroom wrap claude`")
    if _fail_count == 0:
        print("PASS  — Headroom installation is valid")
        return 0
    print("FAIL  — fix the issues above before using Headroom")
    return 1


if __name__ == "__main__":
    sys.exit(main())
