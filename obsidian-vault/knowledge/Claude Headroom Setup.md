---
type: reference
status: active
tags: [claude, headroom, context-compression, token-efficiency]
updated: 2026-06-22
---

# Claude Headroom Setup

Headroom is a local context compression proxy that reduces the tokens sent to Anthropic, with the aim of preserving useful context quality. It runs entirely on your Mac — data never leaves your machine.

**Accuracy note:** Headroom is designed to preserve semantically important content, but compression cannot guarantee zero accuracy loss. For critical or nuanced tasks, prefer lower-compression settings or the uncompressed fallback.

---

## What was installed

| Item | Detail |
|------|--------|
| Package | `headroom-ai[proxy]` v0.27.0 |
| Install method | `pipx install --python /opt/homebrew/bin/python3.12 "headroom-ai[proxy]"` |
| Python | 3.12.13 (isolated pipx venv — does not touch adwi/.venv) |
| Binary | `~/.local/bin/headroom` |
| Config modified | None at install time |

---

## How Claude is configured

Headroom does **not** permanently modify Claude config. Instead:

1. `headroom wrap claude` starts a local proxy on port 8787
2. It temporarily writes `ANTHROPIC_BASE_URL=http://127.0.0.1:8787` into `.claude/settings.local.json` (project-local, not global)
3. Claude Code sends all API calls through the proxy, which compresses context before forwarding to Anthropic
4. When the wrap session exits, the settings.local.json entry is automatically removed

---

## How to launch Claude with Headroom

```bash
# From your workspace terminal:
headroom wrap claude

# With a specific model:
headroom wrap claude -- --model claude-sonnet-4-6
```

This replaces a bare `claude` invocation. You get the same Claude experience, with compression running transparently.

**Without Headroom (fallback):** Just run `claude` normally. Everything works as before. Headroom is purely additive.

---

## Verify it is working

During a `headroom wrap claude` session, open a second terminal and run:

```bash
# Check proxy and routing:
headroom doctor

# See compression savings:
headroom perf

# Run the local validator:
adwi/.venv/bin/python3 adwi/scripts/validate_claude_headroom.py

# Compact status:
adwi/.venv/bin/python3 adwi/scripts/claude_headroom_status.py
```

When the proxy is running, `headroom doctor` shows all green. `headroom perf` shows token savings per session.

---

## What Headroom compresses

Current install: `headroom-ai[proxy]`. Available compressors:

| Content type | Algorithm | Status | Indicative savings |
|---|---|---|---|
| JSON tool outputs | SmartCrusher | ✅ Available | 70–90% |
| Source code | CodeCompressor (AST) | ✅ Available | 40–75% |
| Git/search outputs | RTK shell filters | ✅ Available | 60–92% |
| Prose / logs (ML) | Kompress-base | ❌ Not installed | 60–85% |

**ML Kompress-base** (text/prose compression) requires `headroom-ai[ml]` which adds `torch` and `onnxruntime`. Not currently installed. To add it later:
```bash
pipx inject headroom-ai "headroom-ai[ml]"
```

The RTK shell filter (`rtk <cmd>`) reduces what enters context before the proxy sees it. Add `rtk` as a prefix to common commands:

```bash
rtk git status    # ~59% smaller
rtk git diff      # ~80% smaller
rtk grep <pat>    # filtered to matches only
```

Savings figures are indicative from Headroom benchmarks — actual savings depend on content type and size.

---

## Proxy details

| Property | Value |
|---|---|
| Default port | 8787 |
| Backend | Direct Anthropic API (forwarded with compression) |
| Data location | Local only — no data leaves your Mac |
| CCR cache | Originals stored locally; LLM retrieves via headroom_retrieve if needed |

---

## Rollback / uninstall

To stop using Headroom:
1. Exit the `headroom wrap claude` session (Ctrl+C or close terminal)
2. Verify `.claude/settings.local.json` no longer has `ANTHROPIC_BASE_URL` — it is cleaned up automatically
3. If anything was injected globally: `headroom unwrap` removes Headroom entries from `~/.claude/settings.json`
4. To uninstall entirely: `pipx uninstall headroom-ai`

**Normal `claude` invocations are never affected** — only `headroom wrap claude` sessions route through the proxy.

---

## First wrapped session checklist

Do this the first time you use Headroom with Claude:

1. **Start the wrapped session:** `headroom wrap claude` (or `adwi/bin/claude-headroom`)
2. **In a second terminal, run:** `headroom doctor` — confirm proxy shows OK
3. **Ask Claude to read a few files** in the Claude session to generate some context traffic
4. **Check savings:** `headroom perf` — should show token counts for that session
5. **If anything behaves unexpectedly:** exit the wrap session (Ctrl+C), run `claude` directly as fallback, and report the issue

---

## When to use normal Claude (not Headroom)

Use `claude` directly (not `headroom wrap claude`) when:
- Debugging proxy or routing issues
- Headroom is unavailable or the proxy fails to start
- You notice compressed context affecting response quality on a subtle task
- You need to reproduce a bug without compression in the picture

The bare `claude` command is always the reliable fallback and is never affected by Headroom config.

---

## Known limitations

- Headroom is designed to preserve semantically important content, but compression is lossy — accuracy cannot be guaranteed to be identical to uncompressed sessions.
- Context limits are extended, not eliminated. Very large codebases may still hit limits.
- The proxy must be running (`headroom wrap claude`) for compression to be active. Outside a wrap session, Claude uses the direct Anthropic API.
- Python 3.12 is used for the Headroom venv (pipx-isolated). The adwi `.venv` (Python 3.14) is untouched.
- `headroom-ai[proxy]` is installed. ML Kompress-base (text/prose) is not installed — requires `headroom-ai[ml]`.
- `headroom perf` shows no data until after the first wrapped session.

---

## Validation scripts

| Script | Purpose |
|---|---|
| `adwi/scripts/smoke_claude_headroom.py` | Smoke check — install valid, binary works, doctor interpreted |
| `adwi/scripts/validate_claude_headroom.py` | 8-check static validator (stdlib-only, read-only) |
| `adwi/scripts/claude_headroom_status.py` | Compact one-screen status |
| `adwi/bin/claude-headroom` | Shell helper — `headroom wrap claude "$@"` |

---

## Related

- [[Adwi Home]]
- [[knowledge/Automation Map]]
- `CLAUDE.md` — Headroom Usage section (workspace Claude instructions)
- `adwi/scripts/validate_claude_headroom.py`
- `adwi/scripts/claude_headroom_status.py`
