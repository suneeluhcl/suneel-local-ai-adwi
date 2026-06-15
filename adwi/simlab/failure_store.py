"""
simlab/failure_store.py

Persistent, deduplicated failure log for Adwi SimLab.

Schema design:
  failures      — one row per unique (expected_intent, actual_intent, error_class)
                  keyed by 16-hex fingerprint; occurrence_count incremented on repeat
  eval_results  — one row per EvalResult; linked to failure by fingerprint
  proposals     — improvement proposals pending human review or auto-apply

Fingerprinting:
  fingerprint = SHA-256[:16] of "expected|actual|error_class"
  Duplicate failure → increment occurrence_count, append prompt to variations list.
  This prevents database bloat from semantically identical failures.

Clustering:
  cluster_by_error_class() returns failures grouped by error_class, sorted by count.
  This drives the ImprovementEngine to address the most frequent failure patterns first.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .schemas import (
    EvalResult,
    FailureRecord,
    ImprovementProposal,
    Scenario,
    make_fingerprint,
    now_iso,
)

log = logging.getLogger(__name__)

_WORKSPACE   = Path(__file__).parent.parent.parent
_DB_PATH     = _WORKSPACE / "logs" / "simlab_failures.db"
_SCHEMA_SQL  = """
CREATE TABLE IF NOT EXISTS failures (
    fingerprint       TEXT PRIMARY KEY,
    expected_intent   TEXT,
    actual_intent     TEXT,
    error_class       TEXT NOT NULL,
    failure_category  TEXT NOT NULL,
    occurrence_count  INTEGER NOT NULL DEFAULT 1,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    eval_result_ids   TEXT NOT NULL DEFAULT '[]',   -- JSON list
    status            TEXT NOT NULL DEFAULT 'new',
    variations        TEXT NOT NULL DEFAULT '[]',   -- JSON list of prompt strings
    root_cause_hint   TEXT NOT NULL DEFAULT '',
    affected_modules  TEXT NOT NULL DEFAULT '[]'    -- JSON list
);

CREATE TABLE IF NOT EXISTS eval_results (
    eval_result_id  TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    scenario_id     TEXT NOT NULL,
    fingerprint     TEXT,
    timestamp       TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    actual_intent   TEXT,
    overall_grade   TEXT NOT NULL,
    latency_ms      REAL NOT NULL,
    scores          TEXT NOT NULL DEFAULT '{}',    -- JSON
    grader_notes    TEXT NOT NULL DEFAULT '[]',    -- JSON
    stdout_snippet  TEXT NOT NULL DEFAULT '',      -- first 500 chars only
    FOREIGN KEY (fingerprint) REFERENCES failures (fingerprint)
);

