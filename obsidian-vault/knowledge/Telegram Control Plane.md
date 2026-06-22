---
type: reference
status: active
tags: [telegram, remote-control, bridge, commands]
updated: 2026-06-22
---

# Telegram Control Plane

Complete reference for the Adwi Telegram bridge — your remote command center for Adwi from anywhere.

---

## Architecture

```
iPhone / Any Telegram client
        │
        │  outbound HTTPS only (long-poll)
        ▼
api.telegram.org :443
        │
        ▼
telegram-bridge/bot.py
  ├── Sender allowlist (numeric UID only)
  ├── Command allowlist (TELEGRAM_COMMANDS dict)
  ├── Confirmation gate (token + TTL for mutations)
  ├── Job runner (background subprocess + log files)
  └── Safe Command API → :5055 (for read-only routes)
              │
              ▼
         adwi_cli.py / bin scripts
```

**No inbound port, no tunnel, no ngrok.** The bridge only makes outbound HTTPS calls to Telegram.

---

## Command Groups

### Status & Health (Safe API)

| Command | What it does |
|---------|-------------|
| `/status` | Adwi health — services, models, memory |
| `/doctor` | Full stack diagnostics |
| `/services` | Port-probe all Adwi services (Ollama, n8n, Qdrant, …) |
| `/obsidian` | Vault status + last nightly validation |
| `/ports` | All service ports with up/down |
| `/uptime` | Mac uptime + load average |
| `/version` | Current git commit + branch |
| `/eval-status` | NLU pass rate from MASTER_REPORT |
| `/nightly-status` | Last nightly run timestamp + outcome |
| `/disk` | Disk usage for key Adwi paths |
| `/models` | Available Ollama models |
| `/e2e-status` | E2E auto-loop status (read-only) |
| `/watcher-status` | OpenWebUI knowledge watcher |

### Git (read-only via Safe API)

| Command | What it does |
|---------|-------------|
| `/git` | Git status for all workspace repos |
| `/git-status` | Same (original name) |
| `/git_diff` | `git diff --stat HEAD` |
| `/git_log` | Last 15 commits one-liner |

### Tests (background jobs — locally handled)

| Command | What it does |
|---------|-------------|
| `/test_quick` | Syntax + telegram + remote_control tests |
| `/test_nlu` | Full NLU regex suite (481 tests) |
| `/test_obsidian` | Vault validator 8-check suite |
| `/test_all` | All tests discovered under `adwi/` |
| `/tests_status` | Show latest test job status + log tail |

### Learn & Capture (locally handled)

| Command | What it does |
|---------|-------------|
| `/capture <type> <text>` | Append to today's daily note. Types: `idea decision bug fix note approval` |
| `/idea <text>` | Shorthand — captures as idea |
| `/plan <text>` | Shorthand — captures as plan note |
| `/obsidian_review` | Start 7-day review job (background) |
| `/obsidian_plan` | Generate today's plan (background) |
| `/obsidian_validate` | Run 8-check vault validator (background) |
| `/memory_scan` | Recall recent memory entries |

### Repair with Confirmation Gate

1. `/repair_plan` — shows syntax check + dirty file count + generates token
2. `/repair_ok <token>` — validates token, starts `adwi-self-heal` background job

Token expires in **5 minutes**. Each token is single-use.

### Git Backup with Confirmation Gate

1. `/git_backup` — shows pending changes + generates token
2. `/backup_ok <token>` — validates token, starts `adwi-git-backup` background job

### Job Management

| Command | What it does |
|---------|-------------|
| `/jobs` | List 10 most recent background jobs |
| `/job <id>` | Show job status + last 30 log lines |
| `/cancel <id>` | Send SIGTERM to a running job |
| `/tests_status` | Shortcut: latest test job details |

### Daily Brief / Info

| Command | What it does |
|---------|-------------|
| `/brief` | AI-suggested next action |
| `/daily-brief` | Full formatted morning brief |
| `/config` | Env var names present (no values printed) |

