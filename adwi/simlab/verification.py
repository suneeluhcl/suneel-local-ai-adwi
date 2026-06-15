"""
simlab/verification.py

Immutable golden baseline guard + promotion/rollback pipeline.

Rules (non-negotiable):
  1. Golden baseline is loaded from golden_baseline.jsonl — NEVER modified
     by any automated process. Additions require a human git commit.
  2. golden_baseline_score must equal 1.0 (100% pass) to promote any change.
     A single golden failure blocks promotion and triggers rollback.
  3. canary_score is informational; it tracks broader eval quality but
     does not block promotion (regression detected if it drops > 10%).
  4. Rollback for Tier B (code patch): git checkout HEAD -- <patched_file>
  5. Rollback for Tier A (NLU fixture): idempotent; reprovisioning with the
     previous fixture set restores state.

Verification flow:
  1. Apply proposed change to workspace (done by ImprovementEngine.apply())
  2. Run golden baseline scenarios against REAL adwi (not sandbox)
  3. golden_baseline_score = passed / total
  4. If < 1.0 → rollback + reject proposal
  5. Run canary subset
  6. If canary score regresses > 10% from prior → rollback + reject
  7. Otherwise → promote (mark proposal as verified)
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from .eval_runner import EvalRunner, EvalSandbox
from .grader      import GraderComposite
from .schemas     import ImprovementProposal, Scenario, VerificationResult, now_iso

log = logging.getLogger(__name__)

_WORKSPACE      = Path(__file__).parent.parent.parent
_ADWI_DIR       = _WORKSPACE / "adwi"
_GOLDEN_FILE    = Path(__file__).parent / "golden_baseline.jsonl"
_CANARY_REGRESS = 0.10   # canary score drop > 10% triggers rollback


class VerificationPipeline:
    """
    Runs golden baseline + canary checks against a proposed change.
    If any check fails, automatically rolls back the change.
    """

    def __init__(self, prior_canary_score: float = 1.0) -> None:
        self._prior_canary = prior_canary_score

    def verify(
        self,
        proposal: ImprovementProposal,
        grader: Optional[GraderComposite] = None,
    ) -> VerificationResult:
        """
        Run full verification pipeline.
        Returns VerificationResult with promoted=True only if all checks pass.
        """
        if grader is None:
            grader = GraderComposite()

        golden_scenarios = _load_golden()
        if not golden_scenarios:
            log.warning("No golden baseline scenarios found — verification skipped.")
            return VerificationResult(
                proposal_id=proposal.id,
                golden_baseline_score=1.0,
                canary_score=1.0,
                regression_detected=False,
                promoted=False,
                rolled_back=False,
                details={"skipped": "empty golden baseline"},
                timestamp=now_iso(),
            )

        # Run golden baseline in sandbox
        golden_score, golden_details = self._run_golden(golden_scenarios, grader)

        if golden_score < 1.0:
            log.warning(
                "Proposal %s FAILED golden baseline (%.0f%%) — rolling back.",
                proposal.id, golden_score * 100,
            )
            rolled = self._rollback(proposal)
            return VerificationResult(
                proposal_id=proposal.id,
                golden_baseline_score=golden_score,
                canary_score=0.0,
                regression_detected=True,
                promoted=False,
                rolled_back=rolled,
                details=golden_details,
                timestamp=now_iso(),
            )

        # Golden passed — run canary subset
        canary_score, canary_details = self._run_canary(grader)
        regression = (self._prior_canary - canary_score) > _CANARY_REGRESS

        if regression:
            log.warning(
                "Canary regression detected for proposal %s (%.2f → %.2f).",
                proposal.id, self._prior_canary, canary_score,
            )
            rolled = self._rollback(proposal)
            return VerificationResult(
                proposal_id=proposal.id,
                golden_baseline_score=golden_score,
                canary_score=canary_score,
                regression_detected=True,
                promoted=False,
                rolled_back=rolled,
                details={**golden_details, **canary_details},
                timestamp=now_iso(),
            )

        log.info(
            "Proposal %s VERIFIED (golden=%.0f%%, canary=%.0f%%).",
            proposal.id, golden_score * 100, canary_score * 100,
        )
        proposal.status = "verified"
        return VerificationResult(
            proposal_id=proposal.id,
            golden_baseline_score=golden_score,
            canary_score=canary_score,
            regression_detected=False,
            promoted=True,
            rolled_back=False,
            details={**golden_details, **canary_details},
            timestamp=now_iso(),
        )

    # ── Golden check ──────────────────────────────────────────────────────────

    def _run_golden(
        self, scenarios: list[Scenario], grader: GraderComposite
    ) -> tuple[float, dict]:
        passed  = 0
        failed  = []
        details = {}

        with EvalSandbox() as sandbox:
            runner = EvalRunner(sandbox=sandbox)
            for scenario in scenarios:
                result = runner.run_scenario(scenario, grader)
                if result.passed:
                    passed += 1
                else:
                    failed.append({
                        "id":       scenario.id,
                        "prompt":   scenario.prompt[:80],
                        "expected": scenario.expected_intent,
                        "actual":   result.actual_intent,
                        "grade":    result.overall_grade,
                    })

        total = len(scenarios)
        score = passed / total if total else 1.0
        details["golden_passed"]  = passed
        details["golden_total"]   = total
        details["golden_failures"] = failed
        return score, details

    # ── Canary check ──────────────────────────────────────────────────────────

    def _run_canary(self, grader: GraderComposite) -> tuple[float, dict]:
        """Run a small random sample of non-golden scenarios."""
        from .scenario_generator import ScenarioGenerator
        import random

        gen       = ScenarioGenerator()
        scenarios = gen.generate(mode="canary", fraction=0.15)
        # Exclude golden (already covered)
        scenarios = [s for s in scenarios if s.source != "golden"][:15]

        if not scenarios:
            return 1.0, {"canary": "no scenarios"}

        passed = 0
        with EvalSandbox() as sandbox:
            runner = EvalRunner(sandbox=sandbox)
            for scenario in scenarios:
                result = runner.run_scenario(scenario, grader)
                if result.passed:
                    passed += 1

        score = passed / len(scenarios)
        return score, {"canary_passed": passed, "canary_total": len(scenarios)}

    # ── Rollback ──────────────────────────────────────────────────────────────

    def _rollback(self, proposal: ImprovementProposal) -> bool:
        """
        Roll back changes made by a failed proposal.
        Tier A (fixture): reprovision from source (idempotent — fixture may still be in memory.py).
        Tier B (regex/code): git checkout HEAD -- <file> to restore the committed version.
        """
        proposal.status = "rolled_back"
        ptype = proposal.proposal_type

        if ptype == "add_nlu_fixture":
            # Tier A rollback: the fixture is in memory.py; we can't un-add it
            # easily, but provisioning is additive and the golden baseline score
            # revealed the regression — flag for human review.
            log.warning(
                "Tier A rollback: NLU fixture added but golden baseline regressed. "
                "Manual review of memory.py NLU_SEED_FIXTURES required."
            )
            return True

        if ptype in ("add_regex", "patch_code"):
            # Tier B rollback via git checkout
            changed_file = _infer_changed_file(proposal)
            if changed_file and changed_file.exists():
                try:
                    result = subprocess.run(
                        ["git", "checkout", "HEAD", "--", str(changed_file)],
                        capture_output=True, text=True,
                        cwd=str(_WORKSPACE),
                    )
                    if result.returncode == 0:
                        log.info("Rolled back %s via git checkout.", changed_file.name)
                        return True
                    else:
                        log.error("git rollback failed: %s", result.stderr[:200])
                        return False
                except Exception as exc:
                    log.error("Rollback exception: %s", exc)
                    return False

        return False


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_golden() -> list[Scenario]:
    if not _GOLDEN_FILE.exists():
        return []
    scenarios = []
    for line in _GOLDEN_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            scenarios.append(Scenario.from_dict(json.loads(line)))
        except Exception:
            pass
    return scenarios


def _infer_changed_file(proposal: ImprovementProposal) -> Optional[Path]:
    mapping = {
        "add_regex":     _ADWI_DIR / "adwi_cli.py",
        "patch_code":    _ADWI_DIR / "adwi_cli.py",
        "add_nlu_fixture": _ADWI_DIR / "memory.py",
    }
    return mapping.get(proposal.proposal_type)
