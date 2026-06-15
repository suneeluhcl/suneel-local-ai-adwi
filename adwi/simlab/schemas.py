"""
simlab/schemas.py — Core data models for Adwi SimLab.

All dataclasses use stdlib only (no pydantic) for minimal dependencies.
Serialisation helpers (to_dict / from_dict) are provided on each class.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


# ── Helpers ───────────────────────────────────────────────────────────────────


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str = "") -> str:
    return f"{prefix}{str(uuid.uuid4())[:8]}"


def make_fingerprint(
    expected_intent: Optional[str],
    actual_intent: Optional[str],
    error_class: str = "",
) -> str:
    """
    Deterministic 16-hex failure hash.
    Combines expected_intent + actual_intent + error_class so that identical
    failure modes from different prompts increment the same counter.
    """
    raw = f"{expected_intent or ''}|{actual_intent or ''}|{error_class or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Scenario ──────────────────────────────────────────────────────────────────


@dataclass
class Scenario:
    """One generated test prompt with its expected outcome metadata."""

    id: str
    prompt: str
    category: str            # disk / chat / safety / memory / rag / routing / …
    difficulty: str          # easy / medium / hard / adversarial
    expected_intent: Optional[str]   # None = flexible (safety / refusal cases)
    expected_outcome_type: str       # route / answer / refuse / error
    tags: list[str] = field(default_factory=list)
    known_risk: Optional[str] = None  # None / low / medium / high
    source: str = "template"          # template / trace / failure / fixture / golden / llm
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ── EvalResult ────────────────────────────────────────────────────────────────


@dataclass
class EvalResult:
    """Output from running one Scenario through the EvalRunner."""

    scenario_id: str
    run_id: str
    timestamp: str
    prompt: str
    actual_intent: Optional[str]   # parsed from ADWI_EVAL_OUTPUT_JSON
    stdout: str
    stderr: str
    exit_ok: bool
    latency_ms: float
    scores: dict[str, float]       # grader_name → score (0.0–1.0)
    overall_grade: str             # pass / fail / warn / error
    grader_notes: list[str] = field(default_factory=list)
    eval_result_id: str = field(default_factory=lambda: new_id("er-"))

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def passed(self) -> bool:
        return self.overall_grade == "pass"

    @property
    def failed(self) -> bool:
        return self.overall_grade in ("fail", "error")


# ── FailureRecord ─────────────────────────────────────────────────────────────


@dataclass
class FailureRecord:
    """
    Persistent, deduplicated failure entry.
    Multiple prompts producing the same (expected, actual, error_class) triple
    increment occurrence_count instead of creating new rows.
    Text variations are stored in `variations` for analysis.
    """

    fingerprint: str           # 16-hex deterministic hash (primary key)
    expected_intent: Optional[str]
    actual_intent: Optional[str]
    error_class: str           # routing_miss / safety_miss / latency / hallucination / …
    failure_category: str      # nlu / safety / performance / content / system
    occurrence_count: int = 1
    first_seen: str = ""
    last_seen: str = ""
    eval_result_ids: list[str] = field(default_factory=list)
    status: str = "new"        # new / recurring / resolved
    variations: list[str] = field(default_factory=list)
    root_cause_hint: str = ""
    affected_modules: list[str] = field(default_factory=list)

    def __post_init__(self):
        ts = now_iso()
        if not self.first_seen:
            self.first_seen = ts
        if not self.last_seen:
            self.last_seen = ts

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FailureRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ── ImprovementProposal ───────────────────────────────────────────────────────


@dataclass
class ImprovementProposal:
    """
    A bounded, auditable proposal for improving Adwi.
    tier A = auto-apply safe; B = verified autopatch; C = human-review required.
    """

    id: str
    tier: str                  # A / B / C
    failure_fingerprint: str
    proposal_type: str         # add_nlu_fixture / add_eval_case / add_regex /
                               # patch_code / update_help
    description: str
    proposed_change: dict      # type-specific payload (see improvement_engine.py)
    risk_level: str            # low / medium / high
    requires_human: bool
    status: str = "pending"    # pending / applied / rejected / rolled_back / verified
    created_at: str = field(default_factory=now_iso)
    applied_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── VerificationResult ────────────────────────────────────────────────────────


@dataclass
class VerificationResult:
    """
    Result of running the verification pipeline against one proposal.
    golden_baseline_score MUST equal 1.0 for promotion.
    """

    proposal_id: str
    golden_baseline_score: float   # 0.0–1.0; must be 1.0 to promote
    canary_score: float            # 0.0–1.0; informational
    regression_detected: bool
    promoted: bool
    rolled_back: bool
    details: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


# ── SimlabReport ──────────────────────────────────────────────────────────────


@dataclass
class SimlabReport:
    """Human + machine readable summary of one SimLab session."""

    run_id: str
    started_at: str
    completed_at: str
    total_scenarios: int
    passed: int
    failed: int
    warned: int
    top_failures: list[dict] = field(default_factory=list)
    improvements_applied: list[str] = field(default_factory=list)
    improvements_rejected: list[str] = field(default_factory=list)
    regression_alerts: list[str] = field(default_factory=list)
    slow_prompts: list[dict] = field(default_factory=list)    # top-5 slowest
    new_eval_cases_added: int = 0
    needs_human_review: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_scenarios if self.total_scenarios else 0.0
