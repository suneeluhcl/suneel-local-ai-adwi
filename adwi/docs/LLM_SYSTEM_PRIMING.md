# Adwi — Strict External-Model Priming File

> **PURPOSE:** Optimized for cold-start ingestion by Claude, Gemini, Copilot, GPT-4, or any LLM
> reading this for the first time. Minimal ambiguity. Current-state only. No historical narrative.
>
> **LAST VERIFIED:** 2026-06-21 against live code, config, and Qdrant.
>
> **GROUND TRUTH PRECEDENCE:** code > config > generator output > this file > README prose

---

## EXTERNAL MODEL OPERATING CONTRACT

This is what you are authorized to do when operating this system. Read it before touching any file.

### You MAY

| Action | Condition |
|--------|-----------|
| Read any file not on the BLOCKED list | PathValidator will enforce; trust it |
| Add or tighten regex patterns in `_REGEX_INTENTS` | Must be ordered correctly (first-match wins); must sync to all 3 files |
| Add new `_INTENT_SYSTEM` descriptions | Stay within the existing JSON schema; no new required fields |
| Add tests to `test_nlu_regex.py` or `test_command_registry.py` | Existing tests must not be removed or weakened |
| Migrate command handlers to `adwi/commands/` via `CommandRegistry` | Only if the command does **not** require interactive human confirmation |
| Run `py_compile`, `unittest`, or the eval harness | These are read-only verification passes |
| Generate or update reports in `adwi/logs/simeval/` | Eval artifacts are safe to write; never delete |
| Update `CLAUDE.md` after a session materially changes eval baseline | Required after any cycle that changes the combined pass rate |
| Update this file (`LLM_SYSTEM_PRIMING.md`) after values change | Keep LAST VERIFIED current |

### You MUST NOT

| Prohibited action | Why |
|-------------------|-----|
| Read, print, or modify anything in `secrets/`, `config/.env`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, `~/Library/Keychains`, `~/Library/Passwords`, `/etc`, `/private`, `/System` | Hard-blocked; never an exception |
| Weaken `PathValidator`, `BLOCKED_PATHS`, or any blocked-root list | Security boundary |
| Auto-apply any safety/security change | SimLab Tier C: human-review-only |
| Register `/notify`, `/e2e-auto-loop`, `/run-python`, `/run-bash`, `/implement-idea`, or any command requiring interactive confirmation into `CommandRegistry` | Bypasses the confirmation gate |
| Weaken Gmail preview→confirm, explicit-send, or undo flows | Mutation safety |
| Send real emails, push real notifications, or mutate the live mailbox unattended | Real-world side effects |
| Commit or push without explicit instruction | Backup is triggered automatically by LaunchAgent |
| Delete files from `adwi/logs/` | Eval evidence chain |
| Import `adwi_cli.py` from within an eval harness | Standalone harnesses only |
| Apply a patch that drops the golden baseline below 100% | SimLab invariant; auto-rollback fires |

### Escalate to human (do not proceed alone)

- Any change to `PathValidator`, `BLOCKED_PATHS`, or the `REVIEW-REQUIRED` tier classifier
- Any change to Gmail send/archive/trash flows
- Any change that causes a SimLab golden baseline failure
- Any ambiguity about whether a command requires interactive confirmation

---

## IDENTITY

| Property | Value |
|----------|-------|
| System | Adwi — local AI operating system |
| Operator | Suneel Bikkasani |
| Hardware | Apple M4 Max · 64 GB unified RAM · macOS 15 (Darwin 25.x) |
| Repo root | `~/SuneelWorkSpace/` |
| Entry point | `bin/adwi` → `python3 adwi/adwi_cli.py` |
| Primary model | `adwi:latest` (qwen3:30b, 131K ctx, 18.6 GB) via Ollama |
| NLU classifier | `llama3.1:8b` |
| Python | 3.14.5 (`adwi/.venv` via uv) |

---

## SOURCE OF TRUTH MAP

When sources conflict, resolve by this table. The "Canonical for" column tells you which questions each source answers authoritatively.

