# Telegram Bridge — Setup and Operation Guide

> **Audience:** Suneel (operator). Step-by-step setup for the Adwi Telegram bridge.
> All paths assume `~/SuneelWorkSpace` is the repo root.

---

## What the bridge does

Long-polls the Telegram Bot API from this Mac (outbound HTTPS only — no inbound port,
no public endpoint). When you send a command from your Telegram account, it routes
through the Safe Command API at `localhost:5055` and replies with the result.

v1 command surface: `/help` `/status` `/doctor` `/brief` `/daily-brief` `/git-status`

Everything else is rejected. Only your configured Telegram user ID can issue commands.

---

## Step 1 — Create a Telegram bot (one-time, ~2 minutes)

1. Open Telegram and search for **@BotFather**.
2. Send `/start`, then `/newbot`.
3. Enter a display name (e.g. `Adwi`) and a username (e.g. `MyAdwiBot` — must end in `bot`).
4. BotFather replies with a token like:

   ```
   5678901234:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi
   ```

   Copy this — it goes into `config/.env` as `TELEGRAM_BOT_TOKEN`.

> **Security note:** Treat this token like a password. Anyone with the token can
> control the bot. It is stored in `config/.env` which is gitignored.

---

## Step 2 — Find your numeric Telegram user ID

The bridge uses your **numeric user ID** (an integer like `123456789`), not your
`@username`. Usernames can change; numeric IDs cannot.

Safest method:
1. Open Telegram and search for **@userinfobot**.
2. Send `/start`. It replies with your ID, first name, and language.
3. Copy the integer ID.

Alternative: message **@RawDataBot** → `/start` → look for `"id": 123456789` in the JSON.

---

## Step 3 — Add config values to `adwi/config/.env`

Open `~/SuneelWorkSpace/adwi/config/.env` and add (or replace the placeholders):

```ini
TELEGRAM_BOT_TOKEN=5678901234:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi
TELEGRAM_ALLOWED_USER_ID=123456789
```

`ADWI_LOCAL_SECRET` should already be set from the Safe Command API setup.

---

## Step 4 — Verify the Safe Command API is running

The bridge calls `localhost:5055` for every command. Check it is up:

```bash
curl -s -H "X-Adwi-Secret: $(grep ADWI_LOCAL_SECRET ~/SuneelWorkSpace/adwi/config/.env | cut -d= -f2)" \
     http://127.0.0.1:5055/ | python3 -m json.tool
```

Expected: JSON with `"allowed_routes"` list. If you get `Connection refused`, start
the command API first:

```bash
cd ~/SuneelWorkSpace
python3 adwi/services/command-api/server.py &
```

---

## Step 5 — Test the bridge manually (before installing as daemon)

Run the bridge directly in a terminal first to verify your config is correct:

```bash
cd ~/SuneelWorkSpace
python3 adwi/services/telegram-bridge/bot.py
```

Expected startup output:

```
2026-06-20T10:45:00 [telegram-bridge] INFO Started. Long-polling Telegram (timeout=30s per batch).
2026-06-20T10:45:00 [telegram-bridge] INFO Allowed sender UID: 123456789
```

If you see `[ERROR] TELEGRAM_BOT_TOKEN not set`, the `.env` values are not loaded.
Confirm the file exists and the values are not `REPLACE_ME`.

### Send a test message

Open Telegram → your bot → send:

```
/help
```

Expected bot reply:

```
Adwi Telegram Bridge  —  v1 read-only commands:
  /brief         → /adwi-brief
  /daily-brief   → /adwi-daily-brief-n8n
  /doctor        → /adwi-doctor
  /git-status    → /git-status-workspace
  /help          → this message
  /status        → /adwi-status

Commands not listed here are rejected.
```

Then test a real command:

```
/status
```

Expected: bot replies `Running /status…` then the Adwi service health summary.

### Test that blocked commands are rejected

Send:

```
/run-bash echo hi
```

Expected reply: `Unknown command: '/run-bash'` — the Safe Command API is never called.
Check the terminal log — you should see no dispatch line for this message.

### Test that unknown senders are blocked

If someone else messages your bot (or you test with a second account), the bridge
must not reply. The terminal log shows:

```
WARNING Dropped message from unknown sender_id=<their id>
```

Stop the manual test with `Ctrl+C` once everything looks correct.

---

## Step 6 — Install the LaunchAgent (run at login, keep alive)

Run these commands from `~/SuneelWorkSpace`:

```bash
# Generate the plist with your machine's paths substituted
sed "s|__REPO_ROOT__|$HOME/SuneelWorkSpace|g; \
     s|__PYTHON__|$HOME/SuneelWorkSpace/adwi/.venv/bin/python3|g; \
     s|__HOME__|$HOME|g" \
  adwi/config/launchagents/com.suneel.telegram-bridge.plist.template \
  > ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist

# Load it into launchd (starts immediately due to RunAtLoad=true)
launchctl load ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist
```

---

## Step 7 — Verify the LaunchAgent is loaded and running

```bash
# Check launchd status (non-zero PID means running)
launchctl list | grep telegram-bridge

# Expected output:
# <PID>    0    com.suneel.telegram-bridge

# Follow live logs
tail -f /tmp/adwi-telegram-bridge.log
```

A PID of `-` means the process is not running (crashed or config error).
Check the log for `[ERROR]` lines.

---

## Step 8 — Send the first Telegram command after daemon start

With the LaunchAgent running, open Telegram and send `/help` to your bot.
You should receive the command list within a few seconds (30 s maximum — the
long-poll timeout).

---

## Step 9 — Stop or unload the bridge

```bash
# Unload (stops the process; does not delete the plist — reloads on next login)
launchctl unload ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist

# Reload after changes
launchctl unload ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist
launchctl load   ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist

# Full uninstall (removes from login autostart)
launchctl unload ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist
rm ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist
```

---

## Quick reference: all operational commands

| Goal | Command |
|------|---------|
| Start manually (test mode) | `python3 adwi/services/telegram-bridge/bot.py` |
| Install LaunchAgent | see Step 6 above |
| Check if running | `launchctl list \| grep telegram-bridge` |
| View live logs | `tail -f /tmp/adwi-telegram-bridge.log` |
| Stop (keep plist) | `launchctl unload ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist` |
| Start (reload plist) | `launchctl load ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist` |
| Full uninstall | `launchctl unload ~/...` then `rm ~/Library/LaunchAgents/com.suneel.telegram-bridge.plist` |
| Run bridge tests | `python3 -m unittest adwi/tests/test_telegram_bridge.py` |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `[ERROR] TELEGRAM_BOT_TOKEN not set` | Token missing or still `REPLACE_ME` in `.env` | Edit `adwi/config/.env` |
| `[ERROR] TELEGRAM_ALLOWED_USER_ID not set` | UID missing or still `REPLACE_ME` | Edit `adwi/config/.env` |
| `[ERROR] … must be an integer` | UID is a username (`@suneel`) instead of a number | Use @userinfobot to get numeric ID |
| Bot receives message but does not reply | Sender ID mismatch — log shows `Dropped message` | Confirm UID in `.env` matches @userinfobot output |
| Reply: `[error] Connection refused` | Safe Command API (:5055) not running | Start server.py; check its own LaunchAgent |
| Reply: `[error] HTTP 401` | `ADWI_LOCAL_SECRET` mismatch | Verify same secret in `.env` and the command API |
| LaunchAgent PID is `-` after load | Bridge crashed at startup (bad token/UID) | `tail /tmp/adwi-telegram-bridge.log` for `[ERROR]` |
| `/status@MyBot` not recognized | Shouldn't happen — bridge strips `@BotName` | Check `bot.py` line 192 |
| LaunchAgent loaded but no response | Bot token valid? Try `curl` to Telegram API | `curl "https://api.telegram.org/bot<TOKEN>/getMe"` |

---

## v1 limits

- Single allowed user (one `TELEGRAM_ALLOWED_USER_ID`).
- Read-only commands only — no Gmail, no file writes, no patching, no shell.
- `/daily-brief` returns raw JSON from the `--n8n` mode. Readable but not formatted.
- No message history — each command is stateless.
- Commands may take up to 120 s (bridge timeout); `/doctor` can be slow if Ollama is busy.

---

## Adding a command in the future

1. Confirm the command already exists in `ALLOWED_COMMANDS` in `adwi/services/command-api/server.py`.
2. Add one line to `TELEGRAM_COMMANDS` dict in `adwi/services/telegram-bridge/bot.py`.
3. Add a test case to `adwi/tests/test_telegram_bridge.py`.
4. Run `python3 -m unittest adwi/tests/test_telegram_bridge.py` — must be 0 failures.
5. Reload the LaunchAgent: `launchctl unload …` then `launchctl load …`.
