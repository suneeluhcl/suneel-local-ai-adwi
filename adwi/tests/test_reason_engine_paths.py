"""
tests/test_reason_engine_paths.py — Regression tests for reason_engine file-access gate.

Verifies that _FILE_GATE in reason_engine.py blocks all required credential/system
paths and does not block safe workspace paths.  reason_engine is loaded via importlib
with a stubbed search_orchestrator so the runtime dependency is not required.

Run:
    python3 -m unittest adwi/tests/test_reason_engine_paths.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Stub out search_orchestrator so reason_engine loads without the real dep installed.
for _stub in ("adwi.search_orchestrator", "search_orchestrator"):
    sys.modules.setdefault(_stub, MagicMock())

_RE_PATH = Path(__file__).parent.parent / "reason_engine.py"
_spec    = importlib.util.spec_from_file_location("reason_engine_paths_test", _RE_PATH)
_re_mod  = importlib.util.module_from_spec(_spec)   # type: ignore[arg-type]
_spec.loader.exec_module(_re_mod)                   # type: ignore[union-attr]

GATE      = _re_mod._FILE_GATE
HOME      = Path.home()
WORKSPACE = HOME / "SuneelWorkSpace"
ADWI_DIR  = WORKSPACE / "adwi"


class TestFileGateBlocked(unittest.TestCase):
    """Every path here must remain blocked — failing tests mean a safety regression."""

    def _assertBlocked(self, path: "Path | str") -> None:
        ok, reason = GATE.check(path)
        self.assertFalse(ok, f"Expected BLOCKED but gate allowed: {path!r}")

    def test_env_file_blocked(self):
        self._assertBlocked(ADWI_DIR / "config" / ".env")

    def test_secrets_file_blocked(self):
        self._assertBlocked(WORKSPACE / "secrets" / "api_key.txt")

    def test_secrets_dir_itself_blocked(self):
        self._assertBlocked(WORKSPACE / "secrets")

    def test_ssh_id_rsa_blocked(self):
        self._assertBlocked(HOME / ".ssh" / "id_rsa")

    def test_ssh_known_hosts_blocked(self):
        self._assertBlocked(HOME / ".ssh" / "known_hosts")

    def test_ssh_tilde_expansion_blocked(self):
        self._assertBlocked("~/.ssh/id_ed25519")

    def test_aws_credentials_blocked(self):
        self._assertBlocked(HOME / ".aws" / "credentials")

    def test_aws_config_blocked(self):
        self._assertBlocked(HOME / ".aws" / "config")

    def test_gnupg_blocked(self):
        self._assertBlocked(HOME / ".gnupg" / "secring.gpg")

    def test_kube_config_blocked(self):
        self._assertBlocked(HOME / ".kube" / "config")

    def test_keychains_blocked(self):
        self._assertBlocked(HOME / "Library" / "Keychains" / "login.keychain-db")

    def test_passwords_blocked(self):
        self._assertBlocked(HOME / "Library" / "Passwords" / "db")

    def test_etc_passwd_blocked(self):
        self._assertBlocked(Path("/etc/passwd"))

    def test_private_etc_blocked(self):
        self._assertBlocked(Path("/private/etc/hosts"))

    def test_system_library_blocked(self):
        self._assertBlocked(Path("/System/Library/foo.dylib"))

    def test_usr_lib_blocked(self):
        self._assertBlocked(Path("/usr/lib/libfoo.dylib"))


class TestFileGateAllowed(unittest.TestCase):
    """Safe workspace paths must not be blocked by the gate."""

    def _assertAllowed(self, path: "Path | str") -> None:
        ok, reason = GATE.check(path)
        self.assertTrue(ok, f"Expected ALLOWED but gate blocked: {path!r} — {reason!r}")

    def test_adwi_cli_allowed(self):
        self._assertAllowed(ADWI_DIR / "adwi_cli.py")

    def test_workspace_notes_allowed(self):
        self._assertAllowed(WORKSPACE / "notes" / "scratch.md")

    def test_adwi_config_env_example_allowed(self):
        # .env.example is the commit-safe template — must remain readable
        self._assertAllowed(ADWI_DIR / "config" / ".env.example")


if __name__ == "__main__":
    unittest.main(verbosity=2)