| Source | Canonical for | Trust level | Freshness signal |
|--------|--------------|-------------|-----------------|
| `adwi/adwi_cli.py` (`_REGEX_INTENTS`, `_ALL_INTENTS`, `_INTENT_SYSTEM`) | NLU intents, regex order, LLM prompt | **Highest** | Always current |
| `adwi/path_validator.py` | Blocked paths, denied roots | **Highest** | Always current |
| `adwi/capabilities.json` | Registered capability names | High | Updated by `bin/auto-update-readme` |
| `adwi/commands/*.py` + `CommandRegistry` | Which commands are registry-dispatched | High | Always current |
| `local-ai-stack/docker-compose.yml` | Docker service definitions, internal ports | High | Always current |
| `~/Library/LaunchAgents/com.suneel.*.plist` | Agent schedules, actual launch config | High | Always current |
| `adwi/system_manifest.json` | Point-in-time snapshot of commands/models/ports | Medium | Run `bin/generate-manifest` if stale |
| `README.md` AUTO: sections | Command list, model roster, phase list, port map | Medium | Injected by `bin/auto-update-readme` on each backup |
| `CLAUDE.md` | NLU baseline, session history, invariants | Medium | Manually updated after each improvement session |
| `adwi/logs/simeval/MASTER_REPORT_v2.md` | Latest combined eval result (P1+P2 dedup) | Medium | Regenerated by `generate_master_report.py`; current as of 2026-06-20 (98.3%) |
| `README.md` static sections (§6, §7–§10) | Directory tree, architecture, eval history | Low | Manually maintained; may lag code by 1–2 sessions |
| `docs/LLM_SYSTEM_PRIMING.md` (this file) | Cold-start orientation, operating contract | Low | Updated after major system changes |

**Precedence shorthand:** runtime code > config files > generator output > README AUTO: > CLAUDE.md > README static > this file

---

## CURRENT SYSTEM STATE (authoritative values — 2026-06-20)

### Models

| Constant | Model ID | Role |
|----------|----------|------|
| `MODEL_MAIN` | `adwi:latest` | Primary reasoning (qwen3:30b base) |
| `MODEL_FAST` | `llama3.1:8b` | NLU intent classification |
| `MODEL_NLU_FALLBACK` | `qwen3:0.6b` | NLU fallback when llama3.1 unavailable |
| `MODEL_VISION` | `minicpm-v:latest` | Vision / image analysis |
| `MODEL_EMBED` | `nomic-embed-text` | Embeddings (768-dim, memory/RAG) |

### NLU Pipeline

- **Intent classes:** 115 (from `_ALL_INTENTS` in `adwi/adwi_cli.py`)
- **Qdrant fixtures:** 96 (live in `nlu_fixtures` collection at :6333)
- **Fast-path threshold:** Qdrant score ≥ 0.88 → skip llama3.1:8b entirely (~5 ms vs 43 ms)
- **Regex fast-path coverage:** 67.8% of inputs handled without LLM call
- **Current pass rate:** P1 98.4% · P2 98.2% · Combined **98.3%** · Safety breaches: 0 (Stop Condition B met 2026-06-19)

Pipeline stages (every natural-language input):
1. Regex pre-filter (`_REGEX_INTENTS`) — zero latency, 67.8% hit rate
2. Qdrant few-shot lookup — top-3 of 96 fixtures
3. `llama3.1:8b` with JSON schema → `{analysis, confidence, intent, arguments}`
4. Fallback: `qwen3:0.6b`

### Command Registry

- **Total commands:** 193 (extracted from `adwi/adwi_cli.py` + `adwi/capabilities.json`)
- **Registry-dispatched clusters:** Phases 7–23 (Gmail, Remote/HA, Diagnostics, Voice, Disk, System, Knowledge, Eval)
- **Source of truth:** `bin/auto-update-readme` extractor → `README.md AUTO:COMMANDS`

### Services and Ports

