# Adwi Operator Handbook

> Concise daily-ops reference for Suneel Bikkasani.
> For cold-start model orientation see `docs/LLM_SYSTEM_PRIMING.md`.
> For full architecture see `README.md`.

---

## What is Adwi

A local AI operating system running on an Apple M4 Max Mac. It is a terminal REPL + a set of background daemon services. It is not a library or API. It talks to local Ollama models, your filesystem, Gmail, Home Assistant, Obsidian, GitHub, and the web.

```
bin/adwi          ← interactive REPL (type or slash-command)
bin/status-ai     ← quick health check for all services
```

---

## Daily startup (if any service is down)

```bash
# 1. Docker services (Open WebUI, n8n, SearXNG, monitoring stack)
cd ~/SuneelWorkSpace/adwi/infra/docker && docker compose up -d

# 2. Qdrant (Docker container started by LaunchAgent at login)
docker start suneel-qdrant

# 3. Obsidian Bridge + Safe Command API
bin/start-obsidian-bridge && bin/start-command-api

# 4. Arize Phoenix (OTel observability)
bin/start-phoenix

# 5. Start Adwi REPL
bin/adwi
```

LaunchAgents that auto-start at login: `adwi-git-backup` (30 min), `adwi-nightly` (2 AM), `adwi-scheduled-send` (2 min), `phoenix`, `obsidian-bridge`, `openwebui-knowledge-watcher`, `qdrant`.

---

## Health check

```bash
bin/status-ai           # all-in-one service status
bin/validate-docs       # docs consistency vs code (should be 0 FAIL)
python3 adwi/scripts/validate_adwi_env.py   # full pre-flight: Python, venv, Ollama, Docker, ports, secrets, Telegram config
```

Check Ollama models:
```bash
ollama list | grep -E "adwi|llama3|qwen|minicpm|nomic"
```

Expected: `adwi:latest` (18.6 GB), `llama3.1:8b` (4.9 GB), `qwen3:0.6b` (~400 MB), `minicpm-v:latest` (~5 GB), `nomic-embed-text` (~274 MB).

`validate_adwi_env.py` covers 17 checks: Python version, venv, core file presence, syntax, config/.env keys, ADWI_LOCAL_SECRET, Ollama (both models), Docker services, Obsidian bridge, SearXNG, Qdrant, Safe Command API auth enforcement + loopback-only binding, Telegram bridge config, bin/adwi in PATH, LaunchAgents, .gitignore safety, eval artifacts. Run it on any new machine or after a service disruption.

---

## Port map (quick reference)

| Port  | Service          | Layer              |
|-------|------------------|--------------------|
| :3000 | Open WebUI       | Docker             |
| :5055 | Safe Command API | Host               |
| :5056 | Obsidian Bridge  | Host (LaunchAgent) |
| :5678 | n8n              | Docker             |
| :6006 | Arize Phoenix    | Host (LaunchAgent) |
| :6333 | Qdrant           | Docker (LaunchAgent start) |
| :8123 | Home Assistant   | Docker             |
| :8888 | SearXNG          | Docker             |
| :11434| Ollama           | Host (brew)        |

---

## Common everyday commands

```
/status            Check all services + model health
/disk              Disk usage overview
/large-files       Find files eating space
/cleanup           Remove junk
/self-heal         Auto-diagnose + fix common issues
/backup-now        Trigger immediate git backup
/backup-status     Show last backup time
/nightly-run       Run the 2 AM maintenance cycle now
/memory-scan       Search semantic memory
/web-search <q>    Private web search via SearXNG
/github            Open GitHub project status
```

Gmail:
```
/inbox             Show unread count + summary
/gmail-read        Read recent emails
/gmail-compose     Compose a new email
/gmail-drafts      Manage drafts
/gmail-scheduled   Show scheduled-to-send queue
/gmail-triage      AI-powered inbox triage
```

---

## NLU — how natural language works

Every non-slash input goes through:
1. Regex fast-path (`_REGEX_INTENTS`) — 0 ms, no LLM
2. Qdrant few-shot lookup — top-3 of 96 fixtures injected into context
3. `llama3.1:8b` classification → intent + arguments JSON
4. Fallback: `qwen3:0.6b` if step 3 fails

Current pass rate: **98.3% combined** (P1: 98.4%, P2: 98.2%). Stop Condition B met 2026-06-19.

