"""
Telegram long-polling bridge for Adwi.

Delivery mode: getUpdates long polling — no public endpoint, no tunnel, no ngrok.
All traffic is outbound HTTPS from this Mac to api.telegram.org:443.

Safety model (applied in order on every inbound message):
  1. Sender allowlist  — only TELEGRAM_ALLOWED_USER_ID may issue commands.
     Unknown senders are silently dropped (no error message sent back).
  2. Command allowlist — TELEGRAM_COMMANDS maps Telegram /cmd → Safe Command API route.
     Anything not in the dict is rejected with a usage hint.
  3. Safe Command API  — localhost:5055 enforces its own allowlist + ADWI_LOCAL_SECRET.
     The Telegram bridge never bypasses or duplicates that gate.
  4. Response cap      — replies truncated to REPLY_MAX_LEN chars before send.

What this bridge will never do:
  - Execute shell commands or run-bash/run-python
  - Trigger patching, self-heal, or any code mutation
  - Send emails or archive/trash Gmail messages
  - Write files or mutate any local state
  - Accept input from anyone other than the configured user ID

Config (all from adwi/config/.env):
  TELEGRAM_BOT_TOKEN       — bot token from @BotFather
  TELEGRAM_ALLOWED_USER_ID — your numeric Telegram user ID (integer, not username)
  ADWI_LOCAL_SECRET        — shared secret for Safe Command API (:5055)

Usage:
  python3 adwi/services/telegram-bridge/bot.py
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import time
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [telegram-bridge] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

HOME      = Path.home()
WORKSPACE = HOME / "SuneelWorkSpace"

REPLY_MAX_LEN = 4000   # Telegram hard limit is 4096; headroom for ellipsis suffix
POLL_TIMEOUT  = 30     # seconds — getUpdates long-poll window
ADWI_API_HOST = "127.0.0.1"
ADWI_API_PORT = 5055
TG_API_BASE   = "https://api.telegram.org"

# ── Command allowlist ─────────────────────────────────────────────────────────
# Maps Telegram /command → Safe Command API route already in ALLOWED_COMMANDS.
# To add a command: it must first exist in server.py ALLOWED_COMMANDS; then add
# here. None means handled locally without an API call.
# Never add: run-bash, run-python, patch-adwi, self-heal, nightly-run,
#            git-commit, gmail-send/confirm, implement-idea, notify, file-write.

TELEGRAM_COMMANDS: dict[str, str | None] = {
    "/help":           None,                      # handled locally — lists commands
    "/status":         "/adwi-status",
    "/doctor":         "/adwi-doctor",
    "/brief":          "/adwi-brief",
    "/daily-brief":    "/adwi-daily-brief-n8n",
    "/git-status":     "/git-status-workspace",
    "/models":         "/adwi-models",
    "/watcher-status": "/adwi-watcher-status",
}

_HELP_LINES = [
    "Adwi Telegram Bridge  —  v1 read-only commands:",
    *[f"  {cmd:<14} → {route or 'this message'}"
      for cmd, route in sorted(TELEGRAM_COMMANDS.items())],
    "",
    "Commands not listed here are rejected.",
]
HELP_TEXT = "\n".join(_HELP_LINES)


# ── Config loader ─────────────────────────────────────────────────────────────

def _load_env() -> None:
    """Load config/.env into os.environ (setdefault — does not override shell)."""
    env_path = WORKSPACE / "adwi" / "config" / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ.setdefault(k, v)


# ── Telegram API helpers ──────────────────────────────────────────────────────

def _tg_url(token: str, method: str) -> str:
    return f"{TG_API_BASE}/bot{token}/{method}"


def _tg_post(token: str, method: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _tg_url(token, method),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 10) as resp:
        return json.loads(resp.read())


def _tg_get_updates(token: str, offset: int) -> dict:
    url = _tg_url(token, "getUpdates") + f"?offset={offset}&timeout={POLL_TIMEOUT}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 10) as resp:
        return json.loads(resp.read())


def _send_reply(token: str, chat_id: int, text: str) -> None:
    if len(text) > REPLY_MAX_LEN:
        text = text[:REPLY_MAX_LEN] + "\n…[truncated]"
    try:
        _tg_post(token, "sendMessage", {"chat_id": chat_id, "text": text})
    except Exception as exc:
        log.error("sendMessage failed: %s", exc)


# ── Safe Command API caller ───────────────────────────────────────────────────

def _call_adwi(route: str, secret: str) -> str:
    """
    GET http://127.0.0.1:5055<route> with X-Adwi-Secret header.
    Returns plain-text output suitable for a Telegram reply.
    Never raises — errors surface as a bracketed string.
    """
    conn = http.client.HTTPConnection(ADWI_API_HOST, ADWI_API_PORT, timeout=120)
    try:
        conn.request("GET", route, headers={"X-Adwi-Secret": secret})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        if resp.status != 200:
            return f"[error] HTTP {resp.status} from Adwi command API"
        data = json.loads(raw)
        stdout = data.get("stdout", "").strip()
        stderr = data.get("stderr", "").strip()
        rc     = data.get("returncode", 0)
        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if rc != 0 and stderr:
            parts.append(f"[exit {rc}] {stderr[:300]}")
        elif rc != 0:
            parts.append(f"[exit {rc}]")
        return "\n".join(parts) if parts else "(no output)"
    except Exception as exc:
        return f"[error] {exc}"
    finally:
        conn.close()


# ── /daily-brief JSON formatter ──────────────────────────────────────────────

def _format_daily_brief(raw: str) -> str:
    """
    Parse the JSON emitted by /daily-brief --n8n and render as plain text.
    Falls back to raw text unchanged on any parse failure or unrecognized structure.
    Applied only to /daily-brief — no other command passes through this function.

    Expected top-level keys (from cmd_daily_brief n8n_mode in adwi_cli.py):
        ok, generated_at, services, gmail, brief, warnings, errors
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw   # not JSON — pass through unchanged

    if not isinstance(data, dict) or not data.get("ok"):
        return raw   # unrecognized structure — pass through unchanged

    lines: list[str] = []

    # Header with timestamp (slice ISO string to "YYYY-MM-DD HH:MM")
    ts = (data.get("generated_at") or "")[:16].replace("T", " ")
    lines.append(f"Daily Brief — {ts}" if ts else "Daily Brief")

    # Services: compact single line
    services = data.get("services")
    if isinstance(services, dict) and services:
        lines.append("Services: " + "  ".join(f"{k}={v}" for k, v in services.items()))

    # Gmail section
    gmail = data.get("gmail") or {}
    if isinstance(gmail, dict):
        g_warns = [w for w in (gmail.get("warnings") or []) if w]
        if g_warns:
            lines.append(f"Gmail: {'; '.join(g_warns)}")
        else:
            unread  = gmail.get("unread_count") or 0
            summary = (gmail.get("summary") or "").strip()
            if unread:
                lines.append(f"Gmail: {unread} unread today")
                if summary:
                    lines.append(summary)
            else:
                lines.append(f"Gmail: {summary or 'Inbox clear.'}")

    # LLM-generated brief — strip markdown ** bold markers for plain-text Telegram
    brief = (data.get("brief") or "").strip()
    if brief:
        lines.append("")
        lines.append(brief.replace("**", ""))

    # Surface system-level warnings / errors
    warns = [w for w in (data.get("warnings") or []) if w]
    errs  = [e for e in (data.get("errors")   or []) if e]
    if warns:
        lines.append(f"Warnings: {'; '.join(warns)}")
    if errs:
        lines.append(f"Errors: {'; '.join(errs)}")

    return "\n".join(lines).strip()


