---
type: codex-review
created: 2026-06-21T23:05:50
topic: prompt-relay-design
trigger: design-review
branch: main
nlu_baseline: 98.3%
sandbox: read-only
approval_policy: never
status: resolved
---

# Codex Review: prompt-relay-design

## Review Brief
- Operator goal: Establish a standing workflow where operator gives Claude a rough prompt, Claude relays to Codex for prompt engineering, Codex returns a properly structured execution prompt, Claude acts on it.
- Files changed: none (pure workflow design)
- High-risk files: none
- Tests run: 481/481 NLU regression tests passing

## Questions Asked
1. Design the full relay template Claude should use when sending rough prompts to Codex for engineering.
2. What should Codex's output format look like so Claude can act without ambiguity?
3. New skill or extend codex-advisor?

## Codex Findings

| Severity | Finding | Evidence | Confidence | Next Action | Status |
|----------|---------|----------|------------|-------------|--------|
| Major | codex-advisor is too review-artifact oriented — blurs reviewer vs. executor roles if extended | SKILL.md:3 "Always produces severity-ranked artifact" | high | Create standalone prompt-relay skill | resolved |
| Major | Claude needs strict relay template separating raw intent from executable instructions, preserving Adwi invariants | codex-advisor invariant block at SKILL.md:52 | high | Adopt relay template below | resolved |
| Major | Codex output needs machine-scannable ACTION trigger before Claude proceeds | codex-advisor has no explicit execution trigger (SKILL.md:84) | high | Require ACTION: EXECUTE_ENGINEERED_PROMPT | resolved |
| Advisory | Standalone `.claude/skills/prompt-relay/SKILL.md`; codex-reviews/ artifact path is wrong for relay artifacts | SKILL.md:10 "Never writer. Never executor" | high | Keep codex-advisor unchanged | resolved |

## Highest-Value Next Action
Adopt standalone `prompt-relay` workflow with relay template and require Codex to return one explicit ACTION value before Claude proceeds.

## Reusable Prompt For Next Session
"Use the prompt-relay workflow: take my rough task, send it to Codex as a read-only prompt-engineering request using the Adwi constraints and safety invariants, then execute only if Codex returns `ACTION: EXECUTE_ENGINEERED_PROMPT`; otherwise ask me the requested clarification."

## Claude Resolution Notes
Implemented as `.claude/skills/prompt-relay/SKILL.md` with Codex-designed relay template and ACTION-gated execution. codex-advisor left unchanged.