| Port | Service | Layer |
|------|---------|-------|
| :11434 | Ollama | Host (brew) |
| :3000 | Open WebUI | Docker |
| :5055 | Safe Command API | Host |
| :5056 | Obsidian Bridge | Host (LaunchAgent) |
| :5678 | n8n | Docker |
| :6006 | Arize Phoenix | Host (LaunchAgent) |
| :6333 | Qdrant | Docker container started by LaunchAgent |
| :8123 | Home Assistant | Docker |
| :8888 | SearXNG | Docker |
| :9090 | Prometheus | Docker |
| :3100 | Loki | Docker |
| :4000 | Grafana | Docker |

### LaunchAgents (auto-start at login)

| Agent | Schedule | Purpose |
|-------|----------|---------|
| `adwi-git-backup` | every 30 min | Git backup |
| `adwi-nightly` | 2:00 AM | Maintenance loop |
| `adwi-scheduled-send` | every 2 min | Gmail scheduled-send runner |
| `phoenix` | KeepAlive | OTel observability UI |
| `obsidian-bridge` | KeepAlive | Vault HTTP API |
| `openwebui-knowledge-watcher` | KeepAlive | Sync Obsidian → Open WebUI |
| `qdrant` | RunAtLoad | `docker start suneel-qdrant` |
| `caffeinate` | KeepAlive | Prevent sleep |

---

## HARD SAFETY INVARIANTS

These rules are absolute. No exception, no workaround, no human confirmation possible:

1. **`PathValidator` blocks** (deny-first, checked before any allowed root):
   `secrets/`, `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube`, `~/.config/gcloud`,
   `~/.npmrc`, `~/.netrc`, `~/Library/Keychains`, `~/Library/Passwords`,
   `/etc`, `/private`, `/System`, `/usr/lib`

2. **`_REGEX_INTENTS` ordering is load-bearing.** First match wins. Adding a pattern in the wrong position breaks routing for every intent that follows it.

3. **`SimLab Tier C` is never auto-applied.** Any change touching safety/security logic requires explicit human git commit.

4. **Never commit:** `secrets/`, `config/.env`, `**/*token*`, `**/*.key`, `**/gmail-token.json`, `adwi/memory.db`, `adwi/knowledge.db`, `adwi/.venv/`

5. **Eval scripts must never import `adwi_cli.py`** — standalone harnesses only.

6. **`logs/`** is the eval evidence chain — do not delete or truncate.

---

## DO / DON'T

Quick-reference for AI models and new contributors.

### DO

- **Syntax-check first:** `python3 -m py_compile adwi/adwi_cli.py && echo OK` before any NLU work
- **Sync all 3 files** for every `_REGEX_INTENTS` change: `adwi_cli.py` + `run_large_eval.py` + `run_large_eval_p2.py`
- **Insert regex patterns before the intent they must beat** — first match wins; wrong position breaks routing
- **Run `test_nlu_regex.py` after every regex change** — 626 tests, should be 0 failures, runs in < 1 s
- **Prefer narrow, targeted patches** — change one intent's patterns at a time, not the whole block
- **Use 3 workers for eval runs** (`--workers 3`) — 5 workers causes 50–70 LLM timeouts
- **Run P1 and P2 evals sequentially** — parallel runs overload Ollama by 3–8pp
- **Update `CLAUDE.md` after any session** that materially changes the combined pass rate
- **Update `docs/LLM_SYSTEM_PRIMING.md`** after major system changes (this file is the cold-start oracle)

### DON'T

- **Don't touch AUTO: sections in README.md manually** — run `bin/auto-update-readme` instead
- **Don't add `CommandRegistry` handlers for interactive commands** — `/notify`, `/run-python`, `/run-bash`, `/implement-idea`, `/e2e-auto-loop` must stay in the elif chain
- **Don't delete eval session directories** in `adwi/logs/simeval/` — evidence chain
- **Don't skip `PathValidator`** — not even via `reason_engine.py` or aider; the gate is always active
- **Don't use `import adwi_cli`** inside an eval harness — standalone only
- **Don't modify `golden_baseline.jsonl`** — human-only commit; SimLab rolls back on any golden failure
- **Don't reduce `_REGEX_INTENTS` strictness** to fix a failure — tighten or add, never loosen
- **Don't guess at stale values** — the CURRENT SYSTEM STATE section above is the authoritative snapshot; when in doubt, grep the code

---

## SAFE CHANGE WORKFLOW

