---
type: guide
status: active
tags: [obsidian, planning, daily-plan, workflow]
updated: 2026-06-22
---

# Planning Workflow

How to turn your captured items and weekly review into a concrete daily plan.

---

## The Full Loop

```
Capture → Review → Plan → Execute
(daily)   (weekly) (daily)  (you)
```

1. **Capture** with `/obsidian-capture <type> <text>` — ideas, tasks, decisions, bugs go into daily notes.
2. **Review** with `/obsidian-review` — see what accumulated over the last 7 days.
3. **Plan** with `/obsidian-plan` — generate today's focused action list from those captures.
4. **Execute** — the plan lives in today's daily note as `ADWI:DAILY-PLAN`. Open it in Obsidian and work from it.

---

## Commands

### `/obsidian-plan [days]`

```bash
/obsidian-plan        # plan from last 7 days
/obsidian-plan 14     # plan from last 14 days
```

Reads last N days of captures and writes a structured `ADWI:DAILY-PLAN` block into today's daily note.

**No LLM required** — the plan is built deterministically from your captures.

**Plan sections:**

| Section | Source |
|---------|--------|
| Top Focus | `## Current Focus` entries from last 2 days |
| Carryover Tasks | `## Current Focus` entries older than 2 days |
| Decisions to Remember | `## Decisions` entries |
| Ideas Worth Promoting | `## Ideas` entries |
| Bugs / Fixes to Follow Up | `## Bugs / Fixes` entries |
| Pending Approval | `## Pending Approval` entries |

Each section is deduplicated (same text at different times = one entry) and capped at 5 items.

**Re-running** on the same day updates the `ADWI:DAILY-PLAN` block in-place. Manual content in your daily note is never touched.

---

### `/obsidian-plan-clear`

```bash
/obsidian-plan-clear
```

Blanks the `ADWI:DAILY-PLAN` block body in today's note (sets body to empty). After clearing, `/daily-brief` will no longer show a plan pointer and `read_daily_plan()` returns `None`.

- Only the generated plan block is affected — manual sections and all other blocks (`ADWI:DAILY-SUMMARY`, `ADWI:DAILY-BRIEF`) are preserved.
- If no daily note or no plan block exists today, the command is a safe no-op.

---

## Where the Plan Lives

The plan is written to today's daily note as a generated marker block:

```
obsidian-vault/daily-notes/YYYY-MM-DD.md
```

```markdown
<!-- ADWI:DAILY-PLAN:START -->
## Daily Plan
*Generated 2026-06-22 — last 7 days of captures*

### Top Focus

- 14:00 — finish the NLU audit  *(from 2026-06-21)*

### Decisions to Remember

- 11:30 — use stdlib-only in bridge  *(from 2026-06-20)*
<!-- ADWI:DAILY-PLAN:END -->
```

---

## Daily Brief Integration

When a daily plan exists, `/daily-brief` will show a pointer line:

```
→ Today's plan exists in daily-notes/YYYY-MM-DD.md (ADWI:DAILY-PLAN)
```

This keeps the brief short — the plan itself is the detail.

---

## Typical Daily Session (5 min)

```bash
# Morning: generate plan from last week's captures
/obsidian-plan 7

# Evening: add what came up today
/obsidian-capture decision switched to async approach for the bridge
/obsidian-capture bug rate-limiter trips on batch gmail fetch

# Weekly: review + promote
/obsidian-review 7
/obsidian-review-save 7
/obsidian-promote-idea Rate Limiter Fix -- rewrite batch gmail fetch to respect per-minute limits
```

---

## Related Notes

- [[knowledge/Capture Workflow]]
- [[knowledge/Review Workflow]]
- [[knowledge/Obsidian Maintenance]]
- [[Adwi Home]]