### UX

| Command | What it does |
|---------|-------------|
| `/help` | Flat alphabetical command list |
| `/menu` | Grouped command reference |
| `/ping` | Bridge liveness check |

---

## Background Job Runner

Jobs land in `adwi/logs/telegram-jobs/`. State is persisted in `jobs.json`.

```
adwi/logs/telegram-jobs/
  jobs.json               ← job state (gitignored)
  test-quick-YYYYMMDD-HHmmss-XXXX.log   ← per-job log
  repair-YYYYMMDD-HHmmss-XXXX.log
  ...
```

Job lifecycle: `queued → running → succeeded / failed / cancelled`

Timeout per job: **5 minutes**. Cancelled via `/cancel <id>` (SIGTERM).

---

## Confirmation Gate

Mutating commands (repair, backup) use a two-step gate:

1. **Plan command** generates a token (8 hex chars) and shows what will run
2. **Confirm command** validates the token and fires the job
3. Token expires in **5 minutes**, single-use

Example:
```
/repair_plan
→ "Confirm: /repair_ok a1b2c3d4 (expires 5 min)"

/repair_ok a1b2c3d4
→ "Repair job started. ID: repair-20260622-101234-ab12"
/job repair-20260622-101234-ab12
→ shows log tail
```

---

## Security Properties

| Property | How enforced |
|---------|-------------|
| Sender allowlist | `TELEGRAM_ALLOWED_USER_ID` — single UID, unknown senders silently dropped |
| Command allowlist | `TELEGRAM_COMMANDS` dict — anything not in dict is rejected |
| No shell injection | All subprocess calls use list argv, never `shell=True` |
| Argument sanitization | Control chars stripped, length capped to 500 chars |
| Secret redaction | Bot token + KEY= patterns redacted before sending replies |
| Response cap | Replies truncated to 4000 chars |
| Mutation gate | Dangerous operations require confirmation token |
| Safe API auth | `X-Adwi-Secret` required on every Safe API call |
| No direct shell execution | Bridge cannot execute `/run-bash`, `/patch-adwi`, etc. |

---

## Setup

All config from `adwi/config/.env`:

```bash
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_ALLOWED_USER_ID=<your numeric user ID>
ADWI_LOCAL_SECRET=<shared secret for Safe Command API>
```

Start the bridge:
```bash
python3 adwi/services/telegram-bridge/bot.py
```

Or via LaunchAgent (see `adwi/docs/TELEGRAM_BRIDGE_SETUP.md`).

---

## Files

| File | Purpose |
|------|---------|
| `adwi/services/telegram-bridge/bot.py` | Main bridge + all command handlers |
| `adwi/services/telegram-bridge/job_runner.py` | Background job runner (stdlib-only) |
| `adwi/services/command-api/server.py` | Safe Command API (allowlisted routes) |
| `adwi/bin/adwi-services` | Service port health probe |
| `adwi/bin/adwi-git-diff` | Git diff stat |
| `adwi/bin/adwi-git-log` | Recent commits |
| `adwi/tests/test_telegram_bridge.py` | 97 safety + routing tests |
| `adwi/tests/test_remote_control_surface.py` | Structural invariant tests |
| `adwi/tests/test_telegram_upgrade.py` | 111 Wave 4 feature tests |
| `adwi/logs/telegram-jobs/` | Job state + logs (gitignored) |

---

## Testing

```bash
python3 -m unittest adwi.tests.test_telegram_bridge \
                    adwi.tests.test_remote_control_surface \
                    adwi.tests.test_telegram_upgrade
# Ran 208 tests — OK
```

---

## Related Notes

- [[knowledge/Automation Map]] — how commands flow through Adwi
- [[knowledge/System Map]] — service ports and data flows
- [[knowledge/Obsidian Operator Guide]] — Obsidian commands that can be triggered from Telegram
- [[Adwi Home]]
