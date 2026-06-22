---
type: codex-review
created: 2026-06-21T11:08:21-05:00
topic: unattended-batch-review
trigger: session-end
branch: main
nlu_baseline: 98.3%
sandbox: read-only
approval_policy: never
status: open
---

# Codex Review: Unattended Batch — 2026-06-21

## Review Brief

- Operator goal: Safe, bounded unattended batch improvement of Adwi using Claude↔Codex collaboration
- Trigger: session-end (operator stepped away)
- Files changed: 6 files across tests, docs, and skills
- High-risk files: none (docs and tests only in execution phase)
- Tests run: full test suite (exit 0), test_validate_env.py (34/34), validate-docs (25/25 PASS)

## Questions Asked

1. Which tasks are SAFE-ADDITIVE vs NEEDS-HUMAN-REVIEW?
2. What should T4 (test_validate_env.py) specifically test?
3. Any gaps in the batch coverage?

## Codex Findings

| Severity | Finding | Evidence | Confidence | Next Action | Status |
|----------|---------|----------|------------|-------------|--------|
| Minor | `chk_safe_command_api` static check only catches `host = "0.0.0.0"` string; misses `ThreadingHTTPServer(("0.0.0.0", ...))` form | validate_adwi_env.py chk_safe_command_api | high | Strengthen static check or add grep for all bind patterns in supervised session | open → documented |
| Minor | CODEX_COLLABORATION.md said "cannot execute any command" — inaccurate; Codex can run read-only shell | CODEX_COLLABORATION.md table | high | Fixed in this batch | accepted |
| Advisory | OPERATOR_HANDBOOK changes should be explicitly reviewed before commit (Codex could not see actual diff) | OPERATOR_HANDBOOK.md | med | Review diff before committing: only T2/T3 changes were made, no other content was touched | open |

## Highest-Value Next Action

**T6: Safe Command API audit logging** — human-attended session, with explicit tests for auth, route allowlisting, secret redaction, and no leakage in logs.

## Reusable Prompt For Next Session

"Read `adwi/docs/LLM_SYSTEM_PRIMING.md` first. Task: Add structured audit logging to `adwi/services/command-api/server.py`. Each request should log: timestamp, route, auth decision (pass/fail/no-secret), latency_ms, response status. Log to `~/.claude/adwi-cmd-api-audit.log` in JSON-lines format. Secrets must never appear in logs. The Telegram bridge should forward a correlation-id header. After implementation, run `adwi/tests/test_remote_control_surface.py` + new audit log tests. Ask Codex for pre-implementation risk check before editing server.py."

## Claude Resolution Notes

- T4 gap (alternative 0.0.0.0 bind form) documented as a known limitation in `test_validate_env.py::TestSafeCommandApiStatic::test_alternative_binding_form_not_caught_by_static_check` — if the check is strengthened in future, this test will start failing, signaling that the gap is closed.
- T5, T6, T7 deferred for human-attended sessions.
