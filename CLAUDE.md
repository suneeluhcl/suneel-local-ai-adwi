# Adwi — Claude Session Orientation

> **Read this first** if you are a Claude session (or any AI model) starting work in this repo.
> This file is the fastest path from a cold start to productive contributions.

---

## What this repo is

Adwi is a local AI operating system running on an Apple Silicon Mac. It is not a library or API — it is a personal AI assistant that operates as a terminal REPL and a set of daemon services. The operator is Suneel Bikkasani.

**Entry point:** `adwi/bin/adwi` → `python3 adwi/adwi_cli.py`

**Primary model:** `adwi:latest` (qwen3:30b via Ollama, 131K context, 64 GB RAM)

**NLU classifier:** `llama3.1:8b` — classifies every natural-language input into one of 115 intent classes before dispatch.

---

## Before touching any file, read these

| File | Why |
|------|-----|
| `README.md` §5 | Security invariants and hard-blocked paths — never bypass these |
| `adwi/path_validator.py` | Deny-first path guard — understand before any file operation |
| `adwi/adwi_cli.py` lines 503–660 | `_REGEX_INTENTS` — NLU fast path, ordering is critical |
| `adwi/adwi_cli.py` lines 865–1020 | `_INTENT_SYSTEM` — LLM classification prompt |
| `adwi/logs/simeval/MASTER_REPORT_v2.md` | Refreshed 2026-06-20 (reliability-push session, 98.3% combined dedup). Current state is in the table below. |
| `adwi/docs/NLU_REPAIR_BACKLOG.md` | Prioritized fix list with exact code proposals |

---

## Current NLU quality (as of 2026-06-20)

| Eval | Scenarios | Pre-NHR | Stabilize sprint | CYCLE-5 | CYCLE-6 | CYCLE-7 | CYCLE-11 | REL-S | Total gain |
|------|-----------|---------|------------------|---------|---------|---------|----------|-------|------------|
| Large eval P1 | 1,834 | 78.0% | 92.6% | 96.3% | 96.7% | 95.7% | **98.6%** | **98.4%** | +20.4pp |
| Large eval P2 (weak-family targeting) | 570 | 68.6% | 88.8% | 97.0% | 98.2% | 97.0% | 98.1% | **98.2%** | +29.6pp |
| **Combined (dedup)** | **~2,283** | **75.8%** | **~91.7%** | **~96.5%** | **~97.0%** | **~95.8%** | 98.4% | **98.3%** | **+22.5pp** |

**Stop Condition B reached 2026-06-19: combined >98%. All 10 NHR items applied 2026-06-16. Sessions 2-4 applied 2026-06-16. Gmail burn-in + stabilization sprint applied 2026-06-17. CYCLE-5 (2026-06-17): 13 bare-command anchors, chat advisory fixes, status/advisory boundary, memory_scan/github_connected/web_search additions — synced to all 3 files. CYCLE-6 (2026-06-17): PermissionError guard before CYCLE-1, run-aider before self-heal, organize before chat, use_local/large_files/gmail_list_attachments/capabilities/trusted_roots/tool_roadmap/test_adwi targeted fixes — synced to all 3 files.**

Session-2 applied 11 regex patch groups (FIX-LF-001, FIX-OLD-001, FIX-DUP-001, FIX-ORG-002, FIX-CLEANUP-003, FIX-HEAL-001, FIX-BROWSE-001, FIX-WEB-001, FIX-ERR-002, FIX-EVAL-002, FIX-TEST-002, FIX-MEMSCAN-002) and 1 INTENT_SYSTEM clarification (FIX-BENCH-001).

Session-3 applied 9 regex patch groups (FIX-CLEAN-004, FIX-NOTES-001, FIX-STATUS-002, FIX-WHAT-002, FIX-WEB-002, FIX-OBS-002, FIX-NIGHT-001, FIX-EVAL-003, FIX-PATCH-002, FIX-RC-001, FIX-GMAIL-002, FIX-MEMST-001, FIX-MEMCTX-001, FIX-FR-001) and S3 fixes (FIX-S3-001 through FIX-S3-009) and 4 INTENT_SYSTEM clarifications.

Session-4 applied 8 false-positive hardening fixes. Gmail burn-in applied 12 FIX-STRESS patches + 4 FIX-STAGE3 patches. Stabilization sprint applied 9 regex fix groups + 4 _INTENT_SYSTEM additions + 6 test gap fixes. Total test suite after CYCLE-6: 897 tests.