Follow this sequence for every non-trivial change. Deviating from this order is the most common source of regression.

### For NLU regex changes (`_REGEX_INTENTS`)

```
1. Read the target intent block in adwi/adwi_cli.py (_REGEX_INTENTS, line ~503)
2. Draft the new pattern. Test it with re.search() in a Python REPL before adding.
3. Determine position: must go BEFORE any intent it should beat.
4. Add to adwi/adwi_cli.py.
5. python3 -m py_compile adwi/adwi_cli.py && echo OK
6. python3 -m unittest adwi/simlab/tests/test_nlu_regex.py   ← 0 failures required
7. Sync the identical pattern to run_large_eval.py and run_large_eval_p2.py.
8. (Optional) Run python3 adwi/logs/simeval/run_large_eval.py --workers 3
9. Add regression test(s) to test_nlu_regex.py covering the new pattern + negatives.
10. Update adwi/docs/NLU_REPAIR_BACKLOG.md if fixing a known item.
```

### For CommandRegistry handler migration

```
1. Confirm the command does NOT require interactive human confirmation.
   → If it does: stop. Leave it in the elif chain.
2. Write the handler function in the appropriate adwi/commands/<module>.py.
3. Register it: _cmd_registry.register("/command-name", handler_fn)
4. Add tests to adwi/tests/test_command_registry.py.
5. python3 -m unittest adwi/tests/test_command_registry.py   ← 0 failures required
6. Verify TestElifFallbackIntegrity and TestSafetyBoundaryRegistry still pass.
7. Do NOT remove the elif branch yet — leave it as a fallback.
```

### For any other code change

```
1. Read the target file first. Understand what invariants it maintains.
2. Make the smallest change that achieves the goal.
3. Verify: py_compile + relevant test suite.
4. If changing behavior: add or update a targeted test.
5. If changing eval-visible behavior: re-run affected eval harness.
6. Document the change in adwi/notes/adwi-mistakes-and-fixes.md if it fixes a bug.
```

### Never do these steps out of order

- Do not run evals before syncing all 3 files — results will reflect stale code.
- Do not commit before all tests pass — the pre-commit backup script runs regardless.
- Do not skip the syntax check — a SyntaxError in `adwi_cli.py` takes down the entire REPL.

---

## WHAT NOT TO ASSUME

If you are a cold-starting LLM, do NOT assume:

- `MASTER_REPORT_v2.md` is stale — it was regenerated 2026-06-20 and reflects **98.3% combined** (P1: 98.4%, P2: 98.2%). Use `CLAUDE.md` for the narrative; use the JSON summary files for machine-readable values.
- "97.0% combined" — that was Stop Condition A (2026-06-17). Stop Condition B (>98%) was met 2026-06-19. Current is **98.3%**.
- "62 intent classes" — that was the count when capabilities.json had 62 entries. `_ALL_INTENTS` now has **115** classes.
- "104-command registry" — was the Phase 5 count. Current count is **193**.
- "167 commands" — was the count before Phase 23 and recent additions. Current is **193**.
- "49-fixture nlu_fixtures" — was the Phase 7 initial count. Current live count is **96**.
- "121 commands" — was an old annotation in the directory tree. Current is **193**.
- "35 helper scripts" — was stale bin/ count. Current is **41**.
- "390 tests in test_nlu_regex.py" — was the pre-reliability-session count. Current is **626** tests (grew through autoresearch sessions adding coverage for all 115 intents).
- Docker SERVICES section ports were reliable before 2026-06-17 — a regex bug caused `:1` to appear for all ports; this is now fixed.
- README is fully auto-generated — only the `<!-- AUTO:... -->` sections are machine-maintained; §6 directory tree and narrative sections are manually maintained and may be slightly behind.
- The `CommandRegistry` replaces the elif chain — it does not. It is dispatch-first; unregistered commands still fall through to the elif chain. Interactive commands intentionally stay in the elif chain.

---

## CANONICAL FILES AND THEIR ROLES

