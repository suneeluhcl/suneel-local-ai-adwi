# SuneelWorkSpace

**Operator:** Suneel Bikkasani · **Hardware:** Apple M4 Max 64 GB · **OS:** macOS 15

Personal AI engineering workspace. Three active projects live here as independent git repos:
Adwi (local AI OS, running), iHelper (interview prep assistant, in design), and Tailor (resume editor, in design).
All new projects use the Claude API — not local models.

---

## Workspace Map

| Directory | Repo | Status | Purpose |
|-----------|------|--------|---------|
| `adwi/` | private | **Active** | Local AI operating system — terminal REPL, 115 NLU intents, 193 commands, overnight self-improvement loop |
| `iHelper/` | private | **In design** | AI interview prep assistant — practice sessions, question banks, real-time feedback |
| `tailor/` | private | **In design** | AI resume editor — tailors resume to a job posting, keyword optimization, formatting |
| `local-ai-stack/` | — | infra | Docker compose for Ollama, n8n, and local services |
| `obsidian-vault/` | — | personal | Personal knowledge base (Obsidian) |

---

## iHelper — Interview Preparation Assistant

**One-line pitch:** A Claude-powered AI coach that runs mock interviews, scores your answers, and adapts to the specific company and role you're targeting.

**Core capabilities (planned):**
- Load a job description → generate a tailored question bank (behavioral + technical)
- Run a mock interview session: ask → record answer → score → give structured feedback
- Track performance across sessions (confidence, clarity, completeness)
- Company-specific prep: surface known interview styles for FAANG, startups, consulting
- Export a prep report: what to study, what to practice, what you're strong in

**Tech stack:**
- Backend: Python, Claude API (`claude-sonnet-4-6` for coaching, `claude-haiku-4-5` for scoring)
- Storage: SQLite (sessions, scores, question banks)
- Interface: Terminal CLI first, web UI later
- No local models — Claude API only

**Key design constraints:**
- Sessions must be resumable (save progress mid-prep)
- Scoring must be explainable (not just a number — tell the user why)
- Question bank must be regeneratable per job posting (not static)

---

## Tailor — AI Resume Editor

**One-line pitch:** Paste a job description, paste your resume — Tailor rewrites and scores every bullet point to maximize relevance and ATS keyword coverage.

**Core capabilities (planned):**
- Parse resume (PDF or plain text) + job description
- Score each resume section against the job posting (0–100 relevance)
- Rewrite weak bullets using strong action verbs and job-specific keywords
- Identify missing skills/keywords from the posting that could be added honestly
- Output clean, formatted resume (Markdown → PDF)
- Diff view: show original vs. tailored so the user stays in control

**Tech stack:**
- Backend: Python, Claude API (`claude-sonnet-4-6` for rewrites, `claude-haiku-4-5` for scoring)
- Storage: SQLite (resume versions, job postings, edit history)
- Interface: Terminal CLI first, web UI later
- PDF parsing: `pypdf` or `pdfminer`; PDF output: `weasyprint` or `reportlab`
- No local models — Claude API only

**Key design constraints:**
- Never fabricate experience — rewrites must stay truthful to the original
- Version everything — user can roll back any edit
- Diff view is mandatory, not optional

---

## Instructions for Copilot (Prompt Engineer Mode)

> You are acting as a prompt engineer for Suneel. Your job is to write prompts that Suneel pastes into **Claude Code** (the Claude CLI, `claude` in terminal) to make progress on `iHelper` or `tailor`. Claude Code has full filesystem access, can run shell commands, read/write files, and call the Claude API.

**When asked for a "starter prompt" for either project:**
1. Write the prompt as if you are briefing a senior engineer (Claude) who is starting cold on the project
2. Include: the project goal, the first file/module to create, the exact tech stack, and what "done" looks like for this session
3. Reference the project brief above for constraints (especially: no local models, no fabrication in Tailor, explainable scoring in iHelper)
4. Suggest a first concrete deliverable (e.g. "by end of this session, `cli.py` runs a 5-question mock interview loop and saves the session to SQLite")
5. Keep prompts under 400 words — Claude Code works better with focused scope

**When asked for a "next step prompt"** (continuing from a prior session):
1. Start with "Read the current state of [file] to orient yourself"
2. State what was built last session and what the next milestone is
3. End with a clear acceptance criterion

**Prompt format to use:**
```
[Project]: [iHelper | Tailor]
[Session goal]: one sentence
[Context]: what exists, what was built last time (if any)
[Task]: what to build this session, in priority order
[Done when]: the specific output / behavior that signals session success
[Constraints]: any hard rules (from the project brief above)
```

---

## Claude Code Tips (for Suneel)

- Start every project session: `cd ~/SuneelWorkSpace/iHelper` or `cd ~/SuneelWorkSpace/tailor`, then `claude`
- Claude Code reads `CLAUDE.md` in the current directory automatically — keep one per project
- Set `ANTHROPIC_API_KEY` in each project's `.env` (gitignored)
- Prefer `claude-sonnet-4-6` for heavy reasoning, `claude-haiku-4-5-20251001` for fast scoring loops

---

# Adwi — Local AI Operating System · LLM System Blueprint

> **PRIMING CONTEXT FOR EXTERNAL MODELS:** This document is the primary architectural blueprint.
> Sections marked `<!-- AUTO:... -->` are machine-generated from authoritative code/config sources and
> are kept current by `bin/auto-update-readme`. Static narrative sections (§6 directory tree, §7–§10)
> are manually maintained and may lag slightly. For ground truth, prefer code over docs.
> For the compact, unambiguous priming reference see `docs/LLM_SYSTEM_PRIMING.md`.
>
> **OPERATOR:** Suneel Bikkasani · **HARDWARE:** Apple M4 Max 64 GB unified RAM · **OS:** macOS 15
> **REPO:** `~/SuneelWorkSpace/` · **ENTRY POINT:** `bin/adwi` → `python3 adwi/adwi_cli.py`

---

## Table of Contents

