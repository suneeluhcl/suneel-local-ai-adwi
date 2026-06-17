# Adwi — Claude Session Orientation

> **Read this first** if you are a Claude session (or any AI model) starting work in this repo.
> This file is the fastest path from a cold start to productive contributions.

---

## What this repo is

Adwi is a local AI operating system running on an Apple Silicon Mac. It is not a library or API — it is a personal AI assistant that operates as a terminal REPL and a set of daemon services. The operator is Suneel Bikkasani.

**Entry point:** `bin/adwi` → `python3 adwi/adwi_cli.py`

**Primary model:** `adwi:latest` (qwen3:30b via Ollama, 131K context, 64 GB RAM)

**NLU classifier:** `llama3.1:8b` — classifies every natural-language input into one of 62 intent classes before dispatch.

---

## Before touching any file, read these

| File | Why |
|------|-----|
| `README.md` §5 | Security invariants and hard-blocked paths — never bypass these |
| `adwi/path_validator.py` | Deny-first path guard — understand before any file operation |
| `adwi/adwi_cli.py` lines 503–660 | `_REGEX_INTENTS` — NLU fast path, ordering is critical |
| `adwi/adwi_cli.py` lines 865–1020 | `_INTENT_SYSTEM` — LLM classification prompt |
| `logs/simeval/MASTER_REPORT_v2.md` | Current NLU quality state and 10 known repair items |
| `docs/NLU_REPAIR_BACKLOG.md` | Prioritized fix list with exact code proposals |

---

## Current NLU quality (as of 2026-06-17)

| Eval | Scenarios | Pre-NHR | Post-NHR (session 1) | Post-session-2 | Post-session-3 | Gmail burn-in | Total gain |
|------|-----------|---------|----------------------|----------------|----------------|---------------|------------|
| Large eval P1 | ~1,619 | 78.0% | 83.7% | 88.6% | 90.7% | **92.0%** | +14.0pp |
| Large eval P2 (weak-family targeting) | 561 | 68.6% | 77.6% | 81.4% | 83.9% | **87.2%** | +18.6pp |
| **Combined** | **~2,180** | **75.8%** | **82.1%** | **86.0%** | **89.0%** | **90.7%** | **+14.9pp** |

**All 10 NHR items (NHR-001 through NHR-010) applied 2026-06-16. 13 session-2 patches and 9 session-3 patches applied 2026-06-16. 8 session-4 code-review hardening fixes applied 2026-06-16. Gmail burn-in (Stages 1-3) applied 2026-06-17: 12 FIX-STRESS patterns (Phase B/C burn-in) + 4 FIX-STAGE3 patterns (Stage 3 repair).**

Session-2 applied 11 regex patch groups (FIX-LF-001, FIX-OLD-001, FIX-DUP-001, FIX-ORG-002, FIX-CLEANUP-003, FIX-HEAL-001, FIX-BROWSE-001, FIX-WEB-001, FIX-ERR-002, FIX-EVAL-002, FIX-TEST-002, FIX-MEMSCAN-002) and 1 INTENT_SYSTEM clarification (FIX-BENCH-001).

Session-3 applied 9 regex patch groups (FIX-CLEAN-004, FIX-NOTES-001, FIX-STATUS-002, FIX-WHAT-002, FIX-WEB-002, FIX-OBS-002, FIX-NIGHT-001, FIX-EVAL-003, FIX-PATCH-002, FIX-RC-001, FIX-GMAIL-002, FIX-MEMST-001, FIX-MEMCTX-001, FIX-FR-001) and S3 fixes (FIX-S3-001 through FIX-S3-009) and 4 INTENT_SYSTEM clarifications.

Session-4 applied 8 false-positive hardening fixes identified by post-session-3 code review: FIX-S3-002 gap tightened, FIX-S3-008 `different` removed, FIX-STATUS-002 broad line deleted, FIX-NIGHT-001 context tightened, FIX-S3-001 bare `tps` removed, FIX-S3-006 bare `kb` removed, FIX-MEMCTX-001 negative lookahead added, FIX-S3-004 duplicate typo removed.

Gmail burn-in (2026-06-17) applied 12 FIX-STRESS patches (schedule/send/compose/draft/attachment/inbox/mutation coverage) and 4 FIX-STAGE3 patches (open-latest-message→gmail_read, which-draft→gmail_list_drafts, send-an-email-to-X→gmail_compose, send-the-email→gmail_send_draft). 317-test Gmail stress suite added at `adwi/simlab/tests/`.

**Current baseline: 90.7% combined.** Remaining targets: `chat` bleed (~30 cases — advisory questions mislabeled), `__none__` (24 — irreducible safety blocks), `cleanup` (7 remaining), `organize` (4).

Changes are synchronized across all 3 files: `adwi/adwi_cli.py`, `logs/simeval/run_large_eval.py`, `logs/simeval/run_large_eval_p2.py`.

---

## Key invariants — never violate