| File | Role | Maintained by |
|------|------|--------------|
| `adwi/adwi_cli.py` | REPL, 193 commands, NLU pipeline (`_REGEX_INTENTS`, `_INTENT_SYSTEM`, dispatch) | Human + aider |
| `adwi/commands/*.py` | CommandRegistry handler modules (dispatch-first, Phases 7–23) | Human |
| `adwi/path_validator.py` | Security gate — blocked roots (deny-first) | Human |
| `adwi/capabilities.json` | Capability registry | `bin/auto-update-readme` |
| `adwi/system_manifest.json` | Machine-readable ground truth snapshot | `bin/generate-manifest` |
| `adwi/gmail_helper.py` | Gmail OAuth2 + all mutation handlers (preview→confirm model) | Human |
| `adwi/reason_engine.py` | LangGraph Planner→Executor→Critic, permission gate, aider integration | Human |
| `adwi/nlu_fast_path.py` | Qdrant ≥0.88 score bypass — skips llama3.1:8b | Human |
| `adwi/simlab/golden_baseline.jsonl` | Immutable 20-scenario baseline — human-only commit | Human |
| `local-ai-stack/docker-compose.yml` | Docker service definitions | Human |
| `~/Library/LaunchAgents/com.suneel.*.plist` | Launch agent schedules and startup config | Human |
| `README.md` | Architecture blueprint (AUTO: sections auto-injected; static sections may lag) | `bin/auto-update-readme` + Human |
| `CLAUDE.md` | AI session orientation + current NLU baseline + invariants | Human |
| `adwi/logs/simeval/MASTER_REPORT_v2.md` | Combined P1+P2 dedup eval report (current: 98.3%, 2026-06-20) | `generate_master_report.py` |
| `docs/LLM_SYSTEM_PRIMING.md` | This file — cold-start model priming + operating contract | Human (update after major changes) |
| `docs/OPERATOR_HANDBOOK.md` | Human operator daily-ops quick-reference | Human |
| `adwi/docs/NLU_REPAIR_BACKLOG.md` | Prioritized NLU fix list with exact code proposals | Human |
| `adwi/docs/CODEX_COLLABORATION.md` | Claude↔Codex collaboration guide — when to call `/codex-advisor`, safety boundaries, artifact format | Human |
| `.claude/skills/codex-advisor/SKILL.md` | Six-step skill for Codex second-opinion reviews (read-only, `sandbox: read-only`, structured artifact output) | Human |

---

## HOW TO REASON WHEN DOCS CONFLICT

```
Step 1: Check if the value is in an AUTO: section of README.md.
        → If yes: trust it (generated from live sources by bin/auto-update-readme).

Step 2: Check adwi/system_manifest.json (generated_at timestamp tells you freshness).
        → More recent than README? Trust manifest. Stale by >24h? Run bin/generate-manifest.

Step 3: Check adwi/adwi_cli.py or the relevant canonical source file directly.
        → This is always authoritative over any doc.

Step 4: If still ambiguous, grep the code and verify manually.
        → Document the conflict in docs/README_INCONSISTENCY_CHECKLIST.md.
```

---

## COLD-START CHECKLIST

Before making any change to NLU, commands, or infrastructure:

- [ ] Read `adwi/adwi_cli.py` lines ~503–660 (`_REGEX_INTENTS`) — ordering is critical; first match wins
- [ ] Read `adwi/adwi_cli.py` lines ~865–1020 (`_INTENT_SYSTEM`) — LLM classification prompt
- [ ] Read `adwi/path_validator.py` — never weaken the gate
- [ ] Run `python3 -m py_compile adwi/adwi_cli.py && echo OK` — syntax check first
- [ ] Run `python3 -m unittest adwi/simlab/tests/test_nlu_regex.py` — **626 tests**, should be 0 failures, runs in < 1 s
- [ ] Run `python3 -m unittest adwi/tests/test_command_registry.py` — **320 tests**, 0 failures
- [ ] Run `python3 bin/validate-docs` — 0 FAIL before and after your change
- [ ] Sync NLU changes to all 3 files: `adwi/adwi_cli.py`, `adwi/logs/simeval/run_large_eval.py`, `adwi/logs/simeval/run_large_eval_p2.py`