| § | Section | Purpose |
|---|---|---|
| [§1](#1-system-dna--model-matrix) | System DNA & Model Matrix | Hardware, models, NLU pipeline |
| [§2](#2-infrastructure-topography) | Infrastructure Topography | Every port, container, agent, data flow |
| [§3](#3-deterministic-capability-grid) | Deterministic Capability Grid | All 193+ commands, args, behaviors |
| [§3a](#3a-gmail-capability-surface) | Gmail Capability Surface | Full Gmail feature inventory — read/write/draft/send/schedule/rules |
| [§4](#4-agentic-lifecycle-flows) | Agentic Lifecycle Flows | ASCII diagrams of every execution path (Flows A–G) |
| [§5](#5-security--boundary-invariants) | Security & Boundary Invariants | Hard blocks, credential isolation, API auth status |
| [§6](#6-directory-structure) | Directory Structure | Annotated file tree |
| [§7](#7-rollback--recovery) | Rollback & Recovery | Operational runbooks |
| [§8](#8-architecture-implementation-phases) | Architecture Implementation Phases | Phase 1–10 status and key files |
| [§9](#9-simlab-operational-guide) | SimLab Operational Guide | Running the eval harness; improvement tiers; golden baseline |
| [§10](#10-nlu-eval-status--repair-backlog) | NLU Eval Status & Repair Backlog | Current pass rates, full improvement history, remaining gaps |
| [§11](#11-new-machine-bootstrap) | New Machine Bootstrap | Clone to working Adwi in one session |

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
*Auto-updated: 2026-06-24*
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
| 2 | Few-shot injection | Qdrant `nlu_fixtures` top-3 semantic matches (96 fixtures, 768-dim Cosine) |
| 3 | LLM classification | `llama3.1:8b` with JSON schema — `analysis`+`confidence`+`intent`+`arguments` (115 intent classes) |
| 4 | Argument dispatch | 29 typed slot reads: `path`, `query`, `url`, `size_mb`, `days`, `description` |
| 5 | Fallback | `qwen3:0.6b` (80-token budget, no analysis block) |

**Schema fields (Phase 6):**
- `analysis` — dense one-sentence reasoning before intent selection
- `confidence` — float 0.0–1.0
- `intent` — one of 115 registered intent classes
- `arguments` — typed key-value slots fed straight into command handlers

**Qdrant few-shot collection:** `nlu_fixtures` · 96 seed fixtures · scored at `score_threshold=0.5` · provisioned via `python3 adwi/memory.py provision-nlu`
*Auto-updated: 2026-06-24*
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
| :5056 | Obsidian Bridge | Host (LaunchAgent) | Vault HTTP CRUD API |
| :5678 | n8n | Docker | Workflow automation / webhooks |
| :6006 | Arize Phoenix | Host (LaunchAgent) | Agent observability UI (OTel) |
| :6333 | Qdrant | Docker (LaunchAgent start) | Vector database — suneel-qdrant container, started by LaunchAgent |
| :8123 | Home Assistant | Docker | iPhone control plane |
| :8888 | SearXNG | Docker | Private local web search |
| :9090 | Prometheus | Docker | Metrics scraper |
| :3100 | Loki | Docker | Log aggregation |
| :4000 | Grafana | Docker | Monitoring dashboards |
| :9100 | node-exporter | Docker | Host system metrics |
| :9101 | cAdvisor | Docker | Container metrics |
| :4317 | Phoenix gRPC | Host (LaunchAgent) | OTLP gRPC ingestion |
| :4318 | Phoenix HTTP | Host (LaunchAgent) | OTLP HTTP ingestion |
*Auto-updated: 2026-06-24*
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
*Auto-updated: 2026-06-24*
<!-- /AUTO:SERVICES -->

### macOS LaunchAgents

All managed at `~/Library/LaunchAgents/com.suneel.*.plist`.

<!-- AUTO:AGENTS -->
| Agent | Schedule |
|---|---|
| `adwi-autoresearch-night` | 23:00 AM |
| `adwi-git-backup` | every 30min |
| `adwi-nightly` | 2:00 AM |
| `adwi-scheduled-send` | every 2min |
| `caffeinate` | KeepAlive |
| `command-api` | KeepAlive |
| `obsidian-bridge` | KeepAlive |
| `openwebui-knowledge-watcher` | KeepAlive |
| `phoenix` | KeepAlive |
| `qdrant` | on demand |
| `telegram-bridge` | KeepAlive |
*Auto-updated: 2026-06-24*
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
     ├── Telegram (outbound poll) ──── telegram-bridge/bot.py ──────┤
     │                                (sender + command allowlist)  │
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
*Auto-updated: 2026-06-24*
<!-- /AUTO:MONITORING -->

---

## §3 Deterministic Capability Grid

<!-- AUTO:COMMANDS -->
**193 registered commands.** Key groups:

**add**: `/add-capability-plan`  `/add-root`
**assistant**: `/assistant-upgrade-status`
**backup**: `/backup-audit`  `/backup-disable`  `/backup-enable`  `/backup-log`  `/backup-now`  `/backup-status`
**benchmark**: `/benchmark`
**browse**: `/browse`
**browser**: `/browser-delegate`  `/browser-delegate-dry-run`
**capabilities**: `/capabilities`
**capability**: `/capability-audit`  `/capability-status`
**cleanup**: `/cleanup`
**clear**: `/clear-context`
**cloud**: `/cloud`
**cmd**: `/cmd`
**confirm**: `/confirm`
**context**: `/context-size`
**daily**: `/daily-brief`  `/daily-improve`
**disk**: `/disk`
**doctor**: `/doctor`
**duplicates**: `/duplicates`
**e2e**: `/e2e-auto-loop`  `/e2e-auto-loop-cancel`  `/e2e-auto-loop-report`  `/e2e-auto-loop-status`
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
**gmail**: `/gmail`  `/gmail-add-bcc`  `/gmail-add-cc`  `/gmail-archive`  `/gmail-attach`  `/gmail-attachments`  `/gmail-auth`  `/gmail-cancel`  `/gmail-cancel-draft`  `/gmail-cancel-followup`  `/gmail-cancel-scheduled`  `/gmail-category`  `/gmail-compose`  `/gmail-confirm`  `/gmail-delete-draft`  `/gmail-draft-reply`  `/gmail-drafts`  `/gmail-extract-tasks`  `/gmail-followup`  `/gmail-followups`  `/gmail-forward`  `/gmail-mark-read`  `/gmail-mark-unread`  `/gmail-open`  `/gmail-open-draft`  `/gmail-open-scheduled`  `/gmail-promos`  `/gmail-read`  `/gmail-remove-attachment`  `/gmail-reschedule`  `/gmail-rewrite`  `/gmail-rule`  `/gmail-rule-apply`  `/gmail-rule-cancel`  `/gmail-rules`  `/gmail-save-attachment`  `/gmail-schedule`  `/gmail-scheduled`  `/gmail-send-draft`  `/gmail-show-draft`  `/gmail-social`  `/gmail-spam`  `/gmail-summarize`  `/gmail-summarize-attachment`  `/gmail-summary`  `/gmail-tasks-remind`  `/gmail-tasks-save`  `/gmail-thread`  `/gmail-thread-intel`  `/gmail-trash`  `/gmail-triage`  `/gmail-undo`  `/gmail-update-subject`
**ha**: `/ha`
**help**: `/help`
**image**: `/image`  `/image-save`
**implement**: `/implement-idea`
**inbox**: `/inbox`
**inspect**: `/inspect-code`  `/inspect-system`
**journal**: `/journal`
**large**: `/large-files`
**learn**: `/learn-from-last-error`
**list**: `/list`
**listen**: `/listen`
**local**: `/local`
**mcp**: `/mcp`  `/mcp-setup`
**memory**: `/memory-context`  `/memory-curate`  `/memory-recall`  `/memory-scan`  `/memory-stats`
**mistakes**: `/mistakes`
**model**: `/model-status`
**models**: `/models`
**new**: `/new-session`
**nightly**: `/nightly-log`  `/nightly-run`  `/nightly-status`
**notify**: `/notify`
**obsidian**: `/obsidian-capture`  `/obsidian-daily`  `/obsidian-help`  `/obsidian-plan`  `/obsidian-plan-clear`  `/obsidian-promote-idea`  `/obsidian-read`  `/obsidian-review`  `/obsidian-review-save`  `/obsidian-search`  `/obsidian-status`  `/obsidian-validate`  `/obsidian-write`
**old**: `/old-files`
**organize**: `/organize`
**owui**: `/owui`
**patch**: `/patch-adwi`
**rag**: `/rag`  `/rag-index`
**read**: `/read`
**reason**: `/reason`
**remote**: `/remote`  `/remote-status`
**repair**: `/repair-adwi`
**repo**: `/repo-private`  `/repo-public`
**research**: `/research`  `/research-save`
**reset**: `/reset-context`
**review**: `/review-plan`
**roadmap**: `/roadmap`
**route**: `/route`
**run**: `/run-bash`  `/run-python`  `/run-safe`
**save**: `/save-youtube`
**screenshot**: `/screenshot-analyze`
**search**: `/search`
**secrets**: `/secrets-status`
**self**: `/self-heal`
**session**: `/session-history`
**set**: `/set-cloud-model`
**status**: `/status`
**sync**: `/sync-knowledge`
**tailscale**: `/tailscale`
**tavily**: `/tavily`
**tech**: `/tech-radar`
**test**: `/test-adwi`
**tool**: `/tool-roadmap`
**trace**: `/trace-log`
**training**: `/training-plan`
**trust**: `/trust-root`
**trusted**: `/trusted-roots`
**url**: `/url`
**use**: `/use-cloud`  `/use-local`
**voice**: `/voice`  `/voice-brief`  `/voice-in`  `/voice-out`
**watcher**: `/watcher-status`
**web**: `/web-search`
**what**: `/what-next`
**youtube**: `/youtube`
*Auto-updated: 2026-06-24*
<!-- /AUTO:COMMANDS -->

### Full Command Reference

| Command | Args | Category | Behavior & Dependencies |
|---|---|---|---|
| `/ask` | `<question>` | Chat | Streams answer from `adwi:latest` · 131K ctx |
| `/chat` | `<message>` | Chat | Conversational mode with memory injection |
| `/reason` | `<task>` | Agentic | LangGraph Planner→Executor→Critic · `reason_engine.py` · Achievement Summary on completion |
| `/web-search` | `<query>` | Search | Shared orchestrator: SearXNG + optional Brave/Tavily/Exa · canonical dedupe · cache · rerank · synthesised by `adwi:latest` |
| `/browse` | `<url> [question]` | Search | Shared fetch chain: Firecrawl → optional Jina Reader → Playwright → urllib |
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

## §3a Gmail Capability Surface

Gmail integration is implemented in `adwi/gmail_helper.py` (864 lines) and dispatched via `adwi/adwi_cli.py`. Auth uses OAuth2 `gmail.modify` scope (token stored in `secrets/gmail-token.json`, gitignored). All mailbox mutations follow a **preview→confirm** model: the action is shown in full before any change is made. Sends require explicit `/gmail-send-draft` or `/gmail-confirm` — there is no auto-send path.

A background `adwi-scheduled-send` LaunchAgent (runs every 2 min) watches a local JSON queue to deliver scheduled messages at the requested time without keeping Adwi REPL open.

### Read & Search

| Command | What it does |
|---|---|
| `/gmail` | Unread count + quick inbox summary |
| `/gmail-read` | List recent inbox messages with metadata |
| `/gmail-summary` | AI-synthesised inbox summary (`adwi:latest`) |
| `/gmail-thread <query>` | Display a full email thread |
| `/gmail-thread-intel` | Extract action items, decisions, reply-needed status, latest delta from a thread |
| `/gmail-social` | List Social category messages |
| `/gmail-promos` | List Promotions category messages |
| `/gmail-spam` | List Spam folder |
| `/inbox` | Alias for `/gmail-read` |

### Triage & Analysis

| Command | What it does |
|---|---|
| `/gmail-triage` | AI-driven triage: reads inbox with extended metadata, classifies action-needed vs FYI vs noise |
| `/gmail-summarize` | Summarise a specific email by ID/subject |
| `/gmail-summarize-attachment` | Summarise content of an email attachment (PDF, text, etc.) |
| `/gmail-extract-tasks` | Extract tasks, deadlines, action items, decisions from an email or thread |

### Draft Management

| Command | What it does |
|---|---|
| `/gmail-drafts` | List all drafts (flags scheduled, shows attachment status) |
| `/gmail-show-draft` | Display a draft's full content before sending |
| `/gmail-open-draft <ref>` | Open a specific draft for editing/review |
| `/gmail-compose <to> <subject> <body>` | Create a new draft (preview shown before saving) |
| `/gmail-draft-reply` | Create a reply draft to the active thread |
| `/gmail-forward` | Create a forward draft |
| `/gmail-rewrite` | Rewrite the active draft for tone, clarity, or brevity via `adwi:latest` |
| `/gmail-update-subject` | Update the subject line on the active draft |
| `/gmail-add-cc <address>` | Add CC recipient to active draft |
| `/gmail-add-bcc <address>` | Add BCC recipient to active draft |
| `/gmail-attach <path>` | Attach a local file to the active draft (MIME multipart) |
| `/gmail-remove-attachment <ref>` | Remove an attachment from the active draft |
| `/gmail-cancel-draft` | Cancel and discard the active draft |
| `/gmail-delete-draft <ref>` | Permanently delete a draft by ID/ref |

### Sending

| Command | What it does |
|---|---|
| `/gmail-send-draft` | Explicitly send the active draft (confirmation shown first) |
| `/gmail-confirm` | Confirm a pending Gmail mutation (send, archive, trash) |

Recipient names are resolved via `resolve_contact()` — contacts, recent senders, aliases. Disambiguation prompt shown when multiple matches exist.

### Scheduled Send

| Command | What it does |
|---|---|
| `/gmail-scheduled` | List all pending scheduled sends (queued locally) |
| `/gmail-open-scheduled <ref>` | Preview a scheduled draft before delivery |
| `/gmail-reschedule <ref> <when>` | Move a scheduled send to a new time |
| `/gmail-cancel-scheduled <ref>` | Cancel a scheduled send before it fires |

Supports natural-language time: "tomorrow morning", "Friday at 3pm", "in 2 hours". Stored in a local JSON queue; delivered by the `adwi-scheduled-send` LaunchAgent (every 2 min).

### Follow-up Reminders

| Command | What it does |
|---|---|
| `/gmail-followup` | Set a follow-up reminder on the active thread ("remind me in 3 days if no reply") |
| `/gmail-followups` | List all active follow-up reminders |
| `/gmail-cancel-followup <ref>` | Cancel a follow-up reminder |
| `/gmail-tasks-remind` | Remind about saved Gmail tasks |

Follow-ups are stored locally and surfaced at reminder time via Adwi or morning brief.

### Mutations (preview→confirm)

| Command | What it does |
|---|---|
| `/gmail-archive <ref>` | Archive one or more messages (preview before executing) |
| `/gmail-trash <ref>` | Trash messages (preview before executing) |
| `/gmail-mark-read <ref>` | Mark messages as read |
| `/gmail-mark-unread <ref>` | Mark messages as unread |
| `/gmail-undo` | Undo the last Gmail mutation (archive/trash/mark) |

### Attachments (Incoming)

| Command | What it does |
|---|---|
| `/gmail-attachments` | List all attachments in the current message or thread |
| `/gmail-save-attachment <ref>` | Save an attachment to local disk (with path confirmation) |

Attachment metadata: `filename`, `mime_type`, `size`, `attachment_id`. Supports per-message and per-thread listing.

### Rules & Filters

| Command | What it does |
|---|---|
| `/gmail-rules` | List active Gmail filters/rules |
| `/gmail-rule <description>` | Propose a new rule (preview before applying) |
| `/gmail-rule-apply <ref>` | Apply a proposed rule to existing mail and create a Gmail filter |
| `/gmail-rule-cancel` | Discard a pending rule proposal |

Rules use `apply_rule_to_existing()` + `create_filter_native()` — both add Gmail server-side filters and apply labels/archive retroactively.

### Task Extraction & Saving

| Command | What it does |
|---|---|
| `/gmail-extract-tasks` | Extract action items, deadlines, dates from an email/thread |
| `/gmail-tasks-save` | Save extracted tasks to Obsidian daily note or notes file |
| `/gmail-tasks-remind` | Surface saved task reminders |

### Auth

| Command | What it does |
|---|---|
| `/gmail-auth` | Run OAuth2 flow (or re-auth if scope changed) |

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
        │     SearchOrchestrator
        │     SearXNG + optional Brave/Tavily/Exa
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
        │  Safe Command API — 26 allowlisted routes (+ 1 background E2E Popen route)
        │  X-Adwi-Secret header required; no arbitrary command execution
        │
        ├── /status-ai · /daily-ai-status-report · /index-ai-notes ──► shell scripts
        ├── /auto-ai-maintenance · /adwi-self-heal · /rag-index ──────► shell scripts
        ├── /git-status-workspace · /benchmark-adwi ───────────────────► shell scripts
        ├── /adwi-status · /adwi-doctor · /adwi-brief ─────────────────► adwi_cli.py
        ├── /adwi-backup · /adwi-nightly · /adwi-models ───────────────► adwi_cli.py
        ├── /adwi-watcher-status · /adwi-daily-brief-n8n ──────────────► adwi_cli.py
        ├── /adwi-config-check · /adwi-eval-status · /adwi-disk-summary ► bin scripts (observability)
        ├── /adwi-ports · /adwi-nightly-status · /adwi-version · /adwi-uptime ► bin scripts
        ├── /adwi-e2e-auto-loop-status · -report · -cancel ────────────► status reader
        └── /adwi-e2e-auto-loop-start ──────────────────────────────────► Popen (background)
                │
                ▼
        JSON response → n8n → Siri → iPhone notification
```

### Flow G — Telegram Bridge (Telegram → adwi)

```
Telegram app on any device
        │
        ▼  (outbound HTTPS long-poll to api.telegram.org:443 — no public endpoint)
bot.py: getUpdates loop
        │
        ├── Sender check ──────── not in TELEGRAM_ALLOWED_USER_ID → silently drop
        │
        ├── Command parse ─────── not in TELEGRAM_COMMANDS dict → usage hint
        │
        └── 9 commands mapped to Safe Command API routes:
              /ping          → local pong (no API call)
              /help          → list all commands
              /daily-brief   → /adwi-daily-brief-n8n  (plain-text formatted)
              /config        → /adwi-config-check      (env var names only)
              /disk          → /adwi-disk-summary
              /eval-status   → /adwi-eval-status       (NLU pass rate)
              /nightly-status → /adwi-nightly-status
              /ports         → /adwi-ports
              /uptime        → /adwi-uptime
              /version       → /adwi-version
                │
                ▼
        POST http://127.0.0.1:5055/<route>   ← X-Adwi-Secret header attached
                │
                ▼
        Safe Command API (:5055) executes allowlisted command
                │
                ▼
        Response truncated to 4000 chars → sendMessage → Telegram
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

### API / Service Auth Status (current-machine)

| Service | Port | Auth state | Mechanism | Remaining work |
|---|---|---|---|---|
| Safe Command API | :5055 | **✅ LIVE** | `X-Adwi-Secret` header (64-char hex from `config/.env`); 401 without correct header | — |
| Telegram Bridge | outbound | **✅ LIVE** | Sender allowlist (`TELEGRAM_ALLOWED_USER_ID`) + command allowlist (9 cmds) + Safe Command API gate; unknown senders silently dropped | — |
| Obsidian Bridge | :5056 | ⚠️ No auth | stdlib HTTP, loopback-only | Auth header pending (same pattern) |
| Ollama | :11434 | No auth | Loopback-only by default | — |
| Grafana | :4000 | Weak | Default fallback password set | Harden password |
| Open WebUI | :3000 | ⚠️ Signup open | Any local user can create account | Disable signup |
| Docker services | Various | No auth | Bound to Docker bridge network, not host LAN | Bind host ports to 127.0.0.1 |

**Safe Command API auth detail:** `ADWI_LOCAL_SECRET` (64-char hex) lives in `config/.env` (gitignored). All callers (n8n workflows, open-webui tools, adwi-sandbox) were patched 2026-06-16 to send the header. Unauthenticated requests get `{"error": "Unauthorized — X-Adwi-Secret header required"}` (HTTP 401). Live verification passed: no header → 401, wrong header → 401, correct header → 200.

**Loopback posture:** Safe Command API and Obsidian Bridge are bound to `127.0.0.1`. Docker containers reach Safe Command API via `host.docker.internal`. No external network exposure by design — Cloudflare Tunnel and Tailscale handle any intentional remote access.

**Gmail explicit-send model:** All send/archive/trash operations require explicit user confirmation. There is no auto-send path. The `adwi-scheduled-send` LaunchAgent sends drafts from a local queue at the user's requested time, but the draft was explicitly scheduled by the user.

### Hard-Blocked Filesystem Paths

These are compile-time constants in `adwi_cli.py` and `reason_engine.py`, enforced by `PathValidator` (`adwi/path_validator.py`) using deny-first `.relative_to()` containment.
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
| No token printing | `redact_attrs()` in `telemetry.py` strips sensitive keys before any OTel span or JSONL log write |
| Path containment enforced | `PathValidator` (`path_validator.py`) blocks traversal via `.resolve().relative_to()` — not string prefix matching |
| Memory DB never committed | `adwi/memory.db` gitignored; contains terminal history |
| No credentials in traces | `notes/adwi-trace-logs/` written through `redact()` |
| Nightly loop never auto-upgrades | Upgrade suggestions → `Pending User Approval` section only |
| aider never touches secret files | Hard-block list validated before any file is passed to aider |
| All mutations require gate | REVIEW-REQUIRED tier blocks: `git commit/push`, `rm -r`, `chmod`, `docker compose down` |
| SimLab never touches production data | EvalSandbox redirects all I/O to `/tmp/adwi_sim_sandbox/`; ADWI_EVAL_OUTPUT_JSON env var inert in production |
| SimLab Tier C never auto-applied | Safety-boundary failures queued for human review only; never patched automatically |

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

> **MANUALLY MAINTAINED** — This section is a human-authored snapshot, not auto-generated.
> Numeric annotations (command counts, fixture counts) are validated by `bin/validate-docs`.
> Narrative file descriptions and line-count annotations may lag behind code.
> For authoritative counts, run `bin/validate-docs` or check `adwi/system_manifest.json`.
> Last verified: 2026-06-20.

```
SuneelWorkSpace/
│
├── adwi/                              # Core AI brain
│   ├── adwi_cli.py                    # 11,905 lines · 193 commands · REPL entry point
│   ├── reason_engine.py               # LangGraph: Planner→Executor→Critic (861 lines)
│   ├── memory.py                      # AdwiMemory: SQLite + nomic-embed cosine search (96 NLU fixtures)
│   ├── path_validator.py              # Deny-first path containment; hard-blocks credential dirs
│   ├── telemetry.py                   # OTel tracing → Arize Phoenix; credential-safe redaction
│   ├── nlu_fast_path.py               # Qdrant ≥0.88 bypass: skips llama3.1:8b (~5 ms vs 43 ms)
│   ├── nightly.py                     # 10-step 2 AM maintenance loop
│   ├── overnight_learn.py             # 7-hour knowledge indexer (1 AM via launchd)
│   ├── repair.py                      # Self-repair utilities
│   ├── backup.py                      # Backup orchestration
│   ├── voice.py                       # STT (faster-whisper) + TTS (piper-tts)
│   ├── gmail_helper.py                # Gmail OAuth2 + API integration (864 lines)
│   ├── Modelfile                      # Custom adwi:latest definition (qwen3:30b base)
│   ├── capabilities.json              # Machine-readable capability registry
│   ├── allowed-read-roots.txt         # Trusted filesystem roots
│   ├── commands/                      # CommandRegistry handler modules (dispatch-first pattern)
│   │   ├── __init__.py
│   │   ├── gmail.py                   # Gmail command cluster handlers (Phases 7–17)
│   │   ├── remote.py                  # Remote/HA read-only cluster (Phase 18)
│   │   ├── diagnostics.py             # Diagnostics + viewer cluster (Phase 23)
│   │   ├── voice.py                   # Voice command handlers
│   │   ├── disk.py                    # Disk/FS command handlers
│   │   ├── system.py                  # System command handlers
│   │   ├── assistant.py               # Assistant upgrade/status handlers
│   │   ├── knowledge.py               # Knowledge/RAG command handlers
│   │   └── eval.py                    # Eval routing command handlers
│   ├── tests/                         # Unit test suite for core modules
│   │   ├── test_command_registry.py   # 320 tests — registry dispatch, fallback integrity, safety boundary
│   │   ├── test_nlu_fast_path.py      # NLU Qdrant fast-path bypass tests
│   │   ├── test_path_validator.py     # PathValidator containment tests
│   │   ├── test_search_orchestrator.py # Search orchestrator tests
│   │   ├── test_telemetry.py          # OTel credential redaction tests
│   │   ├── test_telegram_bridge.py    # 80 tests — Telegram bridge safety, routing, /daily-brief formatting
│   │   ├── test_reason_engine_paths.py # 19 tests — PathValidator integration in reason_engine
│   │   ├── test_remote_control_surface.py # 17 tests — static surface guard for Safe Command API + Telegram
│   │   └── test_validate_env.py       # 45 tests — validate_adwi_env.py bootstrap checker
│   ├── simlab/                        # Bounded eval & self-improvement harness (Phase 10)
│   │   ├── schemas.py                 # Dataclasses + SHA-256[:16] failure fingerprinting
│   │   ├── golden_baseline.jsonl      # 20 immutable scenarios — never auto-modified
│   │   ├── idle_orchestrator.py       # Battery/thermal gates, lock, budget, session wiring
│   │   ├── scenario_generator.py      # Templates + safety/adversarial cases + golden seeding
│   │   ├── eval_runner.py             # Ephemeral /tmp sandbox + subprocess eval (45 s timeout)
│   │   ├── grader.py                  # Intent/Safety/Latency/Content/Ambiguity composite
│   │   ├── failure_store.py           # SQLite dedup (fingerprint → occurrence_count)
│   │   ├── improvement_engine.py      # Tier A/B/C proposals; Tier C = human review only
│   │   ├── verification.py            # Must score 100% golden before promotion; git rollback
│   │   ├── reporter.py                # Markdown + JSON reports (logs/simlab/)
│   │   └── tests/
│   │       ├── test_simlab.py         # 41 unit tests, 0 ResourceWarnings
│   │       └── test_nlu_regex.py      # 481 NLU regression tests (Cycles 1–11 + REL-S)
│   ├── logs/simeval/                  # Large-scale eval artifacts
│   │   ├── run_large_eval.py          # P1 eval harness (1,834 scenarios, standalone)
│   │   ├── run_large_eval_p2.py       # P2 eval harness (570 scenarios, weak-family targeting)
│   │   ├── generate_master_report.py  # Combines P1+P2 sessions into MASTER_REPORT_v2.md
│   │   ├── MASTER_REPORT_v2.md        # Combined dedup report: 98.3% (2026-06-20)
│   │   ├── combined_summary_v2.json   # Machine-readable combined summary
│   │   └── fix_backlog_v2.json        # Remaining failure clusters + repair proposals
│   ├── docs/
│   │   ├── NLU_REPAIR_BACKLOG.md      # Prioritized fix list with exact code proposals
│   │   ├── SETUP_NEW_MACHINE.md       # Bootstrap guide for new machines
│   │   ├── BOOTSTRAP_CHECKLIST.md     # Step-by-step new machine checklist
│   │   ├── OPERATOR_HANDBOOK.md       # Day-to-day operator reference
│   │   ├── COMMAND_REGISTRY_WIRING_PLAN.md # Phase migration plan for CommandRegistry
│   │   ├── LLM_SYSTEM_PRIMING.md      # Compact unambiguous priming reference (115 intents, 193 commands)
│   │   ├── TELEGRAM_BRIDGE_SETUP.md   # Telegram bridge config and launch guide
│   │   ├── TELEGRAM_COMMAND_REFERENCE.md # All 9 Telegram commands with examples
│   │   └── CODEX_COLLABORATION.md     # How to use Codex as a reviewer alongside Claude
│   ├── .venv/                         # [gitignored] Python 3.14 virtualenv (uv)
│   ├── memory.db                      # [gitignored] Semantic memory (380+ items)
│   └── knowledge.db                   # [gitignored] Q&A pairs (1,565+) + chunks
│
├── adwi/bin/                          # 51 scripts (auto-update-readme counts authoritative)
│   ├── adwi                           # Launcher (uses .venv python if available)
│   ├── auto-update-readme             # README auto-injection pipeline
│   ├── start-obsidian-bridge          # Start bridge (:5056)
│   ├── stop-obsidian-bridge           # Stop bridge
│   ├── start-phoenix                  # Start Arize Phoenix (:6006)
│   ├── start-homeassistant            # Start Home Assistant (:8123)
│   ├── status-ai                      # All service statuses
│   ├── adwi-git-backup                # 30-min auto-backup script
│   ├── adwi-config-check              # Env var config status (names only, no values)
│   ├── adwi-disk-summary              # Disk usage for key Adwi paths
│   ├── adwi-eval-status               # NLU eval pass rate from MASTER_REPORT_v2.md
│   ├── adwi-nightly-status            # Last nightly run timestamp + outcome
│   ├── adwi-ports                     # Adwi service ports + listen status
│   ├── adwi-version                   # Current git commit + branch
│   └── ...                            # 45 more scripts
│
├── adwi/infra/docker/
│   ├── docker-compose.yml             # 11 compose services + Qdrant (LaunchAgent) = 12 containers (§2)
│   └── monitoring/                    # Prometheus, Loki, Promtail, Grafana configs
│
├── adwi/services/
│   ├── command-api/server.py          # Safe Command API (:5055) · 26 allowlisted routes + 1 background E2E Popen
│   ├── telegram-bridge/bot.py         # Telegram long-poll bridge · 9 cmds · sender+command allowlist · no public port
│   └── mcp/obsidian-bridge/
│       ├── server.py                  # stdlib-only vault HTTP API (:5056)
│       └── start.sh / stop.sh
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
├── adwi/notes/                        # AI learning journal + logs
│   ├── adwi-mistakes-and-fixes.md     # Running bug/fix log (updated after every repair)
│   ├── adwi-trace-logs/               # Per-action execution traces
│   ├── git-backup-logs/               # Per-backup git logs
│   ├── adwi-repair-logs/              # aider pre-flight records
│   ├── codex-reviews/                 # Codex second-opinion review artifacts (severity-ranked)
│   ├── daily-briefs/                  # Daily AI-generated briefs
│   ├── research/                      # Research note saves
│   ├── system-inspections/            # /inspect-system reports
│   └── tech-radar/                    # Tech radar snapshots
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
cd ~/SuneelWorkSpace/adwi/infra/docker
docker compose down && docker compose up -d

# Obsidian bridge
adwi/services/mcp/obsidian-bridge/stop.sh && adwi/services/mcp/obsidian-bridge/start.sh

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
python3 -m py_compile adwi/services/mcp/obsidian-bridge/server.py && echo "bridge OK"
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
| 5 | prompt_toolkit Slash-Command Autocomplete | 193-command registry; substring fuzzy scoring; Tab/arrow REPL overlay | `adwi/adwi_cli.py (SlashCommandCompleter)` |
| 6 | Chain-of-Intent Schema & Semantic Slot-Filling | analysis+confidence+intent+arguments JSON schema; 29 structured arg reads in dispatch | `adwi/adwi_cli.py (_INTENT_JSON_SCHEMA)` |
| 7 | Qdrant-Driven Dynamic Few-Shot Routing | 96-fixture nlu_fixtures collection; top-3 injected into llama3.1:8b system prompt | `adwi/memory.py · Qdrant :6333` |
| 8 | LLM-Priming Documentation Update Invariants | auto-update-readme always runs before backup; PHASES+NLU sections auto-injected | `bin/auto-update-readme · adwi/backup.py` |
| 9 | Security Core: PathValidator, OTel Telemetry, Fast NLU Bypass | deny-first path containment; OTLP→Phoenix traces with credential redaction; Qdrant ≥0.88 score skip of 8B LLM (43 ms → <5 ms fast path) | `adwi/path_validator.py · adwi/telemetry.py · adwi/nlu_fast_path.py` |
| 10 | SimLab: Bounded Continuous Eval & Self-Improvement Harness | hardware/thermal gates; ephemeral sandbox; SHA-256 failure fingerprinting; Tier A/B/C improvement proposals; immutable golden baseline (100% required); auto git-rollback on regression; 41 unit tests, 0 warnings | `adwi/simlab/ (11 modules)` |

All 10 phases verified on 2026-06-24. Each phase committed atomically as an independent transactional unit.
*Auto-updated: 2026-06-24*
<!-- /AUTO:PHASES -->

### CommandRegistry Migration (Phases 11–23, 2026-06-19/20)

The `CommandRegistry` is a dispatch-first handler pattern layered on top of the existing elif chain in `adwi_cli.py`. Every `handle()` call first attempts `_cmd_registry.dispatch(line, {})` before falling through to the legacy elif chain. This allows incremental migration of command handlers into typed, independently-testable modules.

**Architecture:**
```
handle(line)
    │
    ├── _cmd_registry.dispatch(line, {})  ← checks first
    │       │
    │       ├── match found → execute handler → return True
    │       └── no match   → return False
    │
    └── elif chain (legacy fallback)
```

**Migration progress** (as of 2026-06-20):

| Phase | Cluster | Commands migrated | Notes |
|-------|---------|-------------------|-------|
| 7 | Gmail draft lifecycle | `/gmail-drafts`, `/gmail-show-draft`, `/gmail-open-draft`, `/gmail-cancel-draft`, `/gmail-delete-draft` | Test suite: `TestPhase7GmailDraftLifecycle` |
| 8 | Gmail draft editing | `/gmail-rewrite`, `/gmail-update-subject`, `/gmail-add-cc`, `/gmail-add-bcc`, `/gmail-attach`, `/gmail-remove-attachment` | Draft mutation cluster |
| 11 | Gmail schedule | `/gmail-scheduled`, `/gmail-open-scheduled`, `/gmail-cancel-scheduled`, `/gmail-reschedule` | LaunchAgent delivery queue |
| 13 | Gmail extract-tasks | `/gmail-extract-tasks`, `/gmail-tasks-save`, `/gmail-tasks-remind` | Task extraction + Obsidian save |
| 14 | Gmail triage | `/gmail-triage` | AI-driven inbox triage |
| 15 | Gmail attachments | `/gmail-attachments`, `/gmail-save-attachment`, `/gmail-summarize-attachment` | Attachment read + save cluster |
| 16B | Inbox navigation | `/gmail-thread`, `/gmail-thread-intel`, `/gmail-social`, `/gmail-promos`, `/gmail-spam` | Navigation cluster |
| 18 | Remote/HA read-only | `/ha`, `/remote`, `/remote-status`, `/tailscale`, `/watcher-status` | No mutations |
| 23 | Diagnostics + viewer | `/doctor`, `/status`, `/inspect-system`, `/model-status`, `/models`, `/capabilities`, `/capability-audit`, `/capability-status`, `/eval-routing`, `/eval-adwi`, `/route`, `/test-adwi`, `/trace-log` | 13 commands; 315 → 320 tests |

**Safety invariant:** Commands in `ELIF_ONLY` (e.g., `/notify`, `/e2e-auto-loop`, `/run-python`, `/run-bash`, `/implement-idea`) are **intentionally not registered** in the `CommandRegistry`. These require interactive human confirmation at the elif layer. `TestElifFallbackIntegrity` and `TestSafetyBoundaryRegistry` in `test_command_registry.py` enforce this invariant continuously.

**Test coverage:** `adwi/tests/test_command_registry.py` — 320 tests covering:
- All registered cluster dispatch paths
- Fallback (False return) for unregistered commands
- ELIF_ONLY commands confirmed absent from registry
- Dangerous commands confirmed absent from `all_names()`

---

## §9 SimLab Operational Guide

SimLab is a **bounded, offline, self-contained** evaluation harness. It never touches production data, never weakens security boundaries, and never applies changes that would reduce the golden baseline score below 100%.

### How to run

```bash
# Canary run (20% of scenarios, ~5-10 min) — ideal for post-change spot check
python3 -m adwi.simlab

# Full run (all scenarios)
python3 -m adwi.simlab --full --budget 60

# Nightly mode (same as full, wired into nightly.py at 2 AM)
python3 -m adwi.simlab --nightly
```

### Hardware gates (auto-enforced, cannot be bypassed)

| Gate | Condition | Action |
|---|---|---|
| Battery | `pmset -g ps` shows "Battery Power" | Hard block — SimLab does not start |
| Thermal | `loadavg[0] / cpu_count > 0.75` | Pause or abort session |
| Lock file | `logs/simlab.lock` exists | Skip — another session is running |

### Improvement tiers

| Tier | Examples | Gate | Auto-applied? |
|---|---|---|---|
| A | Add NLU fixture, add eval case | None beyond golden check | Yes (immediate) |
| B | Add regex pattern to `_REGEX_INTENTS` | **Must score 100% golden baseline** | Yes, after verification |
| C | Any safety/security logic change | Human review required | **Never auto-applied** |

### Golden baseline invariant

`adwi/simlab/golden_baseline.jsonl` contains 20 immutable scenarios. **Any improvement proposal that causes a single golden failure is automatically rolled back.** For Tier B, rollback is `git checkout HEAD -- <file>`. The golden baseline file itself can only be modified by a human git commit.

### Sandbox isolation

Every eval subprocess runs with:
- `ADWI_SANDBOX_MODE=1`
- `ADWI_MEMORY_DB=/tmp/adwi_sim_sandbox/memory.db`
- `ADWI_KNOWLEDGE_DB=/tmp/adwi_sim_sandbox/knowledge.db`
- `ADWI_NLU_COLLECTION=test_nlu_fixtures`

The sandbox directory is created fresh and torn down after each session. Production `memory.db` and `knowledge.db` are never read or written during eval.

### Session artifacts

After each run: `logs/simlab/simlab-{run_id}.md` and `.json`. The Markdown report includes pass/fail summary, top failure patterns, improvement decisions, slow prompts, and any items needing human review.

### Validate SimLab itself

```bash
python3 adwi/simlab/tests/test_simlab.py -v
# Expected: 41 tests, 0 errors, 0 failures, 0 ResourceWarnings
```

---

## Getting Started

```bash
# 1. Start Docker services
cd ~/SuneelWorkSpace/adwi/infra/docker && docker compose up -d && cd -

# 2. Start Obsidian bridge (if not already via launchd)
bin/start-obsidian-bridge

# 3. Launch adwi
bin/adwi
# or: python3 adwi/adwi_cli.py

# 4. Verify everything
/doctor
```

**New machine?** → See §11 below or `docs/SETUP_NEW_MACHINE.md` for the full bootstrap guide.
**Validating after clone:** `python3 scripts/validate_adwi_env.py`

---

## §10 NLU Eval Status & Repair Backlog

> **Stop Condition B reached 2026-06-19** — combined NLU pass rate exceeded 98%.
> **Last verified:** 2026-06-20 · P1: 1,834 scenarios · P2: 570 scenarios
>
> Eval harness: `adwi/logs/simeval/run_large_eval.py` (P1), `adwi/logs/simeval/run_large_eval_p2.py` (P2)
> Latest P1 session: `adwi/logs/simeval/large-20260620-014026/summary.json`
> Latest P2 session: `adwi/logs/simeval/large-p2-20260620-020631/summary.json`
> Combined master report: `adwi/logs/simeval/MASTER_REPORT_v2.md`
> Living repair list: `adwi/docs/NLU_REPAIR_BACKLOG.md`

### Current pass rates (2026-06-20, verified from eval summary.json)

| Eval | Scenarios | Pass | Fail | Pass rate | Safety breaches | Regex fast-path |
|------|-----------|------|------|-----------|-----------------|-----------------|
| Large P1 (broad coverage) | 1,834 | 1,805 | 24 | **98.4%** | 0 | 70.0% (1,283/1,834) |
| Large P2 (weak-family targeting) | 570 | 560 | 4 | **98.2%** | 0 | 67.5% (385/570) |
| **Combined (dedup)** | **2,283** | **2,244** | **28** | **98.3%** | **0** | **67.8%** |

Average P1 latency: 1,252 ms (P95: 4,779 ms). P2 run time: 246 s (3 workers).

### Full improvement history

| Eval | Pre-NHR | S-1 | S-2 | S-3 | S-4 | Burn-in | Sprint | C-5 | C-6 | C-7 | C-11 | REL-S |
|------|---------|-----|-----|-----|-----|---------|--------|-----|-----|-----|------|-------|
| P1 (1,834) | 78.0% | 83.7% | 88.6% | 90.7% | ~89% | — | 92.6% | 96.3% | 96.7% | 95.7% | **98.6%** | **98.4%** |
| P2 (570) | 68.6% | 77.6% | 81.4% | 83.9% | ~84% | 88.8% | 88.8% | 97.0% | 98.2% | 97.0% | 98.1% | **98.2%** |
| Combined | 75.8% | 82.1% | 86.0% | 89.0% | ~89% | — | ~91.7% | ~96.5% | ~97.0% | ~95.8% | 98.4% | **98.3%** |

Total gain P1: +20.4pp. Total gain P2: +29.6pp. Total gain combined: +22.5pp.

### All applied repair cycles

**NHR-001 through NHR-010 — Session 1** (2026-06-16): `file_search` ordering, `youtube`, `patch_adwi`, `self_heal`, obsidian disambiguation, `daily_improve`, `what_next`, `inspect_code`, `memory_stats`, `backup_now` — ✅ All applied.

**Session-2** (2026-06-16): 11 regex patch groups — FIX-LF-001, FIX-OLD-001, FIX-DUP-001, FIX-ORG-002, FIX-CLEANUP-003, FIX-HEAL-001, FIX-BROWSE-001, FIX-WEB-001, FIX-ERR-002, FIX-EVAL-002, FIX-TEST-002, FIX-MEMSCAN-002, FIX-BENCH-001 — ✅ All applied.

**Session-3** (2026-06-16): 9 regex groups — FIX-CLEAN-004, FIX-NOTES-001, FIX-STATUS-002, FIX-WHAT-002, FIX-WEB-002, FIX-OBS-002, FIX-NIGHT-001, FIX-EVAL-003, FIX-PATCH-002, FIX-RC-001, FIX-GMAIL-002, FIX-MEMST-001, FIX-MEMCTX-001, FIX-FR-001, FIX-S3-001 through FIX-S3-009, plus 4 `_INTENT_SYSTEM` clarifications — ✅ All applied.

**Session-4 code-review hardening** (2026-06-16): 8 false-positive fixes — `.{0,30}` → `.{0,10}` tightening, `different` removed from git_status, broad `is X running` removed, bare `tps`/`kb` removed, `MEMCTX` negative lookahead — ✅ All applied.

**Gmail burn-in** (2026-06-17): 12 FIX-STRESS patches + 4 FIX-STAGE3 patches — Gmail-heavy stress testing across all 50 Gmail intents, 418 comms scenarios — ✅ All applied.

**Stabilization sprint** (2026-06-17): 9 regex fix groups + 4 `_INTENT_SYSTEM` additions + 6 test gap fills — ✅ All applied.

**CYCLE-5** (2026-06-17): 13 bare-command anchors, chat advisory fixes, status/advisory boundary, `memory_scan`/`github_connected`/`web_search` additions — ✅ All applied, synced to all 3 files.

**CYCLE-6** (2026-06-17): `PermissionError` guard before CYCLE-1, `run-aider` before self-heal, `organize` before chat, `use_local`/`large_files`/`gmail_list_attachments`/`capabilities`/`trusted_roots`/`tool_roadmap`/`test_adwi` targeted fixes — ✅ All applied, synced to all 3 files.

**CYCLE-7** (2026-06-18): 6 new intents (research, browser_delegate, daily_brief, tech_radar, memory_curate, assistant_upgrade_status) added. `memory_curate` word-boundary fix. `rag_search` guard (was matching "research" via substring). `save-research-about` regex added. 35 new eval scenarios (26 P1 + 9 P2). P1 total: 1,834. P2 total: 570 — ✅ All applied.

**CYCLE-8–10** (2026-06-18/19): E2E auto-loop applied — 14 patches in cycle 1 (+0.7pp), FIX-042 through FIX-062 (voice_out order, browse `_INTENT_SYSTEM`, web_search/rag_search tightening, capabilities/old_files/trusted_roots/test_adwi regexes, web_search changelog regex) — ✅ All applied.

**CYCLE-11** (2026-06-19): FIX-063 (rag_search before obsidian_search for "search my notes" + typo-tolerant sea?r?a?ch), FIX-064a–e (research, patch_adwi, nightly_status, github_connected typo, duplicates typo). P1: 98.6%, P2: 97.7%, Combined: 98.3% — ✅ All applied.

**Trust-baseline repair pass** (2026-06-19): 3 NLU safety breaches fixed (`~/Library/Passwords`, `/root/.bashrc`, developer-mode social-engineering → `__none__`) + browse guard. All env-path drift fixed across nightly.py, reason_engine.py, obsidian-bridge, adwi-sandbox. `reason_engine.py` write guard expanded to 12 entries. OpenTelemetry startup hang fixed (port-check gate). P1: 98.6%, P2: 98.1%, Combined: 98.4%. Safety breaches: 0 — ✅ All applied.

**Reliability-push session** (2026-06-20): 14 NLU regex fixes — FIX-REL-001 through FIX-REL-014. Targets: disk_usage hogs/hasn't/capacity patterns, file_search locate/Dockerfile patterns, file_list list-contents, backup_now commit-and-push, use_local local-llm patterns, benchmark guard (prevents use_local false positive on "benchmark my local model"), fix_error extended to StopIteration/UnicodeDecodeError/OverflowError/LookupError/ArithmeticError. All 3 files synced. P1: 98.4%, P2: 98.2%, Combined: 98.3%. Safety breaches: 0. Regex fast-path: 67.8% — ✅ All applied.

### Category health (REL-S, from P1 session large-20260620-014026)

| Category | Scenarios | Pass | Rate | Status |
|----------|-----------|------|------|--------|
| file | 85 | 85 | 100% | ✅ Perfect |
| search | 71 | 71 | 100% | ✅ Perfect |
| media | 48 | 48 | 100% | ✅ Perfect |
| memory | 85 | 85 | 100% | ✅ Perfect |
| vault | 60 | 60 | 100% | ✅ Perfect |
| git | 108 | 108 | 100% | ✅ Perfect |
| voice | 41 | 41 | 100% | ✅ Perfect |
| security | 18 | 18 | 100% | ✅ Perfect |
| repair | 83 | 83 | 100% | ✅ Perfect |
| eval | 25 | 25 | 100% | ✅ Perfect |
| safety | 46 | 46 | 100% | ✅ Perfect (0 breaches) |
| upgrade_pack | 26 | 26 | 100% | ✅ Perfect |
| comms (Gmail) | 418 | 415 | 99.3% | ✅ Excellent |
| system | 199 | 195 | 98.0% | ✅ Healthy |
| model | 54 | 53 | 98.1% | ✅ Healthy |
| ambiguous | 40 | 39 | 97.5% | ✅ Healthy |
| disk | 241 | 230 | 95.4% | ✅ Healthy (10 disk_usage → LLM __none__ timeouts) |
| planning | 30 | 28 | 93.3% | ✅ Good |
| chat | 126 | 120 | 95.2% | ⚠️ Advisory questions → LLM variance; irreducible below ~95% |

### Remaining failures (P1, 24 total; P2, 4 total)

| Family | Count | Nature |
|--------|-------|--------|
| `disk_usage` → `__none__` | 10 | LLM misroutes disk_usage phrases to __none__ when LLM is under load; regex path handles 70% correctly |
| `chat` advisory mislabeling | 5 | LLM variance on advisory questions — no regex fix practical |
| Scattered single-intent LLM variance | 9 | 1 failure each: `status`, `gmail_tasks_save`, `gmail_confirm`, `nightly_run`, `gmail`, `use_local`, `benchmark`, `__none__` (2) |
| P2 LLM variance (chat/search) | 4 | "how does vector memory work", "how does RAG memory work", "search with tavily for python packages", "notes" |

### NLU regression test suite

Three layers of protection prevent NLU regressions:

| Layer | File | Tests | Covers |
|-------|------|-------|--------|
| Fast regex unit tests | `adwi/simlab/tests/test_nlu_regex.py` | **481** | All cycles 1–11 + REL-S; intent/negative pairs for every pattern |
| Large eval P1 harness | `adwi/logs/simeval/run_large_eval.py` | **1,834 scenarios** | Broad coverage across all 115 intents |
| Large eval P2 harness | `adwi/logs/simeval/run_large_eval_p2.py` | **570 scenarios** | Weak-family targeting for historically low-accuracy intents |

All regex changes must be synced to all 3 files: `adwi/adwi_cli.py`, `run_large_eval.py`, `run_large_eval_p2.py`.

### Safety assessment

46 safety probes in P1 — **0 breaches**. The trust-baseline repair pass (2026-06-19) resolved 3 prior safety gaps (`~/Library/Passwords` path + `/root/.bashrc` path + developer-mode social-engineering prompt → all correctly return `__none__`). Defense-in-depth: NLU routes safely, execution layer enforced by `PathValidator` + `BLOCKED_PATHS`.

### How to run evals

> **Important:** Run P1 and P2 **sequentially** (not in parallel). Running both simultaneously overloads Ollama and produces 50–70 spurious timeouts that corrupt measurements by 3–8pp.

```bash
# Requires: Ollama running + llama3.1:8b loaded
# Use 3 workers (not 5) to avoid LLM timeout cascade
python3 adwi/logs/simeval/run_large_eval.py --workers 3       # P1: ~1,834 scenarios (~30 min)
python3 adwi/logs/simeval/run_large_eval_p2.py --workers 3    # P2: ~570 scenarios (~10 min)
python3 adwi/logs/simeval/generate_master_report.py \
    adwi/logs/simeval/<p1-dir> adwi/logs/simeval/<p2-dir>

# Quick NLU regression check (no Ollama needed — pure Python regex)
python3 -m unittest adwi/simlab/tests/test_nlu_regex.py -v    # 481 tests, ~5s
python3 -m unittest adwi/tests/test_command_registry.py -v    # 320 tests, ~1s
```

See `adwi/docs/NLU_REPAIR_BACKLOG.md` for the full repair workflow and prioritized fix list.

---

## §11 New Machine Bootstrap

> **Goal:** clone → working Adwi in one session.
> **Full guide:** `docs/SETUP_NEW_MACHINE.md`
> **Checklist:** `docs/BOOTSTRAP_CHECKLIST.md`
> **Validator:** `python3 scripts/validate_adwi_env.py`

### What the repo contains vs. what you must set up per-machine

| Asset | In repo? | Setup action |
|-------|----------|--------------|
| All source code, scripts, docs | ✅ Yes | `git clone` |
| `config/.env.example` (key template) | ✅ Yes | Copy → `config/.env`, fill values |
| `docs/` onboarding + eval guides | ✅ Yes | Read |
| `CLAUDE.md` AI session orientation | ✅ Yes | Claude reads on session start |
| `config/.env` (real API keys) | ❌ Gitignored | Fill from template |
| `secrets/` (OAuth tokens, credentials) | ❌ Gitignored | Re-auth per machine |
| `adwi/.venv/` (Python packages) | ❌ Gitignored | `uv venv` + pip |
| Ollama models (~25–35 GB) | ❌ Not in repo | `ollama pull` each model |
| `adwi/memory.db`, `knowledge.db` | ❌ Gitignored | `/memory-scan`, `overnight_learn.py` |
| Docker runtime data | ❌ Gitignored | `docker compose up -d` |
| LaunchAgent plists | ❌ System-level | `adwi → /backup-enable` |
| Eval large result sessions | ❌ Gitignored | `python3 logs/simeval/run_large_eval.py` |

### 10-step quick bootstrap

```bash
# 1 — Clone and PATH
git clone <repo-url> ~/SuneelWorkSpace
echo 'export PATH="$HOME/SuneelWorkSpace/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc

# 2 — Python venv
cd ~/SuneelWorkSpace/adwi && uv venv --python 3.12
.venv/bin/pip install prompt_toolkit instructor openai qdrant-client faster-whisper

# 3 — Ollama + models (takes time — 25+ GB)
brew install ollama && brew services start ollama
ollama pull llama3.1:8b nomic-embed-text qwen3:0.6b qwen3:30b
ollama create adwi:latest -f ~/SuneelWorkSpace/adwi/Modelfile

# 4 — Secrets
cp config/.env.example config/.env && $EDITOR config/.env

# 5 — Docker stack
cd ~/SuneelWorkSpace/adwi/infra/docker && docker compose up -d && cd -

# 6 — Supporting services
bin/start-obsidian-bridge && bin/start-command-api

# 7 — NLU fixtures
python3 adwi/memory.py provision-nlu

# 8 — Memory (optional, runs overnight)
echo "/memory-scan\n/exit" | python3 adwi/adwi_cli.py

# 9 — Validate
python3 scripts/validate_adwi_env.py

# 10 — Launch
bin/adwi   →   /doctor
```

### AI session onboarding

When a new Claude (or other AI) session opens this repo, it should read `CLAUDE.md` first. That file contains:
- The NLU pipeline summary and current pass rates
- The file responsibility map
- All safety invariants that must not be weakened
- The NHR repair workflow
- What not to do

---

*Auto-backed up every 30 minutes · README sections auto-updated by `bin/auto-update-readme` on every commit.*
