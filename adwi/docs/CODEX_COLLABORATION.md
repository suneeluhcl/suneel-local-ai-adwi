# Claude↔Codex Collaboration — Operator Guide

**Setup status:** Live as of 2026-06-21  
**Architecture:** Claude Code primary · Codex reviewer-only via MCP · structured artifacts  
**No manual copy/paste required.**

---

## How it works

Codex is already connected to Claude Code via MCP (`codex mcp-server`, stdio, global config).
Claude can call Codex directly during any session using the `codex-advisor` skill.
Codex always runs with `sandbox: read-only` and `approval-policy: never` — read-only inspection only; no writes, no escalation, no destructive commands.

```
You (operator)
    │
    ▼
Claude Code ──► /codex-advisor skill
                    │  gathers context (diff, baseline, questions)
                    │  calls mcp__codex__codex (read-only)
                    │  parses severity-ranked findings
                    ▼
            adwi/notes/codex-reviews/<timestamp>-<topic>.md
                    │
                    ▼
            Claude surfaces: Blocker/Major count + Highest-Value Next Action
```

---

## When to run `/codex-advisor`

| Trigger | When | What to ask |
|---------|------|-------------|
| `design-review` | Before starting a complex feature or refactor | "Is this architecture safe?" / "What am I missing?" |
| `session-end` | After touching high-risk files (adwi_cli.py, PathValidator, simlab/, services/) | "Are there any safety regressions or missing tests?" |
| `eval-drop` | After an NLU eval drops unexpectedly | "What could cause this? What should I check first?" |
| `test-failure` | After a test suite fails in an unexpected way | "Is this a real regression or a test design issue?" |
| `prompt-engineering` | Before writing a complex LLM prompt or INTENT_SYSTEM entry | "How would you frame this intent boundary more precisely?" |
| `manual` | Any time you want a second opinion | Anything |

The Stop hook will remind you automatically when the session has >5 non-trivial file changes or any high-risk file change.

---

## Daily workflow

### Scenario A: End of a productive session

1. Run `/adwi-session-end` as usual.
2. Step 6 of that skill checks if high-risk files changed.
3. If yes → run `/codex-advisor` (trigger: `session-end`).
4. Review the artifact in `adwi/notes/codex-reviews/`.
5. Fix any Blocker/Major findings before committing.

### Scenario B: Before a tricky design decision

```
"I want to migrate the elif dispatch chain to CommandRegistry for /run-python.
Let me get a Codex second-opinion first."
```

→ Invoke `/codex-advisor` with trigger: `design-review`.
→ Ask: "Is /run-python safe to migrate to CommandRegistry? What are the risks?"

### Scenario C: NLU eval drops after a regex change

→ Invoke `/codex-advisor` with trigger: `eval-drop`.
→ Include the diff of the regex change and the eval score before/after.
→ Ask: "What could cause this drop? What ordering invariants might I have broken?"

---

## Artifact location

All Codex reviews are saved to:
```
adwi/notes/codex-reviews/YYYYMMDD-HHMMSS-<topic>.md
```

Each artifact has:
- Front matter: created, topic, trigger, branch, NLU baseline, status
- Review brief: what was asked and why
- Findings table: Severity | Finding | Evidence | Confidence | Next Action | Status
- Highest-Value Next Action
- Reusable Prompt for next session
- Claude Resolution Notes (fill in as findings are acted on)

Update the `Status` column in the findings table as you resolve findings (`open` → `accepted` / `rejected` / `deferred`).

---

## Safety boundaries (v1 hard limits)

| What Codex can do | What Codex cannot do |
|------------------|---------------------|
| Read file paths and diffs in the brief Claude sends | Write any file |
| Return severity-ranked findings and recommendations | Write files, run destructive/approval-requiring commands |
| Suggest prompt improvements | Call other MCP tools |
| Critique architecture decisions | Access secrets, tokens, or .env values |
| Ask clarifying questions | Trigger further agent chains |

These limits are enforced by:
- `sandbox: read-only` on every `mcp__codex__codex` call
- `approval-policy: never` (no shell commands run)
- Claude never forwards credential-bearing content to Codex

---

## v1 limits (what stays manual)

- All `/codex-advisor` invocations require explicit Claude invocation during a session
- Claude always reviews Codex findings before acting on them
- Codex does not have repo access between sessions (no persistent state)
- The Stop hook only suggests — it does not auto-invoke Codex

---

## Future upgrades after v1

1. **Artifact index** (`adwi/notes/codex-reviews/INDEX.md`) — searchable log of all reviews with status
2. **Auto-brief generation** — a bin script that pre-generates the brief JSON so Claude only has to fill in questions
3. **Pattern library** — reusable "prompt for next session" entries promoted to `.claude/skills/`
4. **`/adwi-session-end` integration** — fully automated Codex step when high-risk files change (currently a manual step in the checklist)
