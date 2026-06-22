---
name: adwi-session-end
description: End-of-session wrap-up for Adwi development. Runs final checks, summarizes what changed, updates documentation, and prepares for backup. Run when winding down a development session.
---

You are running the Adwi end-of-session checklist. This ensures every session ends in a clean, documented state.

## End-of-session checklist

### 1. Final syntax check
```bash
python3 -m py_compile adwi/adwi_cli.py 2>&1 && echo "✓ CLI syntax OK"
```

### 2. What changed this session?
```bash
git diff --stat HEAD
```
Summarize the changes in one or two sentences for the user.

### 3. Eval state check
Ask: "Was an eval run this session?"
- If YES and the pass rate changed → update the table in `CLAUDE.md` with the new numbers. The table columns are: Eval | Scenarios | Pre-NHR | Stabilize sprint | CYCLE-5 | CYCLE-6 | (add new columns as needed) | Total gain.
- If a new improvement cycle was completed, update the "Current NLU quality" section header in CLAUDE.md.

### 4. Backlog and notes
- Were any NHR items applied? → Update `adwi/adwi/docs/NLU_REPAIR_BACKLOG.md`
- Were any bugs found or fixed? → Update `notes/adwi-mistakes-and-fixes.md`
- Do not create loose analysis files in the repo root (use `adwi/docs/` for persistent docs, `adwi/logs/simeval/` for eval artifacts)

### 5. Open items summary
Show any remaining open NHR items from `adwi/adwi/docs/NLU_REPAIR_BACKLOG.md` so the next session can pick up immediately.

### 6. Codex review (optional, recommended for non-trivial sessions)

Check if the session warrants a second-opinion review:
```bash
git diff --name-only HEAD | grep -cE 'adwi_cli\.py|path_validator\.py|reason_engine\.py|simlab/|services/|\.claude/|gmail_helper\.py|repair\.py'
```

- If result > 0 **or** more than 5 files changed: run `/codex-advisor` (trigger: `session-end`)
- If only docs, trace logs, daily briefs, or backup logs changed: skip Codex review

The `/codex-advisor` skill will produce a severity-ranked artifact in `adwi/notes/codex-reviews/`.
Any Blocker or Major finding should be resolved before committing.

### 7. Commit if needed
If there are uncommitted changes worth keeping, offer to run `/adwi-commit`.

### 8. Backup trigger
The git backup LaunchAgent runs every 30 minutes automatically. To trigger immediately:
```bash
bin/adwi-git-backup
```

## What NOT to do at session end
- Do not run P1 and P2 evals in parallel to "squeeze in" one more check
- Do not commit changes to `secrets/` or `config/.env`
- Do not commit `adwi/memory.db` or `adwi/knowledge.db`
- Do not leave the golden baseline (`adwi/simlab/golden_baseline.jsonl`) modified
