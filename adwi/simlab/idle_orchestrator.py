"""
simlab/idle_orchestrator.py

Controls WHEN SimLab sessions run, enforcing all hardware and concurrency gates.

Hardware gates (enforced before ANY thread is spawned):
  1. Battery power  → BLOCKED. pmset must show AC power.
  2. Thermal load   → BLOCKED if 1-min load_avg / cpu_count > THERMAL_THRESHOLD.
  3. Lock file      → BLOCKED if another SimLab session is running (concurrent safety).

Execution budget:
  - Wall-clock deadline enforced across the whole session.
  - Individual scenario timeouts enforced by EvalRunner.
  - check_budget() is called between every scenario; raises BudgetExceeded.

Modes:
  - canary  : 20% random sample of scenario corpus (~5-10 min)
  - full    : entire scenario corpus (~30-60 min)
  - nightly : same as full, triggered by nightly.py at 2 AM

Signal handling:
  - SIGINT / SIGTERM cause graceful shutdown at next scenario boundary.
  - Lock is always released in finally block.

Usage:
    orch = IdleOrchestrator(mode="canary", budget_minutes=15)
    run_id = orch.run()   # returns None if gated/skipped
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_WORKSPACE        = Path(__file__).parent.parent.parent
_LOCK_FILE        = _WORKSPACE / "logs" / "simlab.lock"
_THERMAL_THRESHOLD = 0.75   # load_avg/cpu_count; above this = too busy
_POLL_INTERVAL_S  = 15      # seconds between idle-check retries
_DEFAULT_BUDGET   = 30      # minutes
_CANARY_FRACTION  = 0.20    # 20% of corpus in canary mode


# ── Sentinel exceptions ───────────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """Raised by check_budget() when wall-clock deadline is past."""


class HardwareGateError(Exception):
    """Raised when battery or thermal check prevents execution."""


# ── Platform checks ───────────────────────────────────────────────────────────


def is_on_battery() -> bool:
    """
    Returns True if the host is on battery power.
    Uses `pmset -g ps` (macOS). Fails open (returns False) if pmset unavailable.
    """
    try:
        out = subprocess.check_output(
            ["pmset", "-g", "ps"], text=True, timeout=5, stderr=subprocess.DEVNULL
        )
        return "Battery Power" in out
    except Exception as exc:
        log.debug("Battery check unavailable (%s) — assuming AC.", exc)
        return False


def get_thermal_pressure() -> float:
    """
    0.0–∞ ratio of (1-minute load average) / (CPU count).
    Values > THERMAL_THRESHOLD indicate the system is under load.
    """
    try:
        load1 = os.getloadavg()[0]
        cpus  = os.cpu_count() or 1
        return load1 / cpus
    except Exception:
        return 0.0


def is_thermal_ok() -> bool:
    return get_thermal_pressure() <= _THERMAL_THRESHOLD


def check_hardware_gates() -> None:
    """Raise HardwareGateError if any gate is failing. Call before execution."""
    if is_on_battery():
        raise HardwareGateError(
            "Host is on battery power — SimLab execution blocked."
        )
    pressure = get_thermal_pressure()
    if pressure > _THERMAL_THRESHOLD:
        raise HardwareGateError(
            f"Thermal pressure {pressure:.2f} exceeds threshold {_THERMAL_THRESHOLD} "
            "— SimLab paused to protect hardware."
        )


# ── Lock management ───────────────────────────────────────────────────────────


def _acquire_lock(run_id: str) -> bool:
    """Write lock file. Returns False if already locked by another session."""
    if _LOCK_FILE.exists():
        try:
            data = json.loads(_LOCK_FILE.read_text())
            log.info("SimLab lock held by run_id=%s pid=%s", data.get("run_id"), data.get("pid"))
        except Exception:
            pass
        return False
    try:
        _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOCK_FILE.write_text(json.dumps({
            "run_id": run_id,
            "pid":    os.getpid(),
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }))
        return True
    except OSError as exc:
        log.warning("Could not write SimLab lock: %s", exc)
        return False


def _release_lock() -> None:
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ── Orchestrator ──────────────────────────────────────────────────────────────


class IdleOrchestrator:
    """
    Controls when SimLab sessions run and wires up all subsystem components.

    Example:
        orch = IdleOrchestrator(mode="nightly", budget_minutes=45)
        run_id = orch.run()
        if run_id:
            print(f"SimLab session {run_id} completed.")
    """

    def __init__(
        self,
        mode: str = "canary",
        budget_minutes: int = _DEFAULT_BUDGET,
        wait_for_idle: bool = True,
        max_wait_minutes: int = 20,
    ) -> None:
        self.mode             = mode
        self.budget_minutes   = budget_minutes
        self.wait_for_idle    = wait_for_idle
        self.max_wait_minutes = max_wait_minutes

        self._stop_event = threading.Event()
        self._run_id: str = ""
        self._deadline:   float = 0.0

        signal.signal(signal.SIGINT,  self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    # ── Signal handling ───────────────────────────────────────────────────────

    def _handle_signal(self, signum, frame) -> None:
        log.info("SimLab received signal %s — stopping after current scenario.", signum)
        self._stop_event.set()

    # ── Budget ────────────────────────────────────────────────────────────────

    def check_budget(self) -> None:
        """Call between scenarios. Raises BudgetExceeded when time is up."""
        if time.monotonic() > self._deadline:
            raise BudgetExceeded(
                f"SimLab budget of {self.budget_minutes} minutes exceeded."
            )

    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    # ── Idle wait ─────────────────────────────────────────────────────────────

    def _wait_for_idle(self) -> bool:
        """
        Poll until hardware gates pass or timeout.
        Returns True when system is ready, False to abort.
        """
        deadline = time.monotonic() + self.max_wait_minutes * 60
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False
            try:
                check_hardware_gates()
                return True
            except HardwareGateError as exc:
                log.info("Gate not clear: %s — retrying in %ds.", exc, _POLL_INTERVAL_S)
            time.sleep(_POLL_INTERVAL_S)
        return False

    # ── Main entry ────────────────────────────────────────────────────────────

    def run(self) -> Optional[str]:
        """
        Full session lifecycle. Returns run_id on completion, None if skipped.
        Safe to call from nightly.py or a launchd plist.
        """
        import uuid
        self._run_id  = str(uuid.uuid4())[:8]
        self._deadline = time.monotonic() + self.budget_minutes * 60

        log.info(
            "SimLab session %s starting (mode=%s, budget=%dm).",
            self._run_id, self.mode, self.budget_minutes,
        )

        # Gate check
        try:
            check_hardware_gates()
        except HardwareGateError as exc:
            if self.wait_for_idle:
                log.info("Initial gate failed (%s) — waiting for idle.", exc)
                if not self._wait_for_idle():
                    log.info("SimLab skipped — system never became idle.")
                    return None
            else:
                log.info("SimLab skipped: %s", exc)
                return None

        # Lock
        if not _acquire_lock(self._run_id):
            log.info("SimLab already running — skipping this session.")
            return None

        try:
            self._execute_session()
        except BudgetExceeded:
            log.info("SimLab session %s hit budget limit — stopping cleanly.", self._run_id)
        except Exception:
            log.exception("SimLab session %s crashed.", self._run_id)
        finally:
            _release_lock()

        log.info("SimLab session %s finished.", self._run_id)
        return self._run_id

    # ── Session wiring ────────────────────────────────────────────────────────

    def _execute_session(self) -> None:
        """Import and wire all SimLab components, then run the eval loop."""
        # Late imports — keep orchestrator importable without heavy deps
        from .eval_runner        import EvalRunner, EvalSandbox
        from .failure_store      import FailureStore
        from .grader             import GraderComposite
        from .improvement_engine import ImprovementEngine
        from .reporter           import Reporter
        from .scenario_generator import ScenarioGenerator
        from .verification       import VerificationPipeline

        gen      = ScenarioGenerator()
        grader   = GraderComposite()
        store    = FailureStore()
        improver = ImprovementEngine(store)
        verifier = VerificationPipeline()
        reporter = Reporter()

        fraction  = _CANARY_FRACTION if self.mode == "canary" else 1.0
        scenarios = gen.generate(mode=self.mode, fraction=fraction)
        log.info("SimLab: %d scenarios queued.", len(scenarios))

        results = []
        with EvalSandbox() as sandbox:
            runner = EvalRunner(sandbox=sandbox, orchestrator=self)
            for scenario in scenarios:
                self.check_budget()
                if self.is_stopping():
                    break

                # Mid-session thermal check — pause up to 60 s if spike
                if not is_thermal_ok():
                    log.info("Thermal spike detected — pausing 60 s.")
                    self._stop_event.wait(timeout=60)
                    if not is_thermal_ok():
                        log.warning("Thermal still high — aborting session early.")
                        break

                result = runner.run_scenario(scenario, grader)
                results.append(result)

                if result.failed:
                    store.record(result, scenario)

        # Improvement cycle
        failures  = store.get_recent(run_id=self._run_id)
        proposals = improver.propose(failures)
        applied, rejected = [], []

        for prop in proposals:
            if prop.tier == "C" or prop.requires_human:
                store.save_proposal(prop)
                rejected.append(prop.description)
                continue
            vr = verifier.verify(prop, grader=grader)
            if vr.promoted:
                improver.apply(prop)
                applied.append(prop.description)
            else:
                rejected.append(prop.description)

        # Report
        report = reporter.generate(
            run_id=self._run_id,
            results=results,
            failure_store=store,
            applied=applied,
            rejected=rejected,
        )
        reporter.write(report)


# ── CLI entry point ───────────────────────────────────────────────────────────


def _cli_main() -> None:
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Adwi SimLab — bounded eval harness")
    parser.add_argument("--full",    action="store_true", help="run full scenario corpus")
    parser.add_argument("--nightly", action="store_true", help="nightly mode (full + verbose)")
    parser.add_argument("--budget",  type=int, default=30, help="max runtime in minutes")
    args = parser.parse_args()

    mode   = "nightly" if args.nightly else ("full" if args.full else "canary")
    budget = 60 if args.nightly else args.budget

    orch   = IdleOrchestrator(mode=mode, budget_minutes=budget)
    run_id = orch.run()
    sys.exit(0 if run_id else 1)


if __name__ == "__main__":
    _cli_main()
