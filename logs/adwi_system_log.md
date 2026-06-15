# Adwi System Log
<!-- Append-only. Every change, success, failure, and pending task recorded here. -->

---

## 2026-06-15 — Phase 1: Environment Discovery & Baseline Audit

**Status: COMPLETE**

### Findings
- Hardware: Apple M4 Max, 64 GB RAM, 712 GB free disk
- Ollama models loaded: adwi:latest (18.6GB), nomic-embed-text, qwen3:0.6b, llama3.1:8b, minicpm-v:latest
- Docker containers: suneel-open-webui (:3000), suneel-n8n (:5678), suneel-searxng (:8888), suneel-qdrant (:6333)
- Active services: local-command-api (:5055), private-gpt (:8001)
- LaunchAgents: adwi-nightly (2AM), adwi-git-backup, openwebui-knowledge-watcher, qdrant, ollama
- knowledge.db: tables `chunks` + `qa_pairs` with embedding columns — operational, 2065 records post overnight run
- memory.db: ledger via AdwiMemory class in adwi/memory.py
- NLU dispatch: adwi_cli.py:3354 `dispatch_natural()`, :641 `ask_adwi()`, :3170 `cmd_memory_recall()`
- SearXNG NOTE: running on host port **8888** (container maps 8080→8888)

### Gaps Identified
- No obsidian-vault/ directory
- No Obsidian MCP server or vault HTTP bridge
- /memory-recall only queries memory.db — does not traverse vault .md files
- No /web-search command wired to SearXNG
- nightly.py lacks: system health checks, web research, Obsidian daily note output, "Pending Approval" section
- No config/.env for API tokens

---

## 2026-06-15 — Phase 2: Vault & Directory Provisioning

**Status: COMPLETE**

### Actions Taken
- Created obsidian-vault/ with subdirs: inbox/ projects/ knowledge/ automations/ prompts/ logs/ daily-notes/ mcp-config/ .obsidian/
- Created config/ for .env API token storage
- Created logs/ for this system log
- Wrote starter notes: Local AI Stack Overview, Agent Rules & Guardrails, Troubleshooting Log
- Wrote config/.env with placeholder tokens (Brave Search, Tavily)
- Wrote .gitignore entries for config/.env and vault runtime files

---

## 2026-06-15 — Phase 3: Dual-Layer MCP Integration

**Status: COMPLETE**

### Actions Taken
- Wrote mcp-servers/obsidian-bridge/server.py — lightweight HTTP server exposing vault read/write/search/append on :5056
- Wrote mcp-servers/obsidian-bridge/start.sh and stop.sh
- Added com.suneel.obsidian-bridge.plist LaunchAgent (starts with login, port 5056)
- Confirmed Playwright MCP available via npx @playwright/mcp
- Extended adwi_cli.py: OBSIDIAN_VAULT path constant + cmd_obsidian_read/write/search + dispatch intents

---

## 2026-06-15 — Phase 4: Web Search & /memory-recall Dual-Layer

**Status: COMPLETE**

### Actions Taken
- Added searxng_search() helper to adwi_cli.py targeting :8888
- Added /web-search command + "web_search" NLU intent in dispatch_natural()
- Extended cmd_memory_recall() to traverse both memory.db AND obsidian-vault/**/*.md
- Added config/.env loader at adwi_cli.py startup (non-fatal if absent)
- Added Brave/Tavily fallback stubs guarded by env var presence

---

## 2026-06-15 — Phase 5: Nightly Maintenance Script Extension

**Status: COMPLETE**

### Actions Taken
- Extended nightly.py with step_system_health(): brew outdated, npm outdated, docker stats, disk check
- Extended nightly.py with step_web_research(): queries SearXNG for release notes on stack tools
- Extended nightly.py with step_obsidian_daily_note(): writes daily note to obsidian-vault/daily-notes/
- Extended step_write_report() to produce full morning_brief.md with "Pending User Approval" section
- LaunchAgent com.suneel.adwi-nightly already in place at 2:00 AM — no plist change needed