# ── Update handler ────────────────────────────────────────────────────────────

def _handle_update(update: dict, token: str, allowed_uid: int, secret: str) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    sender = message.get("from")
    if not sender:
        return   # channel posts have no "from"

    chat_id   = message["chat"]["id"]
    sender_id = sender["id"]
    text      = (message.get("text") or "").strip()

    # 1. Sender allowlist — silent drop; do not reveal capability to unknown senders
    if sender_id != allowed_uid:
        log.warning("Dropped message from unknown sender_id=%s", sender_id)
        return

    if not text:
        return

    # Telegram appends @BotUsername to commands sent in groups — strip it
    cmd_token = text.split()[0].split("@")[0].lower()

    # 2. Command allowlist
    if cmd_token not in TELEGRAM_COMMANDS:
        _send_reply(
            token, chat_id,
            f"Unknown command: {cmd_token!r}\n\nSend /help to see available commands.",
        )
        return

    route = TELEGRAM_COMMANDS[cmd_token]

    # 3. Local /help — no API call
    if route is None:
        _send_reply(token, chat_id, HELP_TEXT)
        return

    # 4. Dispatch via Safe Command API
    log.info("cmd=%s route=%s sender=%s", cmd_token, route, sender_id)
    _send_reply(token, chat_id, f"Running {cmd_token}…")
    result = _call_adwi(route, secret)
    if cmd_token == "/daily-brief":
        result = _format_daily_brief(result)
    _send_reply(token, chat_id, result or "(empty response)")


# ── Poll loop ─────────────────────────────────────────────────────────────────

def poll_loop(token: str, allowed_uid: int, secret: str) -> None:
    offset = 0
    log.info("Started. Long-polling Telegram (timeout=%ss per batch).", POLL_TIMEOUT)
    log.info("Allowed sender UID: %s", allowed_uid)
    while True:
        try:
            data = _tg_get_updates(token, offset)
            if not data.get("ok"):
                log.error("getUpdates error: %s", data)
                time.sleep(5)
                continue
            for update in data.get("result", []):
                uid = update["update_id"]
                try:
                    _handle_update(update, token, allowed_uid, secret)
                except Exception as exc:
                    log.error("Error handling update_id=%s: %s", uid, exc)
                offset = max(offset, uid + 1)
        except KeyboardInterrupt:
            log.info("Stopped by keyboard interrupt.")
            break
        except Exception as exc:
            log.error("Poll error: %s — retrying in 5s", exc)
            time.sleep(5)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    _load_env()
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    uid_str = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "")
    secret  = os.environ.get("ADWI_LOCAL_SECRET", "")

    if not token or token == "REPLACE_ME":
        print("[ERROR] TELEGRAM_BOT_TOKEN not set — add it to adwi/config/.env")
        raise SystemExit(1)
    if not uid_str or uid_str == "REPLACE_ME":
        print("[ERROR] TELEGRAM_ALLOWED_USER_ID not set — add it to adwi/config/.env")
        raise SystemExit(1)
    try:
        allowed_uid = int(uid_str)
    except ValueError:
        print(f"[ERROR] TELEGRAM_ALLOWED_USER_ID must be an integer, got: {uid_str!r}")
        raise SystemExit(1)
    if not secret:
        print("[WARNING] ADWI_LOCAL_SECRET not set — command API auth is disabled")

    poll_loop(token, allowed_uid, secret)


if __name__ == "__main__":
    main()
