"""
adwi/simlab — Bounded continuous evaluation and self-improvement harness.

Entry points:
    from adwi.simlab import IdleOrchestrator
    orch = IdleOrchestrator(mode="canary", budget_minutes=15)
    run_id = orch.run()

Or from the command line:
    python3 -m adwi.simlab           # canary mode
    python3 -m adwi.simlab --full    # full corpus
    python3 -m adwi.simlab --nightly # nightly maintenance mode
"""

from .idle_orchestrator import IdleOrchestrator
from .schemas import (
    EvalResult,
    FailureRecord,
    ImprovementProposal,
    Scenario,
    SimlabReport,
    VerificationResult,
    make_fingerprint,
    now_iso,
)

__all__ = [
    "IdleOrchestrator",
    "Scenario",
    "EvalResult",
    "FailureRecord",
    "ImprovementProposal",
    "VerificationResult",
    "SimlabReport",
    "make_fingerprint",
    "now_iso",
]