**CYCLE-7 (2026-06-18): Assistant Upgrade Pack (Phase 5) NLU integration — 6 new intents (research, browser_delegate, daily_brief, tech_radar, memory_curate, assistant_upgrade_status) added to all 3 files. memory_curate regex fixed (word-boundary bug). rag_search word-boundary guard added (was matching "research" via "re**search**" substring). save-research-about regex added. INTENT_SYSTEM descriptions for all 6 new intents added to adwi_cli.py. 35 new eval scenarios added (26 P1 + 9 P2). P1 total: 1,834 scenarios. P2 total: 570 scenarios.**

**CYCLE-8–10 (2026-06-18/19): E2E auto-loop applied — 14 patches in cycle 1 (+0.7pp), direct application of FIX-042 through FIX-062 (voice_out order, browse INTENT_SYSTEM, web_search/rag_search INTENT_SYSTEM, capabilities/old_files/trusted_roots/test_adwi regexes, rag_search tightening, web_search changelog regex). P1 reached 98.20%.**

**CYCLE-11 (2026-06-19): FIX-063 (rag_search regex BEFORE obsidian_search for "search my notes" + typo-tolerant sea?r?a?ch), FIX-064a–e (research, patch_adwi, nightly_status, github_connected typo, duplicates typo). P1: 98.6%, P2: 97.7%, Combined: 98.3%.**

**Trust-baseline repair pass (2026-06-19): 3 NLU safety breaches fixed (~/Library/Passwords, /root/.bashrc, developer-mode social-engineering → __none__) + browse guard (fetch/summarize page). Patterns synced to P1+P2 harnesses. All env-path drift fixed (nightly.py, reason_engine.py, obsidian-bridge, adwi-sandbox, validate_adwi_env.py). reason_engine.py write guard expanded (12 entries). OpenTelemetry startup hang fixed (port-check gate). validate-docs paths fixed (now 20/20). MASTER_REPORT_v2.md regenerated from sessions large-20260619-103709 + large-p2-20260619-104828. P1: 98.6%, P2: 98.1%, Combined: 98.4%. Safety breaches: 0.**

**Reliability-push session (2026-06-20): 14 NLU regex fixes (FIX-REL-001 through FIX-REL-014) — disk_usage hogs/hasn't/capacity patterns, file_search locate/Dockerfile patterns, file_list list-contents patterns, backup_now commit-and-push patterns, use_local local-llm patterns, benchmark guard (FIX-REL-014) to prevent use_local false positive, fix_error StopIteration/UnicodeDecodeError/OverflowError/LookupError/ArithmeticError extensions. All 3 files synced. MASTER_REPORT_v2.md regenerated from sessions large-20260620-014026 + large-p2-20260620-020631. P1: 98.4%, P2: 98.2%, Combined: 98.3%. Safety breaches: 0. Regex fast-path: 67.8%. 481 NLU regression tests, 320 command registry tests.**

**Current baseline: 98.3% combined (dedup).** P1 failures (24): 10 disk_usage (LLM __none__ misroute), 5 chat bleed, scattered single-intent LLM variance. P2 failures (4): LLM variance only. upgrade_pack: 100% (35/35). Regex fast-path: 67.8%.

Changes are synchronized across all 3 files: `adwi/adwi_cli.py`, `adwi/logs/simeval/run_large_eval.py`, `adwi/logs/simeval/run_large_eval_p2.py`.

---

## Key invariants — never violate

1. **`_REGEX_INTENTS` ordering is load-bearing.** First match wins. New patterns must go before the intents they must beat.
2. **`BLOCKED_PATHS` is execution-layer safety.** NLU routing to `file_read` for a blocked path is not a breach — the gate stops execution. Do not weaken the gate.
3. **SimLab never auto-applies Tier C.** Safety/security changes always require human review.
4. **`secrets/` is gitignored entirely.** Never suggest committing anything from there.
5. **`adwi/config/.env` is gitignored.** `adwi/config/.env.example` is the commit-safe template.
6. **`adwi/memory.db` and `adwi/knowledge.db` are gitignored.** Regenerated on each machine.
7. **`aider` never touches secret files.** Validated before any file is passed to aider.

---

## File responsibility map

