# Telegram Command Reference — Adwi Bridge

**Source of truth:** `adwi/services/telegram-bridge/bot.py` → `TELEGRAM_COMMANDS`
**Safety model:** every command routes through Safe Command API (`:5055`) with `X-Adwi-Secret` auth,
or is handled locally by the bridge process itself (no API call).

---

## Quick Reference

| Command | Routes to | Description |
|---------|-----------|-------------|
| `/help` | local | List all available commands |
| `/ping` | local | Bridge health check — instant Pong reply |
| `/status` | `/adwi-status` | Adwi REPL `/status` output |
| `/doctor` | `/adwi-doctor` | Adwi REPL `/doctor` health check |
| `/brief` | `/adwi-brief` | What-next brief from Adwi AI |
| `/daily-brief` | `/adwi-daily-brief-n8n` | LLM-generated daily brief (JSON → formatted) ⚠ writes report file |
| `/config` | `/adwi-config-check` | Env var config status (names only, never values) |
| `/disk` | `/adwi-disk-summary` | Disk usage for key Adwi paths |
| `/eval-status` | `/adwi-eval-status` | NLU eval pass rate from MASTER_REPORT_v2 |
| `/git-status` | `/git-status-workspace` | `git status` + recent commits |
| `/models` | `/adwi-models` | Ollama model list |
| `/nightly-status` | `/adwi-nightly-status` | Last nightly run timestamp + outcome |
| `/ports` | `/adwi-ports` | Adwi service ports + live probe status |
| `/uptime` | `/adwi-uptime` | Mac uptime + load average |
| `/version` | `/adwi-version` | Current git commit, branch, date |
| `/watcher-status` | `/adwi-watcher-status` | OpenWebUI knowledge watcher status |
| `/e2e-status` | `/adwi-e2e-auto-loop-status` | E2E auto-loop running/idle + last result |

---

## Safety Boundaries

Commands that are explicitly **never** exposed via Telegram (would require direct shell access or
cause irreversible side effects):

| Rejected command | Why |
|-----------------|-----|
| `/run-bash`, `/run-python` | Arbitrary shell execution |
| `/patch-adwi`, `/self-heal` | Code mutation |
| `/e2e-auto-loop` (start) | Starts background evaluation loop |
| `/nightly-run` | Triggers 2 AM maintenance loop |
| `/gmail-send`, `/gmail-confirm` | Email mutation (preview→confirm gate) |
| `/git-commit`, `/git-push` | Repository mutation |
| `/notify` | Interactive confirmation required |
| `/implement-idea` | AI code generation with writes |
| `/memory-scan`, `/file-write` | Local state mutation |

---

## Adding a New Command

1. Add a route to `ALLOWED_COMMANDS` in `adwi/services/command-api/server.py`
2. Add the mapping in `TELEGRAM_COMMANDS` in `adwi/services/telegram-bridge/bot.py`
3. Add tests in `adwi/tests/test_telegram_bridge.py`
4. The static safety test `TestSafeApiCoverage.test_all_telegram_routes_in_safe_api` will fail
   if the bot.py route is not in server.py — this is the drift guard
5. Update this file

**Hard rule:** never add commands that execute shell, mutate files, or bypass confirmation gates.

---

## Command Classification

| Class | Description | Examples |
|-------|-------------|---------|
| **local** | Handled by bridge; zero API calls; instant | `/help`, `/ping` |
| **read-only** | Reads state; no files written by the command | `/status`, `/doctor`, `/disk`, `/eval-status`, `/ports`, `/uptime`, `/version`, `/config`, `/models`, `/git-status`, `/watcher-status`, `/nightly-status`, `/e2e-status` |
| **generates-report** | Calls LLM + writes a local report file as a side effect | `/brief`, `/daily-brief` |

> ⚠ `/daily-brief` calls `adwi_cli.py /daily-brief --n8n` which writes to `notes/daily-briefs/` and
> attempts an Obsidian daily-note update. This is intentional behavior (not a bug), but it is not
> purely read-only. The Telegram bridge does not write files directly.

## Response Handling

- All API responses are stripped of ANSI escape sequences before sending
- Replies are truncated at 4000 characters with a `…[truncated]` suffix
- `/daily-brief` output is JSON-parsed and reformatted as plain text
- Local commands (`/help`, `/ping`) return instantly without an API call

---

*Last updated: 2026-06-21 | Exp branch: exp/claude-codex-autobatch-20260621-1140*