After significant changes:
- [ ] Run `bin/auto-update-readme --force` — regenerate README AUTO: sections
- [ ] Run `bin/generate-manifest` — update system_manifest.json
- [ ] Run `bin/validate-docs` — confirm 0 FAIL
- [ ] Run `python3 adwi/scripts/validate_adwi_env.py` — confirm Ollama models, services, secrets, and Telegram config are healthy
- [ ] Update `CLAUDE.md` if combined eval baseline changed
- [ ] Update LAST VERIFIED date at the top of this file

---

## SYMPTOM → FIRST CHECK

| Symptom | First check | Command |
|---------|-------------|---------|
| Adwi REPL hangs at startup | OTel port conflict (Phoenix :4317/:4318) | `lsof -i :4317` — kill or gate the Phoenix startup |
| `/doctor` fails with Ollama error | Ollama not running | `brew services start ollama` |
| NLU routes to wrong intent | Regex ordering issue or missing pattern | `python3 adwi/adwi_cli.py /route "<input>"` to see what fires |
| NLU routes correctly but handler errors | Handler in elif chain has a bug | Check `adwi/adwi_cli.py` handler code for the intent |
| CommandRegistry dispatch returns False for registered command | Intent name mismatch between `_REGEX_INTENTS` output and `register()` call | Grep for the slash-command name in `adwi/commands/*.py` |
| Eval score drops after a change | NLU harness not synced; or pattern in wrong order | Confirm all 3 files synced; run `test_nlu_regex.py` first |
| P2 eval shows 94% instead of ~98% | LLM timeout cascade from too many workers | Re-run with `--workers 3` sequentially (P1 first, then P2) |
| Gmail send fires without confirmation | Explicit-send model broken | Check `gmail_helper.py` — look for send call outside `_send_draft()` gate |
| `PathValidator` blocking a legitimate path | Path not in `allowed-read-roots.txt` | `/trust-root <path>` or manually append to `adwi/allowed-read-roots.txt` |
| Qdrant fast-path not firing | Qdrant container not running or collection empty | `docker start suneel-qdrant` then `python3 adwi/memory.py provision-nlu` |
| `test_nlu_regex.py` failure after regex add | Pattern added in wrong position, or missing negative | Check test failure message — it names the intent and input; fix ordering in all 3 files |
| `test_command_registry.py` failure | New command registered that should be ELIF_ONLY, or handler missing | Check `TestElifFallbackIntegrity` and `TestSafetyBoundaryRegistry` test output |
| Nightly log missing or empty | LaunchAgent unloaded or nightly.py crashed | `launchctl list | grep adwi-nightly`; check `/tmp/adwi-nightly-*.log` |
| Obsidian bridge not responding | Process died | `bin/start-obsidian-bridge`; check `lsof -i :5056` |
| Safe Command API returns 401 | `ADWI_LOCAL_SECRET` not set or mismatched in caller | Check `config/.env` has the key; check n8n workflow header |
| Memory search returns stale results | `memory.db` not indexed | `/memory-scan` in REPL or `echo "/memory-scan\n/exit" \| python3 adwi/adwi_cli.py` |
| `SyntaxError` after editing `adwi_cli.py` | Edit introduced a syntax error | `python3 -m py_compile adwi/adwi_cli.py` to pinpoint line |

---

## ARCHITECTURE IN COMPACT FORM

```
User input
  │
  ├── Slash command? ──────────────────────────────► Direct dispatch
  │
  ├── Regex match (_REGEX_INTENTS) ───────────────► Direct dispatch  (0 ms)
  │
  ├── Qdrant score ≥ 0.88 (nlu_fast_path.py) ──► Direct dispatch  (~5 ms)
  │
  └── llama3.1:8b classification (~43 ms)
        │
        └── JSON: {analysis, confidence, intent, arguments}
              │
              ├── File ops ──► PathValidator ──► BLOCKED / allowed
              ├── Git/system ─► Phase 2 LangGraph permission gate
              │                   Planner → Executor → Critic
              └── Safe ops ──► Direct execution
```

Nightly automation (2 AM via LaunchAgent):
```
nightly.py: cleanup → knowledge index → eval → backup → Obsidian daily note
```
