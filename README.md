# Adwi — Local AI Operating System · LLM System Blueprint

> **PRIMING CONTEXT FOR EXTERNAL MODELS:** This document is a machine-optimised architectural blueprint.
> If you are Gemini, Copilot, GPT-4, or any other LLM reading this cold, you have full architectural
> comprehension of the Adwi system after reading this file. All sections are authoritative and kept
> current by an automated injection pipeline. Treat this as the single source of truth.
>
> **OPERATOR:** Suneel Bikkasani · **HARDWARE:** Apple M4 Max 64 GB unified RAM · **OS:** macOS 15
> **REPO:** `~/SuneelWorkSpace/` · **ENTRY POINT:** `bin/adwi` → `python3 adwi/adwi_cli.py`

---

## Table of Contents

| § | Section | Purpose |
|---|---|---|
| [§1](#1-system-dna--model-matrix) | System DNA & Model Matrix | Hardware, models, NLU pipeline |
| [§2](#2-infrastructure-topography) | Infrastructure Topography | Every port, container, agent, data flow |
| [§3](#3-deterministic-capability-grid) | Deterministic Capability Grid | All 103+ commands, args, behaviors |
| [§4](#4-agentic-lifecycle-flows) | Agentic Lifecycle Flows | ASCII diagrams of every execution path |
| [§5](#5-security--boundary-invariants) | Security & Boundary Invariants | Hard blocks, credential isolation |
| [§6](#6-directory-structure) | Directory Structure | Annotated file tree |
| [§7](#7-rollback--recovery) | Rollback & Recovery | Operational runbooks |
| [§8](#8-architecture-implementation-phases) | Architecture Implementation Phases | Phase 1–8 status and key files |

---

## §1 System DNA & Model Matrix

### Hardware Platform

| Property | Value |
|---|---|
| CPU | Apple M4 Max (16-core) |
| RAM | 64 GB unified memory |
| Storage | ~712 GB free NVMe |
| OS | macOS 15 (Darwin 25.x) |
| Python | 3.14 (venv: `adwi/.venv`) |
| Package manager | `uv` + pip via `ensurepip` |

### Model Roster

<!-- AUTO:MODELS -->
| Constant | Model |
|---|---|
| `MODEL_EMBED` | `nomic-embed-text` |
| `MODEL_FAST` | `llama3.1:8b` |
| `MODEL_MAIN` | `adwi:latest` |
| `MODEL_NLU_FALLBACK` | `qwen3:0.6b` |
| `MODEL_VISION` | `minicpm-v:latest` |
*Auto-updated: 2026-06-15*
<!-- /AUTO:MODELS -->

### Model Role Matrix

| Model | Role | Context | Size | When used |
|---|---|---|---|---|
| `adwi:latest` | Primary reasoning | 131 072 tok | 18.6 GB | All chat, synthesis, planning |
| `llama3.1:8b` | NLU intent classification | 8 192 tok | 4.9 GB | Every natural-language dispatch |
| `qwen3:0.6b` | NLU fallback | 4 096 tok | ~400 MB | When llama3.1 is unavailable |
| `minicpm-v:latest` | Vision / image analysis | 4 096 tok | ~5 GB | `/image`, `/screenshot-analyze` |
| `nomic-embed-text` | Embeddings (768-dim) | 512 tok | ~274 MB | Memory search, RAG, knowledge DB |

### Custom Modelfile (`adwi/Modelfile`)

```
FROM qwen3:30b
PARAMETER num_ctx      131072
PARAMETER temperature  0.25
PARAMETER repeat_penalty 1.1
SYSTEM You are Adwi, a cautious local AI assistant. Never read secrets, never commit
       without review, always explain destructive actions before executing them.
```

### NLU Classification Pipeline

<!-- AUTO:NLU -->
**NLU Classification Pipeline** — every natural-language input passes through:

| Stage | Component | Detail |
|---|---|---|
| 0 | Instant pre-checks | YouTube URL regex, image path regex (0 ms) |
| 1 | Regex pre-filter | `_regex_prefilter()` — zero-latency for common phrases |
| 2 | Few-shot injection | Qdrant `nlu_fixtures` top-3 semantic matches (89 fixtures, 768-dim Cosine) |
| 3 | LLM classification | `llama3.1:8b` with JSON schema — `analysis`+`confidence`+`intent`+`arguments` (62 intent classes) |
| 4 | Argument dispatch | 29 typed slot reads: `path`, `query`, `url`, `size_mb`, `days`, `description` |
| 5 | Fallback | `qwen3:0.6b` (80-token budget, no analysis block) |

**Schema fields (Phase 6):**
- `analysis` — dense one-sentence reasoning before intent selection
- `confidence` — float 0.0–1.0
- `intent` — one of 62 registered intent classes
- `arguments` — typed key-value slots fed straight into command handlers

**Qdrant few-shot collection:** `nlu_fixtures` · 89 seed fixtures · scored at `score_threshold=0.5` · provisioned via `python3 adwi/memory.py provision-nlu`
*Auto-updated: 2026-06-15*
<!-- /AUTO:NLU -->

---

## §2 Infrastructure Topography

### Complete Port Map

<!-- AUTO:INFRA_PORTS -->
| Port | Service | Layer | Purpose |
|---|---|---|---|
| :11434 | Ollama | Host (brew) | Local LLM inference API |
| :3000 | Open WebUI | Docker | Browser chat UI + model switcher |
| :5055 | Safe Command API | Host | n8n→shell bridge (8 allowlisted routes) |
| :5056 | Obsidian Bridge | Host | Vault HTTP CRUD API |
| :5678 | n8n | Docker | Workflow automation / webhooks |
| :6006 | Arize Phoenix | Docker | Agent observability UI (OTel) |
| :6333 | Qdrant | Docker | Vector database |
| :8001 | PrivateGPT | Host | Document Q&A (optional) |
| :8123 | Home Assistant | Docker | iPhone control plane |
| :8888 | SearXNG | Docker | Private local web search |
| :9090 | Prometheus | Docker | Metrics scraper |
| :3100 | Loki | Docker | Log aggregation |
| :4000 | Grafana | Docker | Monitoring dashboards |
| :9100 | node-exporter | Docker | Host system metrics |
| :9101 | cAdvisor | Docker | Container metrics |
| :4317 | Phoenix gRPC | Docker | OTLP gRPC ingestion |
| :4318 | Phoenix HTTP | Docker | OTLP HTTP ingestion |
*Auto-updated: 2026-06-15*
<!-- /AUTO:INFRA_PORTS -->

### Docker Container Inventory

<!-- AUTO:SERVICES -->
| Service | Port | Status |
|---|---|---|
| open-webui | :3000 | ✓ running |
| n8n | :5678 | ✓ running |
| searxng | :8888 | ✓ running |
| prometheus | :9090 | ✓ running |
| loki | :3100 | ✓ running |
| grafana | :4000 | ✓ running |
| node-exporter | :9100 | ✓ running |
| cadvisor | :9101 | ✓ running |
*Auto-updated: 2026-06-15*
<!-- /AUTO:SERVICES -->

### macOS LaunchAgents

All managed at `~/Library/LaunchAgents/com.suneel.*.plist`.

<!-- AUTO:AGENTS -->
| Agent | Schedule |
|---|---|
| `adwi-git-backup` | every 30min |
| `adwi-nightly` | 2:00 AM |
| `caffeinate` | KeepAlive |
| `obsidian-bridge` | KeepAlive |
| `openwebui-knowledge-watcher` | KeepAlive |
| `phoenix` | KeepAlive |
| `qdrant` | on demand |
*Auto-updated: 2026-06-15*
<!-- /AUTO:AGENTS -->

### Data Flow Topology

```
External World
     │
     ├── Cloudflare Tunnel (:443) ─────────────────────────────────┐
     │                                                              │
     │                                                          n8n :5678
     │                                                              │
  iPhone / Browser                                       Safe Cmd API :5055
     │                                                              │
     ├── Tailscale VPN ─────────────── Home Assistant :8123         │
     │                                                              │
     └── Direct LAN ────────────────────────────────────────────────┘
                                                                     │
                                                       adwi_cli.py (REPL)
                                                                     │
                       ┌─────────────────────────────────────────────┤
                       │                │              │              │
                  Ollama :11434    Qdrant :6333   SearXNG :8888   memory.db
                       │                │              │
                adwi:latest      nomic-embed      local search
                llama3.1:8b      768-dim vecs     (no tracking)
                qwen3:0.6b       knowledge.db
                minicpm-v
```

### Monitoring Stack

<!-- AUTO:MONITORING -->
| Service | Port | Role | Status |
|---|---|---|---|
| prometheus | :9090 | Metrics scraper | ✓ running |
| loki | :3100 | Log aggregation | ✓ running |
| promtail | — | Log shipper → Loki | not started |
| grafana | :4000 | Dashboards UI | ✓ running |
| node-exporter | :9100 | System metrics | ✓ running |
| cadvisor | :9101 | Container metrics | ✓ running |

Start: `cd local-ai-stack && docker compose up -d prometheus loki promtail grafana node-exporter cadvisor`
Dashboard: http://localhost:4000 (user: suneel)
*Auto-updated: 2026-06-15*
<!-- /AUTO:MONITORING -->

---

## §3 Deterministic Capability Grid

<!-- AUTO:COMMANDS -->
**121 registered commands.** Key groups:

**add**: `/add-capability-plan <idea>`  `/add-root`
**backup**: `/backup-audit`  `/backup-disable`  `/backup-enable`  `/backup-log`  `/backup-now`  `/backup-status`
**benchmark**: `/benchmark`
**browse**: `/browse`
**capabilities**: `/capabilities`
**capabilities  or  /capability**: `/capabilities  or  /capability-status`
**capability**: `/capability-audit`  `/capability-status`
**cleanup**: `/cleanup`
**cloud <prompt>  or just type**: `/cloud <prompt>  or just type`
**cmd**: `/cmd`
**daily**: `/daily-improve`
**disk**: `/disk`
**doctor**: `/doctor`
**duplicates**: `/duplicates`
**eval**: `/eval-adwi`  `/eval-routing`
**exa**: `/exa`  `/exa-search`
**export**: `/export-training-example`
**extract**: `/extract-ideas`
**firecrawl**: `/firecrawl`
**fix**: `/fix-error`
**gemini**: `/gemini`
**generate**: `/generate-image`
**gh**: `/gh-status`
**git**: `/git`
**github**: `/github`  `/github-private`  `/github-public`  `/github-status`
**gmail**: `/gmail`  `/gmail-auth`  `/gmail-read`  `/gmail-summary`
**ha**: `/ha`
**help**: `/help`
**image**: `/image-save`
**image <path>  or  /screenshot**: `/image <path>  or  /screenshot-analyze <path>`
**implement**: `/implement-idea`
**inbox**: `/inbox`
**inspect**: `/inspect-code`  `/inspect-system`
**journal**: `/journal`
**large**: `/large-files`
**learn**: `/learn-from-last-error`
**list**: `/list`
**listen**: `/listen`
**local <prompt>  or /use**: `/local <prompt>  or /use-local then type`
**mcp**: `/mcp`  `/mcp-setup`
**memory**: `/memory-context`  `/memory-recall`  `/memory-scan`  `/memory-stats`
**mistakes**: `/mistakes`
**model**: `/model-status`
**models**: `/models`
**nightly**: `/nightly-log`  `/nightly-run`  `/nightly-status`
**notify**: `/notify`
**obsidian**: `/obsidian-daily`  `/obsidian-read`  `/obsidian-search`  `/obsidian-write`
**old**: `/old-files`
**organize**: `/organize`
**owui**: `/owui`
**patch**: `/patch-adwi`
**rag**: `/rag`  `/rag-index`
**read <path>**: `/read <path>`
**reason <task>**: `/reason <task>`
**remote**: `/remote`  `/remote-status`
**repair**: `/repair-adwi`
**repo**: `/repo-private`  `/repo-public`
**review**: `/review-plan <idea>`
**roadmap**: `/roadmap`
**route**: `/route`
**run**: `/run-bash`  `/run-python`  `/run-safe`
**save**: `/save-youtube <url>`
**screenshot**: `/screenshot-analyze`
**search <term>**: `/search <term>`
**secrets**: `/secrets-status`
**self**: `/self-heal`  `/self-heal  or  fix my setup`
**set**: `/set-cloud-model`
**status**: `/status`
**status  or  check my setup**: `/status  or  check my setup`
**sync**: `/sync-knowledge`  `/sync-knowledge  or  sync my knowledge`
**tailscale**: `/tailscale`
**tavily**: `/tavily`
**test**: `/test-adwi`
**tool**: `/tool-roadmap`
**trace**: `/trace-log`
**training**: `/training-plan`
**trusted**: `/trusted-roots`
**url <url>**: `/url <url>`
**use**: `/use-cloud`  `/use-local`
**voice**: `/voice`  `/voice-brief`  `/voice-in`  `/voice-out`
**watcher**: `/watcher-status`
**web**: `/web-search`
**what**: `/what-next`  `/what-next  or  what should I build next`
**youtube <url>  or paste URL**: `/youtube <url>  or paste URL`
*Auto-updated: 2026-06-15*
<!-- /AUTO:COMMANDS -->

### Full Command Reference

| Command | Args | Category | Behavior & Dependencies |
|---|---|---|---|
| `/ask` | `<question>` | Chat | Streams answer from `adwi:latest` · 131K ctx |
| `/chat` | `<message>` | Chat | Conversational mode with memory injection |
| `/reason` | `<task>` | Agentic | LangGraph Planner→Executor→Critic · `reason_engine.py` · Achievement Summary on completion |
| `/web-search` | `<query>` | Search | SearXNG+Tavily+Exa cascade · deduplicated by URL · synthesised by `adwi:latest` |
| `/browse` | `<url> [question]` | Search | Firecrawl → Playwright → urllib fallback chain |
| `/exa` | `<query>` | Search | Neural/semantic via Exa API · requires `EXA_API_KEY` |
| `/tavily` | `<query>` | Search | AI-curated via Tavily · requires `TAVILY_API_KEY` |
| `/firecrawl` | `<url>` | Search | URL→clean markdown · requires `FIRECRAWL_API_KEY` |
| `/memory-recall` | `[query]` | Memory | 3-layer: SQLite cosine → knowledge.db Q&A → obsidian-vault full-text |
| `/memory-scan` | — | Memory | Re-indexes terminal history + git log + notes into `memory.db` |
| `/memory-stats` | — | Memory | Record counts by source (terminal/git/notes) |
| `/memory-context` | `[query]` | Memory | Prints memory block that would be injected into next prompt |
| `/obsidian-search` | `<query>` | Vault | Full-text search across all `.md` files in `obsidian-vault/` |
| `/obsidian-read` | `<path>` | Vault | Read file via obsidian-bridge API `:5056` |
| `/obsidian-write` | `<path>` | Vault | Write file with auto `.bak` backup via bridge |
| `/obsidian-daily` | — | Vault | Open/append today's daily note |
| `/image` | `<path>` | Vision | Analyze image with `minicpm-v:latest` |
| `/screenshot-analyze` | `<path>` | Vision | Alias for `/image` |
| `/run-python` | `[code]` | Exec | Phase 2 rich gate → tempfile → 30s timeout · Phase 4 live heal on error |
| `/run-bash` | `<cmd>` | Exec | Phase 3 risk classify → Phase 2 rich gate → execute · Phase 4 live heal |
| `/run-safe` | `<action>` | Exec | Allowlisted route via Safe Command API `:5055` |
| `/patch-adwi` | `[hint]` | Repair | aider-chat self-heal · snapshots before · per-file rollback on failure |
| `/repair-adwi` | — | Repair | 10-check: syntax, routing, smoke tests |
| `/fix-error` | `[error]` | Repair | Paste error → classify → inspect → aider patch → test |
| `/test-adwi` | — | Repair | `py_compile` + `/model-status` + `/status` + `/capabilities` |
| `/git` | `[status\|log\|diff\|review\|repos]` | Git | Git workspace operations |
| `/backup-now` | `[message]` | Git | Secret scan → stage → commit → push |
| `/backup-status` | — | Git | Health, last commit time, LaunchAgent state |
| `/backup-enable` | — | Git | Init git + install `adwi-git-backup` LaunchAgent |
| `/backup-disable` | — | Git | Unload LaunchAgent |
| `/backup-log` | — | Git | Recent backup commits |
| `/backup-audit` | — | Git | `.gitignore` coverage + secret scan |
| `/nightly-run` | — | System | Trigger 10-step nightly loop immediately (with confirm) |
| `/nightly-status` | — | System | LaunchAgent state + last run time |
| `/nightly-log` | `[n]` | System | Read nth most recent nightly report |
| `/doctor` | — | System | Full health: Ollama + Docker + APIs + syntax |
| `/inspect-system` | — | System | Deep read-only inventory → saves report |
| `/status` | — | System | Stack health (Ollama, Docker, bridge, SearXNG) |
| `/capabilities` | — | System | Show `capabilities.json` registry |
| `/capability-audit` | — | System | Diff registry vs implemented commands |
| `/trusted-roots` | — | Security | Show `allowed-read-roots.txt` |
| `/trust-root` | `<path>` | Security | Append path to allowed roots |
| `/secrets-status` | — | Security | Check `config/.env` key presence (values never shown) |
| `/voice-out` | `[text]` | Voice | TTS via piper-tts `en_US-lessac-medium` |
| `/voice-brief` | — | Voice | Read morning brief aloud |
| `/gmail` | — | Gmail | Unread count via Gmail API |
| `/gmail-read` | — | Gmail | Read recent emails |
| `/gmail-summary` | — | Gmail | Summarise inbox with `adwi:latest` |
| `/gmail-auth` | — | Gmail | OAuth2 flow |
| `/ha` | — | HA | Home Assistant entity states |
| `/notify` | `[message]` | HA | Push notification via HA + iPhone |
| `/mcp` | — | MCP | MCP tool server status |
| `/mcp-setup` | — | MCP | Configure MCP tool servers |
| `/rag` | `<query>` | RAG | Semantic search over local notes index |
| `/rag-index` | — | RAG | Rebuild notes RAG index |
| `/eval-routing` | — | Eval | Run 30 NLU routing test cases |
| `/eval-adwi` | — | Eval | Full eval: smoke + routing + capability audit |
| `/export-training-example` | `[label]` | Training | Save exchange to training data |
| `/training-plan` | — | Training | Fine-tuning readiness report |
| `/extract-ideas` | `[src]` | Ideas | Extract implementable ideas from URL/file/text |
| `/implement-idea` | `[src]` | Ideas | Draft + implement idea with confirmation |
| `/tool-roadmap` | — | Ideas | Planned tool additions roadmap |
| `/trace-log` | `[n]` | Logs | Read nth trace from `notes/adwi-trace-logs/` |
| `/use-local` | — | Model | Switch to `adwi:latest` streaming |
| `/use-cloud` | — | Model | Switch to OpenWebUI/Gemini cloud routing |
| `/model-status` | — | Model | Active routing config |
| `/set-cloud-model` | `<model>` | Model | Set cloud model name |
| `/models` | — | Model | `ollama list` output |
| `/what-next` | — | Planning | AI-suggested next build priorities |
| `/daily-improve` | — | Planning | Daily improvement: tests + journal + sync |
| `/review-plan` | `<plan>` | Planning | Review plan for risks and gaps |
| `/route` | `<query>` | Debug | Show NLU classification result |
| `/disk` | `[path]` | FS | Disk usage analysis |
| `/large-files` | `[path]` | FS | Files over threshold |
| `/old-files` | `[path]` | FS | Files not opened in 1+ year |
| `/duplicates` | `[path]` | FS | Duplicate file detection |
| `/organize` | `[path]` | FS | AI organisation suggestions |
| `/cleanup` | `[path]` | FS | Safe deletion candidates |
| `/read` | `<path>` | FS | Read any file (hard-block list enforced) |
| `/list` | `<path>` | FS | List directory contents |
| `/search` | `<term>` | FS | Search files and content |
| `/inspect-code` | `[file]` | FS | Read + AI-explain source or config file |
| `/add-root` | `<path>` | FS | Add trusted read root |
| `/generate-image` | `<prompt>` | Media | Generate image via LocalAI |
| `/url` | `<url>` | Media | Summarise webpage |
| `/youtube` | `<url>` | Media | Summarise YouTube video |
| `/save-youtube` | `<url>` | Media | Save YouTube summary to notes |
| `/benchmark` | — | Perf | Inference speed benchmark |
| `/sync-knowledge` | — | Knowledge | Sync Open WebUI Knowledge |
| `/inbox` | — | Gmail | Gmail inbox alias |
| `/watcher-status` | — | System | Open WebUI knowledge watcher status |
| `/journal` | — | Memory | View journal file |
| `/mistakes` | — | Memory | View mistakes-and-fixes log |
| `/roadmap` | — | Planning | View capability roadmap |
| `/self-heal` | — | Repair | Auto-repair setup check |
| `/help` | — | Meta | Show help text |
| `/exit` | — | Meta | Quit REPL |
| `/gemini` | `[prompt]` | Cloud | Use Gemini cloud explicitly |
| `/owui` | `[prompt]` | Cloud | Alias for `/gemini` |
| `/cloud` | — | Model | Alias for `/use-cloud` |
| `/local` | — | Model | Alias for `/use-local` |

---

## §4 Agentic Lifecycle Flows

### Flow A — Natural Language REPL Input

```
User types: "summarise the ollama changelog"
        │
        ▼
adwi_cli.py: handle(line)
        │
        ├── Is it a slash command? ──── No
        │                               │
        │                               ▼
        │                    dispatch_natural(line)
        │                               │
        │                 llama3.1:8b classifies intent
        │                 (JSON schema constrained decode)
        │                               │
        │             ┌─────────────────┼──────────────────┐
        │             ▼                 ▼                   ▼
        │        web_search        code_ask           general_chat
        │             │                │                    │
        │        search_web()   adwi:latest (local)  adwi:latest
        │             │         + memory context     streaming
        │     SearXNG+Tavily+Exa
        │             │
        │       adwi:latest synthesis
        │
        └── Output printed · trace saved to notes/adwi-trace-logs/
```

### Flow B — `/reason <task>` LangGraph Execution

```
/reason "set up gmail integration"
        │
        ▼
reason_engine.py: run_reason(task, interactive=True)
        │
        ▼
PlannerAgent ── adwi:latest ──► JSON step array (max 8 steps)
                                [{id, title, action_type, action,
                                  depends_on, success_criteria}]
        │
        ▼  (for each step)
classify_risk(action, action_type)
        │
        ├── BLOCKED ──────────────────► Reject · AchievementLedger.add_blocked()
        │
        ├── REVIEW-REQUIRED ───────────► permission_gate()
        │                                 │
        │                          ╭──────┴──────╮
        │                          │  WHY display │  ← llama3.1:8b one sentence
        │                          │  Action box  │
        │                          │  (y/n)       │
        │                          ╰──────┬──────╯
        │                     n ──► ledger.add_declined()
        │                     y ──► proceed
        │
        └── SAFE ─────────────────────► proceed immediately
                │
                ▼
        executor_agent(step, context, ledger)
                │
                ├── shell      → _exec_shell()       → subprocess + Phase 4
                ├── file_read  → _exec_file_read()   → hard-block check first
                ├── file_write → _exec_file_write()  → hard-block check first
                ├── web_search → _exec_web_search()  → SearXNG :8888
                ├── memory_query → memory.py cosine search
                └── llm_reason → adwi:latest + context injection
                        │
                        ▼  (on runtime error with traceback)
                 ┌──── Phase 4: _live_heal() ──────────────────────────────┐
                 │  Extract workspace .py files from traceback             │
                 │  aider --no-git --yes-always --no-stream <files>        │
                 │  Run: pytest adwi/evals/ or py_compile adwi_cli.py      │
                 │  If pass: retry command once                             │
                 │  ledger.add_heal(error, patched=True, tests_passed=ok)  │
                 └─────────────────────────────────────────────────────────┘
                        │
                        ▼
        CriticAgent(step, output, attempt) ── llama3.1:8b
                │
                ├── PASS  ─► next step
                ├── RETRY ─► re-run executor (max 3 attempts)
                └── FAIL  ─► ledger.add_fail(), skip dependents
                        │
                        ▼  (all steps complete)
        adwi:latest synthesis of step outputs
                        │
                        ▼
        AchievementLedger.render() printed:
          ╭── Achievement Summary ──────────────────────╮
          │  ▶ Commands executed (N)                     │
          │  ✎ Files written (N)                         │
          │  ⚕ Errors caught & healed (N)               │
          │  ⊘ Steps declined by user (N)               │
          ╰──────────────────────────────────────────────╯
```

### Flow C — Voice Input (STT → Dispatch)

```
/listen  (or NLU intent: "listen" / "voice input")
        │
        ▼
voice.py: record_mic()
        │  sox rec -r 16000 -c 1 -b 16 /tmp/adwi-rec.wav
        │  silence 1 0.1 3%  (auto-stops on 3% silence)
        │
        ▼
voice.py: transcribe(audio_path)
        │  faster-whisper base.en · CoreML optimised (M4 Max)
        │
        ▼
handle(transcribed_text)   ← same dispatch as Flow A
        │
        ▼  (if /voice-out or TTS requested)
voice.py: speak(text)
        │  piper-tts en_US-lessac-medium → macOS audio out
```

### Flow D — Mobile Webhook (iPhone → n8n → adwi)

```
Siri Shortcut on iPhone
        │
        ▼  (HTTPS via Cloudflare Tunnel or Tailscale)
n8n :5678  (webhook node)
        │
        ▼
POST http://localhost:5055/<route>
        │  Safe Command API — 8 allowlisted routes only
        │  No arbitrary command execution
        │
        ├── /status-ai ──────────────────► bin/status-ai
        ├── /daily-ai-status-report ──────► nightly.py (report section)
        ├── /auto-ai-maintenance ─────────► nightly.py (full loop)
        ├── /adwi-self-heal ──────────────► aider-chat pass
        ├── /rag-index ───────────────────► overnight_learn.py (index)
        ├── /git-status-workspace ────────► git status + git log
        ├── /index-ai-notes ──────────────► memory-scan
        └── /benchmark-adwi ──────────────► bin/benchmark-adwi
                │
                ▼
        JSON response → n8n → Siri → iPhone notification
```

### Flow E — Nightly 10-Step Maintenance (2 AM)

```
LaunchAgent: com.suneel.adwi-nightly fires at 2:00 AM
        │
        ▼
adwi/nightly.py
        │
        ├── Step 1:  Service health check (Ollama, Docker, APIs)
        ├── Step 2:  Log rotation + cleanup
        ├── Step 3:  Skill discovery (scan notes for new capabilities)
        ├── Step 4:  aider self-heal
        │            snapshot files BEFORE aider
        │            run aider --no-git on watched files
        │            on failure: per-file git checkout -- <file>
        │            failures → "Pending User Approval" in brief
        ├── Step 5:  Eval runs (NLU routing + model quality)
        ├── Step 5b: System health (brew/npm outdated, disk, docker)
        ├── Step 5c: Web research (Ollama, WebUI, n8n, Qdrant, aider)
        ├── Step 6:  Backup sync check
        ├── Step 7:  /memory-scan
        ├── Step 8:  Capability sync → capabilities.json
        ├── Step 8b: Obsidian daily note
        ├── Step 9:  git commit all changes
        └── Step 10: Write ~/Desktop/morning_brief.md
                     ├── Service health
                     ├── System health
                     ├── Web research summaries
                     ├── Memory scan results
                     └── ⚠ Pending User Approval (human-review required)
```

### Flow F — Phase 4 Live Self-Heal (Runtime Error Interception)

```
User approves command via permission_gate()
        │
        ▼
subprocess.run(cmd) or python tempfile exec
        │
        ├── exit 0 ────────────────────────────────► done
        │
        └── exit != 0 AND patchable traceback found
                │
                ▼
        _cli_live_heal(error) / _live_heal(error, ledger)
                │
                ├── Parse traceback for workspace .py paths
                │
                ├── No workspace files → show raw error, stop
                │
                └── Files identified (up to 4):
                        │
                        ▼
                aider --model ollama/adwi:latest
                      --no-git --yes-always --no-pretty
                      --message "[Adwi live self-heal] <error>"
                      <file1> [file2...]
                        │
                        ├── timeout 5 min → show error, stop
                        │
                        └── aider completes
                                │
                                ▼
                        pytest adwi/evals/ -x  OR  py_compile fallback
                                │
                                ├── PASS → retry original command once
                                │          print "✓ Verification passed"
                                │
                                └── FAIL → show partial heal warning
```

---

## §5 Security & Boundary Invariants

### Hard-Blocked Filesystem Paths

These are compile-time constants in `adwi_cli.py` and `reason_engine.py`.
Any access attempt is **rejected with no fallback** — no LLM call, no log.

```
~/.ssh/                    SSH private keys
~/.aws/                    AWS credentials
~/.gnupg/                  GPG keyring
~/.kube/                   Kubernetes configs
~/Library/Keychains/       macOS keychain
~/Library/Passwords/       macOS passwords
~/SuneelWorkSpace/secrets/ Workspace credentials directory
/etc/                      System configuration
/private/                  macOS private namespace
/System/                   macOS system files
```

### Gitignored Sensitive Patterns

The following **can never be committed**:

```
secrets/                            entire directory
**/.env                             all .env files
**/*token* **/*secret* **/*credentials*  named patterns
**/*.pem *.p12 *.pfx *.key          TLS / crypto files
**/id_rsa **/id_ed25519             SSH private keys
**/.netrc **/.npmrc                 auth config files
**/gmail-token.json                 OAuth tokens
**/google-token.json                OAuth tokens
adwi/memory.db                      contains terminal history
adwi/knowledge.db                   indexed workspace content
local-ai-stack/*-data/              Docker runtime
local-ai-stack/homeassistant-data/  HA runtime database + logs
config/.env                         API keys (Tavily, Exa, Firecrawl, HA, CF)
```

### Secret Handling Invariants

| Invariant | Mechanism |
|---|---|
| API keys never appear in prompts | Loaded from `config/.env` as opaque env vars; passed as HTTP headers only |
| No token printing | `redact()` strips known key patterns before any log write |
| Memory DB never committed | `adwi/memory.db` gitignored; contains terminal history |
| No credentials in traces | `notes/adwi-trace-logs/` written through `redact()` |
| Nightly loop never auto-upgrades | Upgrade suggestions → `Pending User Approval` section only |
| aider never touches secret files | Hard-block list validated before any file is passed to aider |
| All mutations require gate | REVIEW-REQUIRED tier blocks: `git commit/push`, `rm -r`, `chmod`, `docker compose down` |

### Phase 3 Risk Classification

Enforced by `_classify_cli_risk()` (adwi_cli.py) and `classify_risk()` (reason_engine.py):

| Tier | Triggered by | Response |
|---|---|---|
| `BLOCKED` | `rm -rf`, `git push --force`, `DROP TABLE`, paths under `/etc/`, `secrets/`, `~/.ssh`, `~/.aws` | Hard reject, no prompt shown |
| `BLOCKED` | `payment`, `bank transfer`, `crypto wallet`, `wire transfer`, `venmo`, `paypal` | Hard reject |
| `REVIEW-REQUIRED` | `git commit`, `git push`, `docker compose down/rm`, `brew uninstall`, `pip uninstall`, `rm -r`, `chmod`, `chown`, `pkill`, `launchctl load/unload` | Phase 2 permission gate with WHY explanation |
| `REVIEW-REQUIRED` | Any `file_write` or `obsidian_write` action type | Phase 2 permission gate |
| `SAFE` | All other commands | Simple `Run this? (y/n)` confirmation |

---

## §6 Directory Structure

```
SuneelWorkSpace/
│
├── adwi/                              # Core AI brain
│   ├── adwi_cli.py                    # 5,000+ lines · 103 commands · REPL entry point
│   ├── reason_engine.py               # LangGraph: Planner→Executor→Critic (822 lines)
│   ├── memory.py                      # AdwiMemory: SQLite + nomic-embed cosine search
│   ├── nightly.py                     # 10-step 2 AM maintenance loop
│   ├── overnight_learn.py             # 7-hour knowledge indexer (1 AM via launchd)
│   ├── repair.py                      # Self-repair utilities
│   ├── backup.py                      # Backup orchestration
│   ├── voice.py                       # STT (faster-whisper) + TTS (piper-tts)
│   ├── gmail_helper.py                # Gmail OAuth2 + API integration
│   ├── Modelfile                      # Custom adwi:latest definition (qwen3:30b base)
│   ├── capabilities.json              # Machine-readable capability registry
│   ├── allowed-read-roots.txt         # Trusted filesystem roots
│   ├── .venv/                         # [gitignored] Python 3.14 virtualenv (uv)
│   ├── memory.db                      # [gitignored] Semantic memory (380+ items)
│   └── knowledge.db                   # [gitignored] Q&A pairs (1,565+) + chunks
│
├── bin/                               # 35 helper scripts
│   ├── adwi                           # Launcher (uses .venv python if available)
│   ├── auto-update-readme             # README auto-injection pipeline
│   ├── start-obsidian-bridge          # Start bridge (:5056)
│   ├── stop-obsidian-bridge           # Stop bridge
│   ├── start-phoenix                  # Start Arize Phoenix (:6006)
│   ├── start-homeassistant            # Start Home Assistant (:8123)
│   ├── status-ai                      # All service statuses
│   ├── adwi-git-backup                # 30-min auto-backup script
│   └── ...                            # 27 more scripts
│
├── local-ai-stack/
│   ├── docker-compose.yml             # 12 containers (§2)
│   └── monitoring/                    # Prometheus, Loki, Promtail, Grafana configs
│
├── mcp-servers/
│   ├── obsidian-bridge/
│   │   ├── server.py                  # stdlib-only vault HTTP API (:5056)
│   │   ├── start.sh / stop.sh
│   └── [playwright, github, sqlite, memory via npx]
│
├── local-command-api/
│   └── server.py                      # Safe Command API (:5055) · 8 allowlisted routes
│
├── obsidian-vault/                    # Markdown knowledge base (git-tracked)
│   ├── knowledge/                     # Architecture, troubleshooting, guardrails
│   ├── daily-notes/                   # Written nightly by nightly.py
│   ├── automations/                   # Loop design docs
│   ├── projects/                      # Active project notes
│   └── prompts/                       # System prompts for Open WebUI
│
├── config/
│   └── .env                           # [gitignored] Tavily, Exa, Firecrawl, HA, CF tokens
│
├── notes/                             # AI learning journal + logs
│   ├── ADWI-START-HERE.md
│   ├── adwi-trace-logs/               # Per-action execution traces
│   ├── git-backup-logs/               # Per-backup git logs
│   └── adwi-repair-logs/              # aider pre-flight records
│
├── logs/
│   └── adwi_system_log.md             # Append-only engineering change log
│
├── secrets/                           # [gitignored entirely]
├── .gitignore                         # See §5 for credential exclusion list
└── README.md                          # This file — auto-updated by bin/auto-update-readme
```

---

## §7 Rollback & Recovery

### Single File Rollback

```bash
git log --oneline adwi/adwi_cli.py
git checkout <hash> -- adwi/adwi_cli.py
python3 -m py_compile adwi/adwi_cli.py && echo "syntax OK"
```

### Full Service Restart

```bash
# Docker stack
cd ~/SuneelWorkSpace/local-ai-stack
docker compose down && docker compose up -d

# Obsidian bridge
mcp-servers/obsidian-bridge/stop.sh && mcp-servers/obsidian-bridge/start.sh

# Reload all LaunchAgents
for plist in ~/Library/LaunchAgents/com.suneel.*.plist; do
  launchctl unload "$plist" 2>/dev/null; launchctl load "$plist"
done

# Ollama
brew services restart ollama
```

### Rebuild Gitignored Databases

```bash
# knowledge.db (~7 hours — normally via launchd at 1 AM)
nohup python3 ~/SuneelWorkSpace/adwi/overnight_learn.py \
  > /tmp/overnight-learn.log 2>&1 &

# memory.db (~2 minutes)
echo "/memory-scan
/exit" | python3 adwi/adwi_cli.py
```

### Full System Validation

```bash
python3 -m py_compile adwi/adwi_cli.py        && echo "cli OK"
python3 -m py_compile adwi/reason_engine.py   && echo "reason_engine OK"
python3 -m py_compile adwi/nightly.py         && echo "nightly OK"
python3 -m py_compile adwi/overnight_learn.py && echo "overnight OK"
python3 -m py_compile mcp-servers/obsidian-bridge/server.py && echo "bridge OK"
curl -s http://localhost:11434/api/tags | python3 -c \
  "import sys,json; print('Ollama OK:', len(json.load(sys.stdin)['models']), 'models')"
curl -s http://localhost:5056/ | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('Bridge OK:', d['status'])"
curl -s "http://localhost:8888/search?q=test&format=json" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('SearXNG OK:', len(d.get('results',[])), 'results')"
```

### aider Manual Self-Heal

```bash
~/.local/bin/aider \
  --model ollama/adwi:latest \
  --no-git --yes-always --no-pretty \
  adwi/adwi_cli.py adwi/memory.py adwi/nightly.py

python3 -m py_compile adwi/adwi_cli.py && echo "still compiles"
```

---

## §8 Architecture Implementation Phases

<!-- AUTO:PHASES -->
| Phase | Title | Key Behaviour | Primary Files |
|---|---|---|---|
| 1 | Heavyweight Infrastructure Observability | Prometheus :9090, Loki :3100, Grafana :4000, node-exporter, cAdvisor | `local-ai-stack/docker-compose.yml` |
| 2 | LangGraph Orchestration & Interactive Permission Surface | Planner→Executor→Critic state machine; Phase 2 boxed gate with WHY explanation | `adwi/reason_engine.py` |
| 3 | Memory Lifecycle, Scoring & Safety Gate | importance_score, recency_decay, provenance columns; BLOCKED/REVIEW/SAFE classifier | `adwi/memory.py` |
| 4 | Real-Time Self-Healing & Hermes Skill Compiling | aider non-interactive patch → pytest verify → skills/ SKILL.md; skill pre-flight match | `adwi/reason_engine.py · skills/` |
| 5 | prompt_toolkit Slash-Command Autocomplete | 104-command registry; substring fuzzy scoring; Tab/arrow REPL overlay | `adwi/adwi_cli.py (SlashCommandCompleter)` |
| 6 | Chain-of-Intent Schema & Semantic Slot-Filling | analysis+confidence+intent+arguments JSON schema; 29 structured arg reads in dispatch | `adwi/adwi_cli.py (_INTENT_JSON_SCHEMA)` |
| 7 | Qdrant-Driven Dynamic Few-Shot Routing | 49-fixture nlu_fixtures collection; top-3 injected into llama3.1:8b system prompt | `adwi/memory.py · Qdrant :6333` |
| 8 | LLM-Priming Documentation Update Invariants | auto-update-readme always runs before backup; PHASES+NLU sections auto-injected | `bin/auto-update-readme · adwi/backup.py` |

All 8 phases verified on 2026-06-15. Each phase committed atomically as an independent transactional unit.
*Auto-updated: 2026-06-15*
<!-- /AUTO:PHASES -->

---

## Getting Started

```bash
# 1. Start Docker services
cd ~/SuneelWorkSpace/local-ai-stack && docker compose up -d && cd ..

# 2. Start Obsidian bridge (if not already via launchd)
bin/start-obsidian-bridge

# 3. Launch adwi
bin/adwi
# or: python3 adwi/adwi_cli.py

# 4. Verify everything
/doctor
```

See `notes/ADWI-START-HERE.md` for detailed first-time setup.

---

*Auto-backed up every 30 minutes · README sections auto-updated by `bin/auto-update-readme` on every commit.*