1. **`_REGEX_INTENTS` ordering is load-bearing.** First match wins. New patterns must go before the intents they must beat.
2. **`BLOCKED_PATHS` is execution-layer safety.** NLU routing to `file_read` for a blocked path is not a breach — the gate stops execution. Do not weaken the gate.
3. **SimLab never auto-applies Tier C.** Safety/security changes always require human review.
4. **`secrets/` is gitignored entirely.** Never suggest committing anything from there.
5. **`config/.env` is gitignored.** `config/.env.example` is the commit-safe template.
6. **`adwi/memory.db` and `adwi/knowledge.db` are gitignored.** Regenerated on each machine.
7. **`aider` never touches secret files.** Validated before any file is passed to aider.

---

## File responsibility map

| File | Owns |
|------|------|
| `adwi/adwi_cli.py` | REPL, 121 commands, NLU pipeline (`_REGEX_INTENTS`, `_INTENT_SYSTEM`, dispatch), Phase 3 risk classifier, Phase 4 live self-heal |
| `adwi/reason_engine.py` | LangGraph Planner→Executor→Critic, permission gate, aider integration, AchievementLedger |
| `adwi/memory.py` | SQLite memory store, nomic-embed cosine search, Qdrant NLU fixtures, knowledge.db |
| `adwi/path_validator.py` | Deny-first path containment — blocks `~/.ssh`, `~/.aws`, `secrets/`, etc. |
| `adwi/nlu_fast_path.py` | Qdrant ≥0.88 score bypass — skips llama3.1:8b for high-confidence prompts |
| `adwi/nightly.py` | 10-step 2 AM maintenance loop (LaunchAgent) |
| `adwi/voice.py` | STT (faster-whisper) + TTS (piper-tts) |
| `adwi/backup.py` | Git backup orchestration |
| `adwi/simlab/` | Bounded continuous eval & self-improvement (11 modules) |
| `local-command-api/server.py` | Safe Command API :5055 (8 allowlisted routes for n8n/iPhone) |
| `mcp-servers/obsidian-bridge/` | Vault HTTP CRUD API :5056 |
| `bin/` | 35 shell helper scripts |
| `logs/simeval/` | Large-scale eval artifacts (MASTER_REPORT_v2.md, fix_backlog_v2.json, jsonl results) |
| `config/.env` | [gitignored] API keys — never read by Claude, only loaded as env vars |
| `docs/` | Human + Claude onboarding documentation |

---

## How to make an NLU fix

1. Read `docs/NLU_REPAIR_BACKLOG.md` for the current NHR item list.
2. Identify which NHR item you are implementing.
3. Locate `_REGEX_INTENTS` in `adwi/adwi_cli.py` (line ~503). New patterns must go BEFORE any intent they should beat.
4. If adding an `_INTENT_SYSTEM` rule, locate the system prompt (line ~865) and add to the relevant intent's description.
5. After editing, run the fast syntax check: `python3 -m py_compile adwi/adwi_cli.py && echo OK`
6. Then run the eval harness: `python3 logs/simeval/run_large_eval.py --workers 5` (or a targeted P2 run)
7. Compare new pass rate to the 82.1% combined baseline (post-NHR).
8. Mark the NHR item as applied in `docs/NLU_REPAIR_BACKLOG.md`.
9. Update `logs/simeval/MASTER_REPORT_v2.md` projected pass rate section if significantly changed.

---

## How to run the eval harness

```bash
# Fast syntax check first
python3 -m py_compile adwi/adwi_cli.py && echo "syntax OK"

# Requires Ollama running with llama3.1:8b
ollama list | grep llama3.1

# Full 1,444-scenario eval (takes ~20-30 min with 10 workers)
python3 logs/simeval/run_large_eval.py --workers 10

# Targeted P2 (446 scenarios, weak families only)
python3 logs/simeval/run_large_eval_p2.py --workers 10

# Combined analysis report
python3 logs/simeval/generate_master_report.py \
    logs/simeval/large-<date>-<time> \
    logs/simeval/large-p2-<date>-<time>
```

Results land in `logs/simeval/<session-dir>/results.jsonl`. The eval harness is standalone — it does not import `adwi_cli.py` and does not touch production data.

---

## What NOT to do

- Do not weaken `BLOCKED_PATHS`, `PathValidator`, or the `REVIEW-REQUIRED` tier in the risk classifier.
- Do not auto-commit or auto-push. Backup is triggered by `bin/adwi-git-backup` (runs every 30 min via LaunchAgent).
- Do not change the SimLab golden baseline (`adwi/simlab/golden_baseline.jsonl`) — it is immutable except via explicit human commit.
- Do not suggest checking in `config/.env`, any file from `secrets/`, or any `*token*` file.
- Do not import production `adwi_cli.py` from within an eval script — standalone eval harnesses only.
- Do not `rm -rf` or destructively modify `logs/` — it contains the eval evidence chain.

---

## How to bootstrap on a new machine

See `docs/SETUP_NEW_MACHINE.md` for the full guide.
Quick validation: `python3 scripts/validate_adwi_env.py`

---

## Repair log conventions

After making any change:
1. Update `notes/adwi-mistakes-and-fixes.md` if you fixed a bug.
2. Update `docs/NLU_REPAIR_BACKLOG.md` if you applied an NHR item.
3. Do NOT create loose analysis files in the root — put them in `docs/` (persistent) or `logs/simeval/` (eval artifacts).