---

## 2026-06-15 — Phase 6: Known-Good State Documentation

**Status: COMPLETE**

### Actions Taken
- Wrote obsidian-vault/knowledge/rollback-and-recovery.md with full rollback instructions

---

## Pending / Watch Items
- [ ] Populate config/.env with real Brave Search / Tavily API keys when ready
- [ ] Point Obsidian desktop app at ~/SuneelWorkSpace/obsidian-vault to open the vault
- [ ] Load com.suneel.obsidian-bridge LaunchAgent: `launchctl load ~/Library/LaunchAgents/com.suneel.obsidian-bridge.plist`
- [ ] Run `/web-search ollama release notes` from adwi to verify SearXNG wiring
- [ ] Run `/obsidian-search local AI` to verify vault bridge

---

## 2026-06-15 — 5-Pillar Architecture Upgrade

### Pillar A: NLU Upgrade (Structured Intent Classification)
- Swapped `MODEL_FAST` from `qwen3:0.6b` → `llama3.1:8b` (already available, 4.9GB)
- Added Ollama native JSON schema `format` parameter to `_ollama_chat()` for constrained decoding
- Built comprehensive `_ALL_INTENTS` enum (55 intents covering all 80+ commands)
- `_INTENT_JSON_SCHEMA` passed to every NLU call — model physically cannot output an invalid intent token
- 4-layer classification: YouTube/image detect → regex prefilter → llama3.1:8b structured → qwen3:0.6b fallback
- Enhanced regex prefilter: added `memory_recall` pattern for "what do you remember about X"
- Added `instructor` library via adwi/.venv for optional enhanced structured outputs
- Wired 20+ new intents into `dispatch_natural()` (voice_in/out, obsidian_read/write, backup_*, nightly_*, etc.)

### Pillar B: iPhone Control Plane
- Added `homeassistant` and `cloudflared` services to docker-compose.yml
- Tailscale already installed — user needs `sudo tailscale up` + browser auth
- Created `bin/start-homeassistant` helper script
- Created `adwi/iphone-control-plane.md` — complete step-by-step guide:
  * Home Assistant setup on :8123
  * Tailscale mesh VPN for remote access
  * Cloudflare Tunnel for inbound webhooks (via CLOUDFLARE_TUNNEL_TOKEN in config/.env)
  * 3 n8n webhook workflows (morning brief, pending approvals, force nightly)
  * Siri Shortcuts specs for "Run Morning Brief", "What Needs Approval?", "Force Maintenance"
  * Apple Watch complication setup
  * HA rest_command configuration

### Pillar C: Local Voice I/O Pipeline
- Created `adwi/voice.py` — full STT/TTS pipeline:
  * STT: faster-whisper (base.en, int8, CoreML-optimized) via `transcribe()`
  * TTS: piper-tts (en_US-lessac-medium, auto-downloads ~63MB model) via `speak()`
  * Recording: `record_mic()` via sox (brew install sox)
- Added commands to adwi_cli.py: `/voice-in`, `/listen`, `/voice-out`, `/voice-brief`
- Wired into NLU: `voice_in` and `voice_out` intents dispatch to voice commands
- Packages installed in adwi/.venv: faster-whisper==1.2.1, piper-tts==1.4.2

### Pillar D: Deep Agent Observability
- Added `arize-phoenix:version-8.1.0` to docker-compose.yml (ports: 6006 UI, 4317 gRPC, 4318 HTTP)
- OpenTelemetry SDK already installed (opentelemetry-api, sdk, exporter-otlp-grpc)
- Added `_otel_span()` context manager to adwi_cli.py — no-op when Phoenix is down
- Instrumented `classify_intent()` with `classify_intent` OTel span including input text + model
- Added `_latency_ms` to every classification result for latency tracking
- Added `step_promptfoo_eval()` to nightly.py:
  * 50 ground-truth intent routing test cases (auto-generated to adwi/promptfoo-eval.yaml)
  * Runs via `promptfoo eval` (installed globally via npm)
  * If precision < 95%: flagged in Pending User Approval section of morning brief