CREATE TABLE IF NOT EXISTS proposals (
    id              TEXT PRIMARY KEY,
    tier            TEXT NOT NULL,
    fingerprint     TEXT,
    proposal_type   TEXT NOT NULL,
    description     TEXT NOT NULL,
    proposed_change TEXT NOT NULL DEFAULT '{}',  -- JSON
    risk_level      TEXT NOT NULL,
    requires_human  INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    applied_at      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_failures_status ON failures(status);
CREATE INDEX IF NOT EXISTS idx_failures_error  ON failures(error_class);
CREATE INDEX IF NOT EXISTS idx_results_run     ON eval_results(run_id);
"""


# ── Error class detection ─────────────────────────────────────────────────────


def _classify_error(result: EvalResult, scenario: Scenario) -> tuple[str, str]:
    """
    Returns (error_class, failure_category).
    error_class is a fine-grained label; failure_category is the broad bucket.
    """
    exp = scenario.expected_intent
    act = result.actual_intent

    # Safety failures are critical
    if "must_refuse" in scenario.tags:
        if "safety" in result.scores and result.scores["safety"] == 0.0:
            return "safety_miss", "safety"

    # Timeout / crash
    if not result.exit_ok:
        return "execution_error", "system"
    if result.latency_ms > 30_000:
        return "timeout", "performance"

    # Routing failures
    if exp and act and act != exp:
        if act == "capabilities" and exp == "chat":
            return "chat_routed_to_capabilities", "nlu"
        if act == "sync" and exp == "chat":
            return "chat_routed_to_sync", "nlu"
        return "routing_miss", "nlu"

    if exp and act is None:
        return "intent_not_captured", "nlu"

    # Latency
    if result.latency_ms > 8_000:
        return "slow_response", "performance"

    # Content
    if "content" in result.scores and result.scores["content"] < 0.5:
        return "weak_answer", "content"

    return "unknown", "misc"


def _guess_affected_modules(error_class: str) -> list[str]:
    mapping = {
        "routing_miss": ["adwi_cli.py", "memory.py"],
        "chat_routed_to_capabilities": ["adwi_cli.py", "_INTENT_SYSTEM"],
        "chat_routed_to_sync": ["adwi_cli.py", "_INTENT_SYSTEM"],
        "intent_not_captured": ["adwi_cli.py", "classify_intent"],
        "safety_miss": ["adwi_cli.py", "path_validator.py"],
        "execution_error": ["adwi_cli.py"],
        "timeout": ["adwi_cli.py", "reason_engine.py"],
        "weak_answer": ["adwi_cli.py", "reason_engine.py"],
        "slow_response": ["adwi_cli.py", "ollama"],
    }
    return mapping.get(error_class, ["adwi_cli.py"])


# ── Store ─────────────────────────────────────────────────────────────────────


class FailureStore:
    """
    Thread-safe SQLite-backed failure and proposal store.
    All writes use a single threading.Lock.
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:   # sqlite3 connection as CM: commit on success, rollback on error
                yield conn
        finally:
            conn.close()

    # ── Recording ─────────────────────────────────────────────────────────────

    def record(self, result: EvalResult, scenario: Scenario) -> str:
        """
        Upsert a failure record.
        Duplicate fingerprints increment occurrence_count and append the
        prompt to variations[] instead of creating a new row.
        Returns the fingerprint.
        """
        error_class, fail_cat = _classify_error(result, scenario)
        fp = make_fingerprint(scenario.expected_intent, result.actual_intent, error_class)
        ts = now_iso()

        with self._lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT * FROM failures WHERE fingerprint = ?", (fp,)
            ).fetchone()

            if existing:
                # Dedup: increment count, record variation
                variations = json.loads(existing["variations"])
                if scenario.prompt not in variations:
                    variations.append(scenario.prompt)
                eval_ids = json.loads(existing["eval_result_ids"])
                eval_ids.append(result.eval_result_id)
                conn.execute(
                    """UPDATE failures
                       SET occurrence_count = occurrence_count + 1,
                           last_seen = ?,
                           status = CASE status WHEN 'resolved' THEN 'recurring' ELSE 'recurring' END,
                           variations = ?,
                           eval_result_ids = ?
                       WHERE fingerprint = ?""",
                    (ts, json.dumps(variations[-20:]), json.dumps(eval_ids[-50:]), fp),
                )
            else:
                conn.execute(
                    """INSERT INTO failures
                       (fingerprint, expected_intent, actual_intent, error_class,
                        failure_category, first_seen, last_seen, eval_result_ids,
                        variations, root_cause_hint, affected_modules)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (fp,
                     scenario.expected_intent, result.actual_intent, error_class,
                     fail_cat, ts, ts,
                     json.dumps([result.eval_result_id]),
                     json.dumps([scenario.prompt]),
                     "",
                     json.dumps(_guess_affected_modules(error_class))),
                )

            # Always record the full eval result
            conn.execute(
                """INSERT OR REPLACE INTO eval_results
                   (eval_result_id, run_id, scenario_id, fingerprint, timestamp,
                    prompt, actual_intent, overall_grade, latency_ms,
                    scores, grader_notes, stdout_snippet)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (result.eval_result_id, result.run_id, scenario.id, fp,
                 result.timestamp, scenario.prompt, result.actual_intent,
                 result.overall_grade, result.latency_ms,
                 json.dumps(result.scores), json.dumps(result.grader_notes),
                 result.stdout[:500]),
            )

        return fp

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_by_fingerprint(self, fp: str) -> Optional[FailureRecord]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM failures WHERE fingerprint = ?", (fp,)).fetchone()
        return _row_to_failure(row) if row else None

    def get_recent(self, run_id: str, limit: int = 50) -> list[FailureRecord]:
        """Return failures that have an eval_result linked to this run_id."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT f.*
                   FROM failures f
                   JOIN eval_results e ON e.fingerprint = f.fingerprint
                   WHERE e.run_id = ?
                   ORDER BY f.last_seen DESC LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        return [_row_to_failure(r) for r in rows]

    def get_recurring(self, min_count: int = 2, limit: int = 20) -> list[FailureRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM failures
                   WHERE occurrence_count >= ? AND status != 'resolved'
                   ORDER BY occurrence_count DESC LIMIT ?""",
                (min_count, limit),
            ).fetchall()
        return [_row_to_failure(r) for r in rows]

    def cluster_by_error_class(self) -> dict[str, list[FailureRecord]]:
        """Group failures by error_class, sorted by total occurrences descending."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM failures WHERE status != 'resolved' ORDER BY occurrence_count DESC"
            ).fetchall()
        clusters: dict[str, list[FailureRecord]] = {}
        for row in rows:
            rec = _row_to_failure(row)
            clusters.setdefault(rec.error_class, []).append(rec)
        return clusters

    def mark_resolved(self, fingerprint: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE failures SET status = 'resolved' WHERE fingerprint = ?",
                (fingerprint,),
            )

    # ── Proposals ─────────────────────────────────────────────────────────────

    def save_proposal(self, prop: ImprovementProposal) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO proposals
                   (id, tier, fingerprint, proposal_type, description,
                    proposed_change, risk_level, requires_human, status,
                    created_at, applied_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (prop.id, prop.tier, prop.failure_fingerprint, prop.proposal_type,
                 prop.description, json.dumps(prop.proposed_change), prop.risk_level,
                 int(prop.requires_human), prop.status, prop.created_at, prop.applied_at),
            )

    def get_proposals_needing_review(self) -> list[ImprovementProposal]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE requires_human = 1 AND status = 'pending'"
            ).fetchall()
        return [_row_to_proposal(r) for r in rows]


# ── Row converters ────────────────────────────────────────────────────────────


def _row_to_failure(row: sqlite3.Row) -> FailureRecord:
    d = dict(row)
    d["eval_result_ids"] = json.loads(d.get("eval_result_ids", "[]"))
    d["variations"]      = json.loads(d.get("variations", "[]"))
    d["affected_modules"] = json.loads(d.get("affected_modules", "[]"))
    return FailureRecord.from_dict(d)


def _row_to_proposal(row: sqlite3.Row) -> ImprovementProposal:
    d = dict(row)
    return ImprovementProposal(
        id=d["id"], tier=d["tier"], failure_fingerprint=d["fingerprint"],
        proposal_type=d["proposal_type"], description=d["description"],
        proposed_change=json.loads(d["proposed_change"]),
        risk_level=d["risk_level"], requires_human=bool(d["requires_human"]),
        status=d["status"], created_at=d["created_at"], applied_at=d["applied_at"],
    )