---

## Safety model

**Hard blocks (no prompt):** `secrets/`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, `/etc`, `/System`, `git push --force`, `DROP TABLE`, payment keywords.

**Review gate (Phase 2 LangGraph):** `git commit`, `git push`, `docker compose down`, `rm -r`, `chmod`, any `file_write` or `obsidian_write`.

**Safe:** Everything else — simple `Run this? (y/n)`.

---

## NLU repair workflow

```bash
# 1. Check syntax
python3 -m py_compile adwi/adwi_cli.py && echo OK

# 2. Edit _REGEX_INTENTS in adwi/adwi_cli.py (new patterns BEFORE the intents they beat)

# 3. Fast check (481 regex unit tests, ~5s)
python3 -m unittest adwi/simlab/tests/test_nlu_regex.py

# 4. Full eval P1 (requires Ollama + llama3.1:8b, ~30 min)
python3 adwi/logs/simeval/run_large_eval.py --workers 3

# 5. P2 targeted eval (weak families, ~10 min) — run AFTER P1, not in parallel
python3 adwi/logs/simeval/run_large_eval_p2.py --workers 3
```

Sync changes to all 3 files: `adwi/adwi_cli.py`, `logs/simeval/run_large_eval.py`, `logs/simeval/run_large_eval_p2.py`.

---

## Documentation maintenance

```bash
# Regenerate README AUTO: sections from live sources
bin/auto-update-readme --force

# Regenerate system_manifest.json
bin/generate-manifest

# Check docs vs code consistency
bin/validate-docs
```

Auto-update-readme runs automatically before every git backup (`adwi/backup.py`).

---

## Key invariants — never violate

1. `_REGEX_INTENTS` ordering is load-bearing. First match wins.
2. Never weaken `BLOCKED_PATHS`, `PathValidator`, or the `REVIEW-REQUIRED` risk tier.
3. SimLab never auto-applies Tier C (safety/security changes require human review).
4. Never commit `secrets/`, `config/.env`, `*token*`, `*.key`, or `adwi/memory.db`.
5. Never import `adwi_cli.py` from eval scripts — standalone harnesses only.
6. Do not `rm -rf logs/` — it is the eval evidence chain.

---

## Claude↔Codex collaboration

Codex is connected as a read-only reviewer via MCP (globally configured in Claude Code).

**To get a second opinion from Codex during a Claude Code session:**
```
/codex-advisor
```
This skill gathers context (git diff, NLU baseline, open issues), calls Codex with `sandbox: read-only`, and saves a severity-ranked review artifact to `adwi/notes/codex-reviews/`.

**When to use it:**
- Before a difficult design decision (trigger: `design-review`)
- At session end after touching high-risk files (trigger: `session-end`) — `adwi-session-end` skill Step 6 will remind you
- After an NLU eval drop (trigger: `eval-drop`)
- After an unexpected test failure (trigger: `test-failure`)

The Stop hook in `.claude/settings.local.json` automatically suggests `/codex-advisor` when the session changes more than 5 non-trivial files or any high-risk file (adwi_cli.py, path_validator.py, services/, etc.).

Review artifacts are saved to `adwi/notes/codex-reviews/` with front matter, a findings table (Severity | Finding | Evidence | Confidence | Next Action | Status), and a reusable prompt for the next session.

Full details: `docs/CODEX_COLLABORATION.md`.

---

## Deeper docs

| File | Purpose |
|------|---------|
| `README.md` | Full architecture blueprint |
| `CLAUDE.md` | Claude/AI session orientation |
| `docs/LLM_SYSTEM_PRIMING.md` | Compact external-model priming |
| `docs/SETUP_NEW_MACHINE.md` | Bootstrap on a new Mac |
| `docs/EVAL_GUIDE.md` | Eval harness guide |
| `docs/NLU_REPAIR_BACKLOG.md` | NLU repair history |
| `docs/CODEX_COLLABORATION.md` | Claude↔Codex second-opinion workflow |
| `docs/SINGLE_SOURCE_OF_TRUTH_DESIGN.md` | Doc architecture |
| `adwi/system_manifest.json` | Machine-readable ground truth |
| `logs/simeval/MASTER_REPORT_v2.md` | NLU eval report (note: stale — current baseline in CLAUDE.md) |
| `notes/adwi-mistakes-and-fixes.md` | Bug + fix history |
