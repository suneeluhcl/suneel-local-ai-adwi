---
type: codex-review
created: 2026-06-21T11:39:53-05:00
topic: session-end-wave1-wave2
trigger: session-end
branch: main
nlu_baseline: 98.3%
sandbox: read-only
approval_policy: never
status: open
---

# Codex Review: Session-End Wave 1+2 — 2026-06-21

## Review Brief

- Operator goal: Multi-wave safe improvements — Codex↔Claude collaboration layer (skills, hooks, artifacts), `validate_adwi_env.py` `adwi:latest` check fix, hermetic tests for `chk_syntax()` and `chk_key_files()`, documentation sync (LLM_SYSTEM_PRIMING.md canonical files, adwi-mistakes-and-fixes.md, SETUP_NEW_MACHINE.md 89→96 fixture count, codex-reviews/INDEX.md)
- Files changed: 18 tracked modified + 7 new untracked (test_validate_env.py, CODEX_COLLABORATION.md, codex-advisor skill, settings.local.json, codex-reviews artifacts)
- High-risk files: `.claude/skills/adwi-session-end/SKILL.md`, `adwi/reason_engine.py`, `adwi/repair.py`, `adwi/services/telegram-bridge/bot.py`, `.claude/settings.local.json`
- Tests run: `test_validate_env.py` 42/42 PASS, `validate-docs` 25/25 PASS. NLU eval not re-run (no `_REGEX_INTENTS` changes)

## Questions Asked

1. Is the adwi-session-end skill Step 6 (conditional Codex invocation) loop-safe?
2. Is `test_alternative_binding_form_not_caught_by_static_check` (documentation test that passes when gap exists) clear enough or confusing?
3. Missing hermetic test cases for `chk_syntax()` / `chk_key_files()` that create false confidence?

## Codex Findings

| Severity | Finding | Evidence | Confidence | Next Action | Status |
|----------|---------|----------|------------|-------------|--------|
| Blocker | `.claude/settings.local.json` contains HA bearer tokens embedded in `allowedTools` curl commands (lines 84, 93, 99) | `settings.local.json:84,93,99` — `Authorization: Bearer ...` | high | File is globally gitignored (safe from commit). NEVER include settings.local.json content in Codex briefs. Operator: consider extracting token to env var or rotating if ever shared. | open |
| Major | `chk_safe_command_api()` static check only catches `host = "0.0.0.0"` literal; test locks in known gap as "acceptable" rather than as a regression guard | `validate_adwi_env.py:302`, `test_validate_env.py:263` | high | Strengthen static check to also catch `ThreadingHTTPServer(("0.0.0.0", ...))` form; invert the test so it fails if the gap is NOT caught | open |
| Minor | `chk_key_files()` has untested `relative_to()` failure path — ADWI outside WORKSPACE not covered | `validate_adwi_env.py:90`, `test_validate_env.py:TestKeyFiles` | med | Add hermetic test with `ADWI` outside `WORKSPACE`; decide whether to catch `ValueError` from `relative_to()` | open |
| Minor | `chk_syntax()` tests don't cover subprocess exceptions (`TimeoutExpired`, `OSError`) or verify call argv shape | `validate_adwi_env.py:109`, `test_validate_env.py:TestSyntaxCheck` | med | Add tests for `subprocess.run` raising `OSError`/`TimeoutExpired`; assert `sys.executable -m py_compile` call shape | open |
| Advisory | Codex loop is currently safe (skill is manual, Stop hook only suggests). Future "fully automated" language in CODEX_COLLABORATION.md could become unsafe if implemented without a "already-ran" sentinel | `CODEX_COLLABORATION.md:125`, `adwi-session-end SKILL.md:41` | high | If automation added later: include session sentinel, exclude `adwi/notes/codex-reviews/` from retrigger criteria | open |
| Advisory | CODEX_COLLABORATION.md says "cannot write files or run destructive/approval-requiring commands" — Codex can still run read-only inspection in its environment | `CODEX_COLLABORATION.md:13` | high | Clarify to "read-only inspection only; no writes, no escalation, no destructive commands" | accepted |

## Highest-Value Next Action

Fix `chk_safe_command_api()` bind detection and convert the "known gap" test into a failing regression guard; separately keep `.claude/settings.local.json` out of all tracked artifacts and Codex briefs (HA bearer token is embedded in `allowedTools` entries).

## Reusable Prompt For Next Session

"Review `validate_adwi_env.py::chk_safe_command_api()` and `adwi/tests/test_validate_env.py`. Strengthen public-interface bind detection for Safe Command API, including direct `ThreadingHTTPServer(("0.0.0.0", ...))`, host variable assignment, and equivalent single-quote forms. Convert the current documentation test into a regression test that fails on any public bind. Do not touch secrets or `.claude/settings.local.json` contents."

## Claude Resolution Notes

- Blocker (`settings.local.json`): File is globally gitignored at `/Users/MAC/.config/git/ignore` — NOT a commit risk. Content was NOT sent to Codex in this review brief. HA bearer token is in `allowedTools` curl allow-list entries. Operator should decide whether to extract token to env var or rotate. Mitigation in place: never include settings.local.json content in future Codex briefs.
- Advisory (CODEX_COLLABORATION.md wording): Updated table cell to "read-only inspection only; no writes, no escalation, no destructive commands" — accepted and applied.
- Major/Minor test gaps: Deferred to next human-attended session (low blast radius, no NLU or security files touched).
