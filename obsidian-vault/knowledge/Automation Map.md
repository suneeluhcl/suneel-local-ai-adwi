---
type: map-of-content
status: active
tags: [automation, flows, dispatch]
updated: 2026-06-21
---

# Automation Map

How a command or natural-language input flows through Adwi.

## Flow A — NLU Dispatch (natural language)

```
User types a sentence
    → Stage 0: YouTube URL / image path regex (0 ms)
→ Stage 1: _REGEX_INTENTS fast-path (67.8% of queries, <1 ms)
    → Stage 2: Qdrant few-shot injection (top-3 from nlu_fixtures, 768-dim)
→ Stage 3: llama3.1:8b JSON decode → intent + confidence + arguments
    → Stage 4: dispatch to handler
    → Stage 5: fallback qwen3:0.6b if llama offline
```

Key invariant: `_REGEX_INTENTS` ordering is load-bearing — first match wins.

## Flow B — `/reason` (LangGraph)

```
/reason "task"
    → PlannerAgent → JSON step array (max 8 steps)
    → For each step: classify_risk() → BLOCKED / REVIEW-REQUIRED / SAFE
    → REVIEW-REQUIRED: permission gate with WHY explanation
    → ExecutorAgent → shell / file_read / file_write / web_search / llm_reason
    → On error: _live_heal() → aider patch → pytest verify → retry
    → CriticAgent → PASS / RETRY (max 3) / FAIL
    → AchievementLedger.render()
```

## Flow C — Nightly Loop (2 AM)

```
LaunchAgent fires → adwi/nightly.py
    Step 1:  Service health check
    Step 2:  Log rotation + cleanup
    Step 3:  Skill discovery
    Step 4:  aider self-heal (snapshot → patch → rollback on fail)
    Step 5:  Eval runs
    Step 5b: System health (brew/npm/disk/docker)
    Step 5c: Web research
    Step 6:  Backup sync check
    Step 7:  /memory-scan
    Step 8:  Capability sync → capabilities.json
    Step 8b: Obsidian daily note (marker-replace, no duplicates)
    Step 9:  git commit all changes
    Step 10: Write morning_brief.md
```

## Flow D — Telegram Bridge (Wave 4, 41 commands)

```
/cmd on Telegram
    → sender allowlist (TELEGRAM_ALLOWED_USER_ID)
    → command allowlist (TELEGRAM_COMMANDS — 41 entries)
    ├── route = None (locally handled):
    │     /help /menu /ping → static reply
    │     /test_* /obsidian_* /memory_scan → job_runner.submit()
    │     /capture /idea /plan → _run_quick(adwi_cli.py …)
    │     /repair_plan → plan text + _make_token("repair")
    │     /repair_ok <token> → _consume_token() → job_runner.submit(adwi-self-heal)
    │     /git_backup → plan + _make_token("git_backup")
    │     /backup_ok <token> → _consume_token() → job_runner.submit(adwi-git-backup)
    │     /jobs /job /cancel → job_runner.status() / list_recent() / cancel()
    └── route = "/adwi-*" (Safe Command API):
          POST http://127.0.0.1:5055/<route> + X-Adwi-Secret
          → subprocess.run() → stdout/stderr
          → _redact() → _strip_ansi() → truncate 4000 chars → Telegram reply

Background job lifecycle:
    job_runner.submit(name, argv)
        → threading.Thread → subprocess.Popen → log file
        → state written to adwi/logs/telegram-jobs/jobs.json
        → job status: queued → running → succeeded / failed / cancelled
```

## Flow E — n8n / Safe Command API

```
Siri / n8n webhook → POST :5055/<route>
    → X-Adwi-Secret header check (401 if missing/wrong)
    → ALLOWED_COMMANDS lookup (26 routes)
    → subprocess.run() → JSON response
```

## CommandRegistry (dispatch-first pattern)

```
handle(line)
    → _cmd_registry.dispatch(line, {})   ← checks first
        match → execute handler → return True
        no match → return False
    → elif chain (legacy fallback for interactive commands)
```

Migrated clusters: Gmail (Ph 7,8,11,13,14,15,16B), Remote/HA (Ph 18), Diagnostics (Ph 23).
Interactive commands (e.g. `/run-python`, `/notify`, `/e2e-auto-loop`) intentionally stay in elif chain.

## Related Notes

- [[knowledge/System Map]]
- [[projects/Adwi]]
- [adwi/docs/COMMAND_REGISTRY_WIRING_PLAN.md](../../adwi/docs/COMMAND_REGISTRY_WIRING_PLAN.md)
- [adwi/docs/OPERATOR_HANDBOOK.md](../../adwi/docs/OPERATOR_HANDBOOK.md)

## Next Improvements

- [ ] Complete CommandRegistry migration for remaining elif-chain commands
- [ ] Add Telegram bridge as a proper LaunchAgent plist
- [ ] Wire `/daily-brief` nightly scheduling via n8n