| File | Owns |
|------|------|
| `adwi/adwi_cli.py` | REPL, 184 commands, NLU pipeline (`_REGEX_INTENTS`, `_INTENT_SYSTEM`, dispatch), Phase 3 risk classifier, Phase 4 live self-heal |
| `adwi/reason_engine.py` | LangGraph Planner→Executor→Critic, permission gate, aider integration, AchievementLedger |
| `adwi/memory.py` | SQLite memory store, nomic-embed cosine search, Qdrant NLU fixtures, knowledge.db |
| `adwi/path_validator.py` | Deny-first path containment — blocks `~/.ssh`, `~/.aws`, `secrets/`, etc. |
| `adwi/nlu_fast_path.py` | Qdrant ≥0.88 score bypass — skips llama3.1:8b for high-confidence prompts |
| `adwi/nightly.py` | 10-step 2 AM maintenance loop (LaunchAgent) |
| `adwi/voice.py` | STT (faster-whisper) + TTS (piper-tts) |
| `adwi/backup.py` | Git backup orchestration |
| `adwi/simlab/` | Bounded continuous eval & self-improvement (11 modules) |
| `adwi/services/command-api/server.py` | Safe Command API :5055 (8 allowlisted routes for n8n/iPhone) |
| `adwi/services/mcp/obsidian-bridge/` | Vault HTTP CRUD API :5056 |
| `adwi/bin/` | 41 scripts (shell + Python helpers) |
| `adwi/logs/simeval/` | Large-scale eval artifacts (MASTER_REPORT_v2.md, fix_backlog_v2.json, jsonl results) |
| `adwi/config/.env` | [gitignored] API keys — never read by Claude, only loaded as env vars |
| `adwi/docs/` | Human + Claude onboarding documentation |

---

## How to make an NLU fix

1. Read `adwi/docs/NLU_REPAIR_BACKLOG.md` for the current NHR item list.
2. Identify which NHR item you are implementing.
3. Locate `_REGEX_INTENTS` in `adwi/adwi_cli.py` (line ~503). New patterns must go BEFORE any intent they should beat.
4. If adding an `_INTENT_SYSTEM` rule, locate the system prompt (line ~865) and add to the relevant intent's description.
5. After editing, run the fast syntax check: `python3 -m py_compile adwi/adwi_cli.py && echo OK`
6. Then run the eval harness: `python3 adwi/logs/simeval/run_large_eval.py --workers 5` (or a targeted P2 run)
7. Compare new pass rate to the **97.0% combined current baseline** (all NHR + CYCLE-5 + CYCLE-6 applied).
8. Mark the NHR item as applied in `adwi/docs/NLU_REPAIR_BACKLOG.md`.
9. If the session materially changes the pass rate, run `python3 adwi/logs/simeval/generate_master_report.py` with the new session paths to produce a fresh MASTER_REPORT. Update the table in this file.

---

## How to run the eval harness

```bash
# Fast syntax check first
python3 -m py_compile adwi/adwi_cli.py && echo "syntax OK"

# Requires Ollama running with llama3.1:8b
ollama list | grep llama3.1

# Full 1,444-scenario eval (takes ~20-30 min with 10 workers)
python3 adwi/logs/simeval/run_large_eval.py --workers 10

# Targeted P2 (446 scenarios, weak families only)
python3 adwi/logs/simeval/run_large_eval_p2.py --workers 10

# Combined analysis report
python3 adwi/logs/simeval/generate_master_report.py \
    adwi/logs/simeval/large-<date>-<time> \
    adwi/logs/simeval/large-p2-<date>-<time>
```

Results land in `adwi/logs/simeval/<session-dir>/results.jsonl`. The eval harness is standalone — it does not import `adwi_cli.py` and does not touch production data.

---

## What NOT to do

- Do not weaken `BLOCKED_PATHS`, `PathValidator`, or the `REVIEW-REQUIRED` tier in the risk classifier.
- Do not auto-commit or auto-push. Backup is triggered by `adwi/bin/adwi-git-backup` (runs every 30 min via LaunchAgent).
- Do not change the SimLab golden baseline (`adwi/simlab/golden_baseline.jsonl`) — it is immutable except via explicit human commit.
- Do not suggest checking in `adwi/config/.env`, any file from `secrets/`, or any `*token*` file.
- Do not import production `adwi_cli.py` from within an eval script — standalone eval harnesses only.
- Do not `rm -rf` or destructively modify `adwi/logs/` — it contains the eval evidence chain.

---

## How to bootstrap on a new machine

See `adwi/docs/SETUP_NEW_MACHINE.md` for the full guide.
Quick validation: `python3 adwi/scripts/validate_adwi_env.py`

---

## Repair log conventions

After making any change:
1. Update `adwi/notes/adwi-mistakes-and-fixes.md` if you fixed a bug.
2. Update `adwi/docs/NLU_REPAIR_BACKLOG.md` if you applied an NHR item.
3. Do NOT create loose analysis files in the root — put them in `adwi/docs/` (persistent) or `adwi/logs/simeval/` (eval artifacts).
