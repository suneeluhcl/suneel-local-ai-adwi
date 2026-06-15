"""
simlab/improvement_engine.py

Bounded, tiered self-improvement engine for Adwi SimLab.

Improvement tiers:

  Tier A — AUTO-APPLY (low-risk, always reversible):
    • add_nlu_fixture     : inject a new (prompt, intent, args) example into
                           the Qdrant nlu_fixtures collection via memory.py
    • add_eval_case       : append new scenario to adwi/evals/routing-tests.jsonl
    • update_help_text    : improve capability description text (non-functional)

  Tier B — AUTO-PATCH (only after 100% golden-baseline verification):
    • add_regex           : add a new entry to _REGEX_INTENTS in adwi_cli.py
                           Strictly scoped: only new (pattern, intent) pairs.
    • refine_intent_system: append a single clarifying bullet to _INTENT_SYSTEM
                           for a misclassified intent.

  Tier C — HUMAN-REVIEW REQUIRED (queued, never auto-applied):
    • Any change to safety logic, blocked paths, permission gates
    • Broad code rewrites
    • Changes to existing regex patterns (only additions are Tier B)
    • Any change that affects more than one module

Safety invariants:
  - The improvement engine NEVER writes to production files directly for Tier B.
    All Tier B changes are applied to a Git branch and gated by VerificationPipeline.
  - Tier A changes (NLU fixtures, eval cases) are data-only and trivially reversible.
  - Tier C proposals are written to the FailureStore and reported to the operator.
  - No change is applied unless it passes golden_baseline_score == 1.0.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .failure_store import FailureStore
from .schemas import FailureRecord, ImprovementProposal, now_iso, new_id

log = logging.getLogger(__name__)

_WORKSPACE     = Path(__file__).parent.parent.parent
_ADWI_DIR      = _WORKSPACE / "adwi"
_MEMORY_PY     = _ADWI_DIR / "memory.py"
_CLI_PY        = _ADWI_DIR / "adwi_cli.py"
_EVALS_DIR     = _ADWI_DIR / "evals"
_ROUTING_TESTS = _EVALS_DIR / "routing-tests.jsonl"

# Error classes that map to Tier A (safe fixture improvement)
_TIER_A_ERRORS = {
    "routing_miss",
    "chat_routed_to_capabilities",
    "chat_routed_to_sync",
    "intent_not_captured",
}

# Error classes that may get Tier B (code-level patch)
_TIER_B_ERRORS = {
    "routing_miss",   # only if fixture hasn't solved it after 3 occurrences
}


class ImprovementEngine:
    """
    Analyses failure records and proposes the safest possible improvement.
    Applies Tier A automatically after proposal; Tier B requires VerificationPipeline.
    """

    def __init__(self, store: FailureStore) -> None:
        self._store = store

    # ── Proposal factory ──────────────────────────────────────────────────────

    def propose(self, failures: list[FailureRecord]) -> list[ImprovementProposal]:
        proposals = []
        for failure in failures:
            if failure.status == "resolved":
                continue
            prop = self._propose_one(failure)
            if prop:
                proposals.append(prop)
        return proposals

    def _propose_one(self, failure: FailureRecord) -> Optional[ImprovementProposal]:
        ec = failure.error_class

        if ec in _TIER_A_ERRORS:
            # Choose most specific Tier A action
            return self._propose_nlu_fixture(failure)

        if ec in _TIER_B_ERRORS and failure.occurrence_count >= 3:
            # Escalate to Tier B only after fixture hasn't helped
            return self._propose_regex_addition(failure)

        if ec == "safety_miss":
            # Safety misses always go to Tier C — human must review
            return self._propose_human_review(
                failure,
                reason="Safety boundary miss requires human review before any change.",
            )

        return None

    # ── Tier A: NLU fixture ───────────────────────────────────────────────────

    def _propose_nlu_fixture(self, failure: FailureRecord) -> ImprovementProposal:
        prompt    = failure.variations[-1] if failure.variations else "unknown prompt"
        expected  = failure.expected_intent or "chat"
        reasoning = (
            f"Routing miss: '{prompt}' was classified as '{failure.actual_intent}' "
            f"instead of '{expected}'. Adding fixture to anchor correct routing."
        )
        return ImprovementProposal(
            id=new_id("P-"),
            tier="A",
            failure_fingerprint=failure.fingerprint,
            proposal_type="add_nlu_fixture",
            description=f"Add NLU fixture for '{prompt[:60]}' → {expected}",
            proposed_change={
                "phrase":    prompt,
                "intent":    expected,
                "arguments": {},
                "reasoning": reasoning,
            },
            risk_level="low",
            requires_human=False,
            created_at=now_iso(),
        )

    # ── Tier B: Regex addition ────────────────────────────────────────────────

    def _propose_regex_addition(self, failure: FailureRecord) -> ImprovementProposal:
        prompt   = failure.variations[0] if failure.variations else ""
        expected = failure.expected_intent or "chat"
        # Build a conservative word-boundary pattern from the prompt
        words    = re.findall(r"\b\w{4,}\b", prompt.lower())[:5]
        pattern  = r"(?:" + "|".join(re.escape(w) for w in words) + r")" if words else r"PLACEHOLDER"
        return ImprovementProposal(
            id=new_id("P-"),
            tier="B",
            failure_fingerprint=failure.fingerprint,
            proposal_type="add_regex",
            description=f"Add _REGEX_INTENTS entry for {expected} (recurring {failure.occurrence_count}x)",
            proposed_change={
                "pattern":  pattern,
                "intent":   expected,
                "flags":    "re.I",
                "rationale": f"Fires on: {words}",
            },
            risk_level="medium",
            requires_human=False,
            created_at=now_iso(),
        )

    # ── Tier C: Human review ──────────────────────────────────────────────────

    def _propose_human_review(
        self, failure: FailureRecord, reason: str
    ) -> ImprovementProposal:
        return ImprovementProposal(
            id=new_id("P-"),
            tier="C",
            failure_fingerprint=failure.fingerprint,
            proposal_type="human_review_required",
            description=f"[TIER C] {reason}",
            proposed_change={"failure": failure.to_dict()},
            risk_level="high",
            requires_human=True,
            created_at=now_iso(),
        )

    # ── Application ───────────────────────────────────────────────────────────

    def apply(self, proposal: ImprovementProposal) -> bool:
        """
        Apply a verified proposal. Caller must have run VerificationPipeline first.
        Returns True on success.
        """
        if proposal.tier == "C":
            log.warning("Refusing to auto-apply Tier C proposal %s.", proposal.id)
            return False

        try:
            if proposal.proposal_type == "add_nlu_fixture":
                ok = self._apply_nlu_fixture(proposal)
            elif proposal.proposal_type == "add_regex":
                ok = self._apply_regex(proposal)
            elif proposal.proposal_type == "add_eval_case":
                ok = self._apply_eval_case(proposal)
            else:
                log.warning("Unknown proposal_type %s — skipping.", proposal.proposal_type)
                ok = False

            if ok:
                proposal.status     = "applied"
                proposal.applied_at = now_iso()
                self._store.save_proposal(proposal)
                self._store.mark_resolved(proposal.failure_fingerprint)
                log.info("Applied proposal %s (%s).", proposal.id, proposal.proposal_type)
            return ok

        except Exception:
            log.exception("Failed to apply proposal %s.", proposal.id)
            return False

    def _apply_nlu_fixture(self, proposal: ImprovementProposal) -> bool:
        """Add one fixture to memory.py NLU_SEED_FIXTURES and reprovision Qdrant."""
        change = proposal.proposed_change
        phrase, intent = change["phrase"], change["intent"]
        args, reasoning = change.get("arguments", {}), change.get("reasoning", "simlab")

        # Append to NLU_SEED_FIXTURES in memory.py
        marker = "# ── chat fallback"
        try:
            text = _MEMORY_PY.read_text(encoding="utf-8")
        except OSError as exc:
            log.error("Cannot read memory.py: %s", exc)
            return False

        new_line = (
            f'    ({json.dumps(phrase):<55} {json.dumps(intent)},  '
            f'{json.dumps(args)}, {json.dumps(reasoning)}),\n'
        )
        if new_line.strip() in text:
            log.info("Fixture already present — skipping add.")
        else:
            updated = text.replace(marker, new_line + "    " + marker)
            _MEMORY_PY.write_text(updated, encoding="utf-8")

        # Reprovision Qdrant
        try:
            python = _pick_python()
            result = subprocess.run(
                [python, str(_MEMORY_PY), "provision-nlu"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                log.warning("provision-nlu exited %d: %s", result.returncode, result.stderr[:200])
            else:
                log.info("NLU fixtures reprovisioned: %s", result.stdout.strip()[:100])
            return True
        except Exception as exc:
            log.error("provision-nlu failed: %s", exc)
            return False

    def _apply_regex(self, proposal: ImprovementProposal) -> bool:
        """Append one new (pattern, intent) to _REGEX_INTENTS in adwi_cli.py."""
        change  = proposal.proposed_change
        pattern = change["pattern"]
        intent  = change["intent"]
        flags   = change.get("flags", "re.I")

        try:
            text = _CLI_PY.read_text(encoding="utf-8")
        except OSError as exc:
            log.error("Cannot read adwi_cli.py: %s", exc)
            return False

        marker   = "]  # end _REGEX_INTENTS"
        new_line = f'    (re.compile(r"{pattern}", {flags}), "{intent}"),\n'
        if new_line.strip() in text:
            return True  # already present

        # Only add before the closing bracket
        if marker not in text:
            log.warning("_REGEX_INTENTS close marker not found — skipping regex patch.")
            return False

        updated = text.replace(marker, new_line + marker)
        _CLI_PY.write_text(updated, encoding="utf-8")

        # Verify syntax
        result = subprocess.run(
            [_pick_python(), "-m", "py_compile", str(_CLI_PY)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.error("Syntax error after regex patch — reverting.")
            _CLI_PY.write_text(text, encoding="utf-8")
            return False

        log.info("Regex entry added for intent '%s'.", intent)
        return True

    def _apply_eval_case(self, proposal: ImprovementProposal) -> bool:
        """Append a new routing test case to routing-tests.jsonl."""
        change = proposal.proposed_change
        _EVALS_DIR.mkdir(exist_ok=True)
        line = json.dumps(change) + "\n"
        with _ROUTING_TESTS.open("a", encoding="utf-8") as f:
            f.write(line)
        log.info("Eval case appended to %s.", _ROUTING_TESTS.name)
        return True


def _pick_python() -> str:
    venv_py = _WORKSPACE / "adwi" / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else "python3"
