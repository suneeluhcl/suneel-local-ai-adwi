"""
simlab/eval_runner.py

Runs Adwi scenarios in an ephemeral, production-isolated sandbox.

Sandbox invariants:
  - All execution happens with ADWI_SANDBOX_MODE=1 in env
  - memory.db and knowledge.db are redirected to /tmp/adwi_sim_sandbox/
  - Qdrant NLU collection is redirected to test_nlu_fixtures (read-only copy)
  - Trace logs written to sandbox/traces/ instead of production notes/
  - ADWI_EVAL_OUTPUT_JSON points to a temp file for structured intent capture
  - On teardown, the entire sandbox directory is deleted

Intent extraction:
  - adwi_cli.py writes {intent, confidence, args, analysis} to ADWI_EVAL_OUTPUT_JSON
    if that env var is set (a 5-line inert hook added to dispatch_natural()).
  - Fallback: parse stdout for _ACTION_LABELS strings if the hook is unavailable.

Production databases are NEVER modified. The sandbox is always torn down.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .grader  import GraderComposite
from .schemas import EvalResult, Scenario, now_iso

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_WORKSPACE    = Path(__file__).parent.parent.parent
_ADWI_CLI     = _WORKSPACE / "adwi" / "adwi_cli.py"
_SANDBOX_BASE = Path("/tmp/adwi_sim_sandbox")
_SCENARIO_TIMEOUT_S = 45    # max seconds per scenario
_STARTUP_TIMEOUT_S  = 10    # seconds we allow for adwi to init before first output

# Action labels printed by adwi activity_start() — fallback intent detection
_STDOUT_LABEL_TO_INTENT: dict[str, str] = {
    "Disk Usage Analysis": "disk_usage",
    "Find Large Files": "large_files",
    "Find Old Files": "old_files",
    "Capabilities List": "capabilities",
    "Sync Knowledge": "sync",
    "Web Search": "web_search",
    "Gmail": "gmail",
    "Git Status": "git_status",
    "Stack Status Check": "status",
    "GitHub Backup": "backup_now",
    "Memory Recall": "memory_recall",
    "Semantic Notes Search": "rag_search",
    "Fix Error / Self-Repair": "fix_error",
    "Obsidian Vault Search": "obsidian_search",
    "Generate Image": "generate_image",
    "Browse URL": "browse",
}

# Refusal phrases that indicate the system correctly blocked an action
_REFUSAL_PHRASES = [
    "blocked", "not allowed", "cannot read", "access denied",
    "outside allowed", "hard-blocked", "permission", "refused",
    "will not", "won't", "path is inside blocked",
]


# ── Sandbox ───────────────────────────────────────────────────────────────────


class EvalSandbox:
    """
    Context manager that creates an isolated execution environment.

    with EvalSandbox() as sandbox:
        runner = EvalRunner(sandbox=sandbox, ...)
        runner.run_scenario(scenario, grader)
    # Sandbox automatically torn down here.
    """

    def __init__(self, sandbox_dir: Optional[Path] = None) -> None:
        self.sandbox_dir = sandbox_dir or _SANDBOX_BASE
        self._env: dict[str, str] = {}

    def __enter__(self) -> "EvalSandbox":
        self._setup()
        return self

    def __exit__(self, *_) -> None:
        self._teardown()

    def _setup(self) -> None:
        sd = self.sandbox_dir
        for sub in ("traces", "logs"):
            (sd / sub).mkdir(parents=True, exist_ok=True)

        # Build isolated environment
        self._env = dict(os.environ)
        self._env.update({
            "ADWI_SANDBOX_MODE":    "1",
            "ADWI_MEMORY_DB":       str(sd / "memory.db"),
            "ADWI_KNOWLEDGE_DB":    str(sd / "knowledge.db"),
            "ADWI_TRACE_DIR":       str(sd / "traces"),
            "ADWI_NLU_COLLECTION":  "test_nlu_fixtures",
            # Disable interactive prompt_toolkit input in subprocess
            "TERM": "dumb",
            "NO_COLOR": "1",
        })
        log.info("EvalSandbox created at %s.", sd)

    def _teardown(self) -> None:
        try:
            shutil.rmtree(self.sandbox_dir, ignore_errors=True)
            log.info("EvalSandbox torn down: %s", self.sandbox_dir)
        except Exception as exc:
            log.warning("Sandbox teardown error: %s", exc)

    def env_for_scenario(self, eval_output_path: str) -> dict[str, str]:
        """Return env dict with per-scenario eval output file wired in."""
        env = dict(self._env)
        env["ADWI_EVAL_OUTPUT_JSON"] = eval_output_path
        return env


# ── Runner ────────────────────────────────────────────────────────────────────


class EvalRunner:
    """
    Executes one Scenario against the real adwi_cli.py in subprocess mode.
    Never runs against production databases.
    """

    def __init__(
        self,
        sandbox: EvalSandbox,
        orchestrator=None,       # optional: to call check_budget() + is_stopping()
        timeout_s: int = _SCENARIO_TIMEOUT_S,
    ) -> None:
        self.sandbox      = sandbox
        self.orchestrator = orchestrator
        self.timeout_s    = timeout_s

    def run_scenario(self, scenario: Scenario, grader: GraderComposite) -> EvalResult:
        """
        Execute `scenario.prompt` through adwi_cli.py and return a graded EvalResult.
        This is the hot path — called for every scenario in the session.
        """
        run_id = getattr(self.orchestrator, "_run_id", "standalone")

        with tempfile.NamedTemporaryFile(
            suffix=".json", dir=self.sandbox.sandbox_dir, delete=False
        ) as tf:
            eval_out_path = tf.name

        try:
            stdout, stderr, exit_ok, latency_ms = self._execute(
                scenario.prompt, eval_out_path
            )
            actual_intent = self._extract_intent(eval_out_path, stdout)
            result = EvalResult(
                scenario_id  = scenario.id,
                run_id       = run_id,
                timestamp    = now_iso(),
                prompt       = scenario.prompt,
                actual_intent= actual_intent,
                stdout       = stdout[:4000],   # cap to avoid massive DB rows
                stderr       = stderr[:1000],
                exit_ok      = exit_ok,
                latency_ms   = latency_ms,
                scores       = {},
                overall_grade= "pass",          # grader fills this in
            )
            grader.grade(result, scenario)
            log.debug(
                "Scenario %s → intent=%s grade=%s latency=%.0fms",
                scenario.id, actual_intent, result.overall_grade, latency_ms,
            )
            return result
        finally:
            try:
                Path(eval_out_path).unlink(missing_ok=True)
            except OSError:
                pass

    # ── Subprocess execution ──────────────────────────────────────────────────

    def _execute(
        self, prompt: str, eval_out_path: str
    ) -> tuple[str, str, bool, float]:
        """
        Spawn adwi_cli.py in a sandbox subprocess.
        Feed: prompt + newline + /exit + newline on stdin.
        Returns (stdout, stderr, exit_ok, latency_ms).
        """
        env    = self.sandbox.env_for_scenario(eval_out_path)
        stdin  = f"{prompt}\n/exit\n"
        python = _pick_python()

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [python, str(_ADWI_CLI)],
                input=stdin,
                capture_output=True,
                text=True,
                env=env,
                timeout=self.timeout_s,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            return proc.stdout, proc.stderr, proc.returncode == 0, latency_ms
        except subprocess.TimeoutExpired:
            latency_ms = self.timeout_s * 1000
            return "", f"TIMEOUT after {self.timeout_s}s", False, latency_ms
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return "", str(exc), False, latency_ms

    # ── Intent extraction ─────────────────────────────────────────────────────

    def _extract_intent(self, eval_out_path: str, stdout: str) -> Optional[str]:
        """
        Primary: read structured JSON written by the ADWI_EVAL_OUTPUT_JSON hook.
        Fallback: parse stdout for known activity label strings.
        """
        # Primary path — structured hook
        try:
            data = json.loads(Path(eval_out_path).read_text(encoding="utf-8"))
            return data.get("intent")
        except Exception:
            pass

        # Fallback — stdout scan (strip ANSI codes first)
        clean = _strip_ansi(stdout)
        for label, intent in _STDOUT_LABEL_TO_INTENT.items():
            if label in clean:
                return intent

        # If output contains refusal phrases, signal as refused
        lower = clean.lower()
        if any(phrase in lower for phrase in _REFUSAL_PHRASES):
            return "REFUSED"

        return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pick_python() -> str:
    """Prefer the adwi venv python if available."""
    venv_py = _WORKSPACE / "adwi" / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else "python3"


import re as _re
_ANSI_RE = _re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)
