"""
simlab/reporter.py

Generates human-readable and machine-readable SimLab session artifacts.

Output files (written to logs/simlab/):
  simlab-{run_id}.md    — Markdown summary for human review
  simlab-{run_id}.json  — Full structured record for automated processing

Report covers:
  - Session metadata (run_id, duration, mode)
  - Pass/fail/warn counts and pass rate
  - Top 5 most common failures (by error class and occurrence)
  - Newly applied improvements (Tier A/B)
  - Proposals pending human review (Tier C)
  - Top 5 slowest prompts
  - Regression alerts
  - New eval cases added this session
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .failure_store import FailureStore
from .schemas import EvalResult, SimlabReport, now_iso

log = logging.getLogger(__name__)

_WORKSPACE   = Path(__file__).parent.parent.parent
_REPORT_DIR  = _WORKSPACE / "logs" / "simlab"


class Reporter:
    """Generates and persists SimLab session reports."""

    def __init__(self, report_dir: Path = _REPORT_DIR) -> None:
        self._dir = report_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        run_id: str,
        results: list[EvalResult],
        failure_store: FailureStore,
        applied: list[str],
        rejected: list[str],
        started_at: Optional[str] = None,
    ) -> SimlabReport:
        completed_at = now_iso()
        started_at   = started_at or completed_at

        passed  = sum(1 for r in results if r.overall_grade == "pass")
        failed  = sum(1 for r in results if r.overall_grade in ("fail", "error"))
        warned  = sum(1 for r in results if r.overall_grade == "warn")

        # Top failures by occurrence count
        clusters  = failure_store.cluster_by_error_class()
        top_fail  = []
        for error_class, recs in sorted(clusters.items(), key=lambda x: -sum(r.occurrence_count for r in x[1]))[:5]:
            top_fail.append({
                "error_class": error_class,
                "count":       sum(r.occurrence_count for r in recs),
                "examples":    [r.variations[-1][:80] if r.variations else "?" for r in recs[:2]],
            })

        # Top 5 slowest
        slow = sorted(results, key=lambda r: -r.latency_ms)[:5]
        slow_list = [{"prompt": r.prompt[:80], "latency_ms": round(r.latency_ms)} for r in slow]

        # Regression alerts (failed results that were previously passing)
        regressions = [r.prompt[:80] for r in results if r.overall_grade == "fail"
                       and "regression" in (r.grader_notes or [])]

        # Pending human review proposals
        pending = failure_store.get_proposals_needing_review()
        needs_review = [p.description for p in pending[:10]]

        return SimlabReport(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            total_scenarios=len(results),
            passed=passed,
            failed=failed,
            warned=warned,
            top_failures=top_fail,
            improvements_applied=applied,
            improvements_rejected=rejected,
            regression_alerts=regressions,
            slow_prompts=slow_list,
            new_eval_cases_added=sum(1 for a in applied if "eval case" in a.lower()),
            needs_human_review=needs_review,
        )

    def write(self, report: SimlabReport) -> tuple[Path, Path]:
        """Write Markdown + JSON reports. Returns (md_path, json_path)."""
        md_path   = self._dir / f"simlab-{report.run_id}.md"
        json_path = self._dir / f"simlab-{report.run_id}.json"

        md_path.write_text(_render_markdown(report), encoding="utf-8")
        json_path.write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )
        log.info("SimLab report: %s  %s", md_path.name, json_path.name)
        return md_path, json_path


# ── Markdown renderer ─────────────────────────────────────────────────────────


def _render_markdown(r: SimlabReport) -> str:
    pass_pct = f"{r.pass_rate * 100:.1f}"
    lines = [
        f"# Adwi SimLab Report — {r.run_id}",
        "",
        f"**Started:** {r.started_at}  ",
        f"**Completed:** {r.completed_at}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total scenarios | {r.total_scenarios} |",
        f"| Passed | {r.passed} ({pass_pct}%) |",
        f"| Failed | {r.failed} |",
        f"| Warned | {r.warned} |",
        "",
    ]

    if r.top_failures:
        lines += ["## Top Failure Patterns", ""]
        for tf in r.top_failures:
            lines.append(f"**{tf['error_class']}** ({tf['count']} occurrences)")
            for ex in tf.get("examples", []):
                lines.append(f'  - "{ex}"')
        lines.append("")

    if r.slow_prompts:
        lines += ["## Slowest Prompts", ""]
        for sp in r.slow_prompts:
            lines.append(f"- `{sp['latency_ms']}ms` — {sp['prompt']}")
        lines.append("")

    if r.improvements_applied:
        lines += ["## Improvements Applied", ""]
        for a in r.improvements_applied:
            lines.append(f"- ✅ {a}")
        lines.append("")

    if r.needs_human_review:
        lines += ["## ⚠️ Needs Human Review", ""]
        for n in r.needs_human_review:
            lines.append(f"- {n}")
        lines.append("")

    if r.regression_alerts:
        lines += ["## 🚨 Regression Alerts", ""]
        for ra in r.regression_alerts:
            lines.append(f"- {ra}")
        lines.append("")

    lines += [
        "---",
        "*Generated by Adwi SimLab — bounded continuous evaluation harness.*",
        "",
    ]
    return "\n".join(lines)