- Created `bin/start-phoenix` helper

### Pillar E: Multi-Modal Document Indexing
- Added `markitdown==0.1.6` to adwi/.venv
- Added `RICH_EXTS = {".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".epub", ".zip"}` to overnight_learn.py
- `crawl_workspace()` now includes rich formats when markitdown is available
- Created `read_file_content()` — dispatches to markitdown for rich formats, text for rest
- Rich docs allow up to 5MB (vs 180KB for plain text)
- Main indexing loop now calls `read_file_content(file_path)` instead of direct `read_text()`

### New Files
- `adwi/voice.py` — Voice I/O module
- `adwi/iphone-control-plane.md` — iPhone setup guide
- `adwi/.venv/` — Python venv with instructor, markitdown, faster-whisper, piper-tts, arize-phoenix
- `adwi/promptfoo-eval.yaml` — Auto-generated on first nightly run
- `bin/start-phoenix` — Start Phoenix dashboard
- `bin/start-homeassistant` — Start Home Assistant

### Updated Files
- `adwi/adwi_cli.py` — Pillar A NLU, Pillar C voice commands, Pillar D OTel instrumentation
- `adwi/overnight_learn.py` — Pillar E markitdown integration
- `adwi/nightly.py` — Pillar D promptfoo eval step
- `local-ai-stack/docker-compose.yml` — Phoenix, Home Assistant, cloudflared containers
- `bin/adwi` — Now uses venv python if available
- `config/.env` — Added HA token, cloudflare tunnel token, Phoenix URL placeholders

### Port Assignments (new)
- :6006 — Arize Phoenix UI
- :4317 — OTLP gRPC (Phoenix)
- :4318 — OTLP HTTP (Phoenix)
- :8123 — Home Assistant (pending `docker compose up -d homeassistant`)

### Requires User Action
1. `sudo tailscale up` — authenticate Tailscale for remote access
2. `docker compose up -d homeassistant` → visit :8123 → create HA account → add token to config/.env
3. Cloudflare Tunnel: get token from dash.cloudflare.com → add CLOUDFLARE_TUNNEL_TOKEN to config/.env
4. Install sox for mic recording: `brew install sox`
5. iPhone: install Tailscale app + HA companion app (see iphone-control-plane.md)

---

## 2026-06-15 — Mandate Execution: Infrastructure Wiring

### Completed Automatically
- sox 14.x installed via brew — mic recording now live
- voice.py updated: sox (primary) + ffmpeg (fallback) for mic recording  
- Home Assistant container started: suneel-homeassistant up at :8123
- auto-update-readme script created (bin/auto-update-readme)
- .git/hooks/pre-commit installed — fires auto-readme on every commit
- bin/adwi-git-backup patched — calls auto-readme before each backup commit
- adwi/backup.py patched — _run_auto_readme() called inside do_backup()
- README.md markers injected: AUTO:MODELS, AUTO:SERVICES, AUTO:AGENTS, AUTO:COMMANDS
- All changes committed and pushed (acc5db7 → 43a99aa)

### Pending User Action (3 items)
1. **Tailscale**: App at /Applications/Tailscale.app is missing.
   Install from: https://tailscale.com/download/mac
   Then run: tailscale up (no sudo needed after app install)
   
2. **Home Assistant Token**: Visit http://localhost:8123 → complete onboarding →
   Settings → Profile → Long-Lived Access Tokens → Create Token → copy it
   Then paste here and I will write it to config/.env

3. **Cloudflare Tunnel Token**: Visit https://one.dash.cloudflare.com →
   Zero Trust → Networks → Tunnels → Create tunnel → name it "adwi-n8n" →
   Copy the token shown in step 2 of the connector setup →
   Paste here and I will write it to config/.env
