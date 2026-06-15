# Adwi — Local AI Operating System

> A fully autonomous, self-healing AI operating environment running entirely on local hardware (Apple M4 Max, 64 GB RAM). No cloud required for core inference. All data stays local.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Components Breakdown](#4-components-breakdown)
5. [Commands & Capabilities](#5-commands--capabilities)
6. [Background Services](#6-background-services)
7. [Security Model](#7-security-model)
8. [Rollback & Recovery](#8-rollback--recovery)

---

## 1. Overview

Adwi is a personal AI OS built around a single interactive CLI (`adwi/adwi_cli.py`). It is not a chatbot wrapper — it is a full operating environment that:

- Runs a **131K-context local reasoning model** (Qwen3 MoE 30B) via Ollama
- Maintains a **persistent semantic memory** (380+ memories across git, notes, terminal history)
- Indexes its own codebase and notes nightly into a **Q&A knowledge base** (1,500+ pairs)
- Searches the web via **three parallel APIs** (SearXNG local + Tavily + Exa) and scrapes pages with Firecrawl
- Reads, writes, and searches an **Obsidian vault** via an HTTP bridge
- Heals itself nightly using **aider-chat** when tests fail
- Auto-commits its own git backups every 30 minutes via a macOS LaunchAgent
- Writes a **morning brief** to the Desktop every night at 2 AM

Everything runs as persistent background services. You open a terminal, type `adwi`, and the full environment is already warm.

### Hardware & Runtime

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

---

## 2. Architecture

### Component Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          USER ENTRY POINTS                               │
│                                                                          │
│   adwi CLI (terminal)          Open WebUI (browser :3000)               │
│   python3 adwi/adwi_cli.py    └── Gemini cloud routing (optional)       │
└───────────────────┬─────────────────────────────┬───────────────────────┘
                    │                             │
                    ▼                             ▼
┌───────────────────────────────────────────────────────────────────────┐
│                      CORE BRAIN — adwi_cli.py                         │
│                                                                        │
│  dispatch_natural()  ←─── NLU intent (qwen3:0.6b + regex patterns)   │
│        │                                                               │
│        ├── /ask, /chat       → adwi:latest (Ollama)                   │
│        ├── /web-search       → search_web() multi-source cascade       │
│        ├── /memory-recall    → 3-layer memory system (see below)       │
│        ├── /obsidian-*       → obsidian-bridge HTTP API (:5056)        │
│        ├── /browse           → Firecrawl → Playwright → urllib          │
│        ├── /patch-adwi       → aider-chat self-healing                 │
│        ├── /vision           → minicpm-v (Ollama)                      │
│        └── 80+ other commands (see §5)                                 │
└───────────┬─────────┬──────────┬────────────────────────────────────┘
            │         │          │
            ▼         ▼          ▼
    ┌────────────┐ ┌──────────┐ ┌────────────────────────────────────┐
    │ memory.db  │ │knowledge │ │          Web Search Layer           │
    │ SQLite     │ │ .db      │ │                                     │
    │ 380 items  │ │ SQLite   │ │  SearXNG (:8888) — always runs     │
    │ nomic-     │ │ 1565 Q&A │ │  Tavily  — AI-curated results      │
    │ embed-text │ │ 500 chunks│ │  Exa     — neural/semantic search  │
    │ 768-dim    │ │ embeddings│ │  Firecrawl — URL→clean markdown    │
    └────────────┘ └──────────┘ └────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                       DOCKER SERVICES                                    │
│                                                                          │
│   Open WebUI   :3000   — browser chat UI, model switching               │
│   n8n          :5678   — workflow automation                             │
│   SearXNG      :8888   — private local web search (no tracking)         │
│   Qdrant       :6333   — vector database                                │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    BACKGROUND AUTOMATION                                  │
│                                                                          │
│   nightly.py      2:00 AM — 10-step maintenance loop                    │
│   overnight_learn 1:00 AM — 7-hour knowledge indexer                    │
│   git-backup      every 30 min — auto-commit all workspace changes       │
│   obsidian-bridge KeepAlive — Obsidian vault HTTP API (:5056)           │
│   qdrant          KeepAlive — vector DB (via launchd)                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3-Layer Memory Recall

When you run `/memory-recall <query>`, Adwi searches three stores in sequence:

```
Layer 1: memory.db (AdwiMemory)
  → semantic search via nomic-embed-text cosine similarity
  → sources: terminal history, git commits, notes files

Layer 2: knowledge.db (Q&A pairs)
  → embed query with nomic-embed-text
  → cosine similarity across 1,565 Q&A pairs
  → built nightly by overnight_learn.py from codebase + notes

Layer 3: obsidian-vault/ (full-text)
  → substring scan across all .md files in vault
  → returns snippets with file path + line context
```

### Web Search Data Flow

```
/web-search "query"
     │
     ├── SearXNG (local, always)    → deduplicate by URL
     ├── Tavily (if key set)        → add new URLs only
     └── Exa (if key set)           → add new URLs only
                                         │
                                    synthesis by adwi:latest
                                         │
                                    formatted answer with [TAV]/[EXA]/[SEA] badges
```

### Nightly 10-Step Loop (2 AM)

```
Step 1: Service health checks (Ollama, Docker, all APIs)
Step 2: Log rotation and cleanup
Step 3: AI skill discovery (scan notes for new capabilities)
Step 4: aider-chat self-healing (run tests → auto-fix failures → up to 3 attempts)
Step 5: Evaluation runs (routing + model quality evals)
Step 5b: System health audit (brew outdated, npm outdated, disk, docker stats)
Step 5c: Web research (5 topics: Ollama, Open WebUI, n8n, Qdrant, aider)
Step 6: Backup sync check
Step 7: Memory scan (/memory-scan)
Step 8: Capability sync to capabilities.json
Step 8b: Obsidian daily note (writes obsidian-vault/daily-notes/YYYY-MM-DD.md)
Step 9: Git commit of all changes
Step 10: Write morning_brief.md to Desktop
```

---

## 3. Directory Structure

```
SuneelWorkSpace/
│
├── adwi/                          # Core AI brain
│   ├── adwi_cli.py                # Main CLI — 4,150+ lines, 80+ commands
│   ├── memory.py                  # AdwiMemory: SQLite + nomic embeddings
│   ├── nightly.py                 # 10-step 2 AM maintenance loop
│   ├── overnight_learn.py         # 7-hour knowledge indexer
│   ├── repair.py                  # Self-repair utilities
│   ├── backup.py                  # Backup orchestration
│   ├── Modelfile                  # Custom adwi:latest model definition
│   ├── capabilities.json          # Machine-readable capability registry
│   ├── allowed-read-roots.txt     # Trusted filesystem roots (/Users/MAC)
│   ├── memory.db                  # [gitignored] Semantic memory store
│   └── knowledge.db               # [gitignored] Q&A knowledge base
│
├── bin/                           # 35 helper shell scripts
│   ├── adwi                       # Launcher: python3 adwi/adwi_cli.py
│   ├── start-obsidian-bridge      # Start bridge on :5056
│   ├── stop-obsidian-bridge       # Stop bridge
│   ├── status-ai                  # Print all service statuses
│   ├── daily-ai-status-report     # Run nightly.py report section only
│   ├── benchmark-adwi             # Run inference benchmark
│   └── ...                        # 29 more scripts
│
├── local-ai-stack/
│   └── docker-compose.yml         # Open WebUI, n8n, SearXNG, Qdrant
│
├── mcp-servers/
│   ├── obsidian-bridge/
│   │   ├── server.py              # stdlib-only HTTP API for vault (:5056)
│   │   ├── start.sh               # PID-managed start
│   │   └── stop.sh                # PID-managed stop
│   └── [other MCP server dirs]    # Playwright, GitHub, SQLite, Memory, etc.
│
├── local-command-api/
│   └── server.py                  # Safe Command API (:5055) — 8 allowlisted routes
│
├── obsidian-vault/                # Structured markdown knowledge base
│   ├── knowledge/                 # Architecture docs, troubleshooting, guardrails
│   ├── daily-notes/               # Written nightly by nightly.py
│   ├── automations/               # Loop design docs
│   └── prompts/                   # System prompts for Open WebUI
│
├── config/
│   └── .env                       # [gitignored] API keys (Tavily, Exa, Firecrawl, etc.)
│
├── notes/                         # AI learning journal, capability roadmap, logs
│   ├── ADWI-START-HERE.md         # Setup guide
│   ├── capability-roadmap.md      # Planned capabilities
│   └── ...
│
├── logs/
│   └── adwi_system_log.md         # Running system change log
│
├── secrets/                       # [gitignored entirely] Credentials, tokens
└── .gitignore                     # Excludes: secrets, .env, *.db, model files, logs
```

---

## 4. Components Breakdown

### 4.1 Adwi CLI (`adwi/adwi_cli.py`)

The central nervous system. ~4,150 lines of Python. Runs as an interactive REPL with a colored prompt.

**Startup sequence:**
1. Load `config/.env` (non-fatal if missing)
2. Connect to Ollama, verify `adwi:latest` is available
3. Open `memory.db` (create if missing)
4. Print banner with service health status

**Intent routing** — every input goes through `dispatch_natural()`:
- If it starts with `/` → direct command dispatch
- Otherwise → `qwen3:0.6b` classifies intent (web_search, obsidian_search, code_ask, general, etc.)
- Falls back to natural language chat with `adwi:latest`

### 4.2 Local Reasoning Model (`adwi:latest`)

Custom Modelfile built on `qwen3:30b`:

```
FROM qwen3:30b
PARAMETER num_ctx     131072
PARAMETER temperature 0.25
PARAMETER repeat_penalty 1.1
```

The system prompt instructs the model to act as a cautious local AI assistant that never reads secrets, never commits without review, and always explains destructive actions before taking them.

### 4.3 Memory System (`adwi/memory.py`)

**Schema:** SQLite table `memories` with columns: `id`, `source`, `content`, `embedding` (BLOB), `timestamp`, `metadata`.

**Sources indexed:**
- `terminal` — shell commands (filters out common noise like `ls`, `cd`, secrets)
- `git` — commit messages from workspace git log
- `notes` — markdown files in `notes/` directory

**Search:** cosine similarity between nomic-embed-text query embedding and stored embeddings. Falls back to keyword substring match.

**Current size:** 380 memories (69 git, 218 notes, 93 terminal)

### 4.4 Knowledge Base (`adwi/knowledge.db`)

Built by `overnight_learn.py` (runs nightly at 1 AM):

1. Crawls workspace files (Python, markdown, JSON, shell scripts)
2. Chunks each file into ~500-token segments
3. Sends each chunk to `adwi:latest` to generate Q&A pairs
4. Embeds each Q&A pair with `nomic-embed-text`
5. Stores in SQLite tables: `chunks` (500 rows) + `qa_pairs` (1,565 rows)

Used by `/memory-recall` Layer 2 for semantic code/docs search.

### 4.5 Web Search (`search_web()`)

Three-source cascade, deduplicated by URL:

| Source | Type | Requires |
|---|---|---|
| SearXNG `:8888` | Local, private | Docker running |
| Tavily | AI-curated, fast | `TAVILY_API_KEY` in `config/.env` |
| Exa | Neural/semantic | `EXA_API_KEY` in `config/.env` |

Results displayed with source badges: `[TAV]` / `[EXA]` / `[SEA]`.

**Page scraping priority** (used by `/browse`):
1. Firecrawl (cloud, best quality) — if `FIRECRAWL_API_KEY` is set
2. Playwright (local browser automation)
3. `urllib` (raw HTTP fallback)

### 4.6 Obsidian Vault + Bridge

**Vault location:** `obsidian-vault/` (tracked in git, minus workspace runtime files)

**Bridge:** `mcp-servers/obsidian-bridge/server.py` — stdlib-only Python HTTP server on `:5056`.

Routes:
| Method | Path | Action |
|---|---|---|
| GET | `/` | Health check |
| GET | `/read?path=...` | Read a vault .md file |
| GET | `/list?dir=...` | List files in vault directory |
| GET | `/search?q=...` | Full-text search across all .md files |
| POST | `/write` | Write file (auto-creates `.bak` backup) |
| POST | `/append` | Append to file |
| POST | `/daily-note` | Write/append today's daily note |

Path traversal protection: all paths resolved and validated against vault root before any operation.

### 4.7 Safe Command API (`:5055`)

`local-command-api/server.py` — an HTTP→shell bridge for n8n workflows. Only 8 allowlisted routes, no arbitrary command execution:

| Route | Action |
|---|---|
| `/status-ai` | Run `bin/status-ai` |
| `/daily-ai-status-report` | Run nightly report section |
| `/index-ai-notes` | Re-index notes into knowledge.db |
| `/auto-ai-maintenance` | Run nightly.py manually |
| `/adwi-self-heal` | Run aider-chat self-healing pass |
| `/rag-index` | Re-index RAG database |
| `/git-status-workspace` | `git status` + `git log --oneline -10` |
| `/benchmark-adwi` | Run inference benchmark |

### 4.8 Nightly Loop (`adwi/nightly.py`)

Runs at 2 AM via macOS LaunchAgent. Writes `~/Desktop/morning_brief.md` with:
- Service health status
- System health (disk, Docker stats, outdated packages)
- Web research summaries (5 topics)
- Memory scan results
- **Pending User Approval** section — version updates and other high-risk suggestions that must be manually reviewed before applying

The loop never auto-applies high-risk changes. It writes them to the brief for human review.

---

## 5. Commands & Capabilities

### Chat & Reasoning

| Command | Description |
|---|---|
| `/ask <question>` | Ask adwi:latest a question |
| `/chat <message>` | Conversational mode |
| `/vision <image> [question]` | Analyze image with minicpm-v |
| `/route <query>` | Show NLU intent classification for a query |
| `/eval-routing` | Run routing accuracy evaluation |
| `/eval-adwi` | Run model quality evaluation |

### Web Search & Browse

| Command | Description |
|---|---|
| `/web-search <query>` | Multi-source search (SearXNG + Tavily + Exa) with AI synthesis |
| `/exa <query>` | Neural search via Exa API |
| `/tavily <query>` | AI-curated search via Tavily API |
| `/browse <url> [question]` | Scrape page via Firecrawl→Playwright→urllib |
| `/firecrawl <url> [question]` | Scrape + clean markdown via Firecrawl |

### Memory & Knowledge

| Command | Description |
|---|---|
| `/memory-recall [query]` | 3-layer recall: ledger + Q&A + Obsidian vault |
| `/memory-context [query]` | Memory context for current conversation |
| `/memory-scan` | Re-index terminal history, git, notes into memory.db |
| `/memory-stats` | Show memory.db record counts by source |

### Obsidian Vault

| Command | Description |
|---|---|
| `/obsidian-search <query>` | Full-text search across vault |
| `/obsidian-read <path>` | Read a vault file |
| `/obsidian-write <path>` | Write to a vault file (interactive) |
| `/obsidian-daily` | Open/append today's daily note |

### Code & Self-Healing

| Command | Description |
|---|---|
| `/patch-adwi [hint]` | Run aider-chat to fix failing tests |
| `/run-safe <command>` | Run a command through safe execution wrapper |
| `/inspect-code <file>` | Analyze a code file for issues |
| `/test-adwi` | Run adwi test suite |
| `/learn-from-last-error` | Analyze most recent error and suggest fix |
| `/extract-ideas [file]` | Extract actionable ideas from notes |
| `/implement-idea <idea>` | Draft implementation plan for an idea |

### Backup & Git

| Command | Description |
|---|---|
| `/backup-now [message]` | Commit and push all changes |
| `/backup-status` | Show backup health and last commit time |
| `/backup-enable` / `/backup-disable` | Toggle auto-backup LaunchAgent |
| `/backup-log` | Show recent backup commits |
| `/backup-audit` | Audit .gitignore coverage |

### System & Diagnostics

| Command | Description |
|---|---|
| `/doctor` | Full system health check (all services + syntax) |
| `/inspect-system` | Deep system inspection and recommendations |
| `/capabilities` | Show all registered capabilities |
| `/capability-audit` | Audit capabilities vs. actual implementations |
| `/trusted-roots` | Show allowed filesystem read roots |
| `/trust-root <path>` | Add a trusted filesystem root |
| `/nightly-status` | Show last nightly run status |
| `/nightly-log` | Show nightly loop log |
| `/nightly-run` | Trigger nightly loop manually |
| `/trace-log [query]` | Search system trace log |

### Training & Evaluation

| Command | Description |
|---|---|
| `/export-training-example [label]` | Export current exchange as training data |
| `/training-plan` | Generate fine-tuning plan from examples |
| `/tool-roadmap` | Show planned tool additions |

---

## 6. Background Services

All managed as macOS LaunchAgents (`~/Library/LaunchAgents/com.suneel.*.plist`):

| Agent | Schedule | What it does |
|---|---|---|
| `adwi-nightly` | 2:00 AM daily | 10-step maintenance + morning brief |
| `adwi-overnight-learn` | 1:00 AM daily | 7-hour knowledge indexer |
| `adwi-git-backup` | Every 30 min | Auto-commit all workspace changes |
| `obsidian-bridge` | KeepAlive | Obsidian vault HTTP API on :5056 |
| `qdrant` | KeepAlive | Vector database on :6333 |

Docker services (managed via `local-ai-stack/docker-compose.yml`):

| Service | Port | Purpose |
|---|---|---|
| Open WebUI | :3000 | Browser chat UI + model switching |
| n8n | :5678 | Workflow automation |
| SearXNG | :8888 | Private local web search |
| Qdrant | :6333 | Vector database |

Other always-running services:

| Service | Port | Start command |
|---|---|---|
| Ollama | :11434 | `brew services start ollama` |
| Obsidian Bridge | :5056 | `bin/start-obsidian-bridge` or launchd |
| Safe Command API | :5055 | `bin/start-command-api` |
| PrivateGPT | :8001 | `uv tool run private-gpt serve` |

---

## 7. Security Model

### What is never committed

- `secrets/` — entire directory is gitignored
- `config/.env` — API keys (Tavily, Exa, Firecrawl, etc.)
- `adwi/memory.db` — contains terminal history
- `adwi/knowledge.db` — contains indexed workspace content
- Docker runtime data (`*-data/` directories)
- Model files (`*.gguf`, `*.bin`, `*.safetensors`)

### Hard-blocked paths (agents will never read/write)

```
~/.ssh/          ~/.gnupg/         ~/Library/Keychains/
~/Library/Passwords/  ~/.aws/      ~/.kube/
~/SuneelWorkSpace/secrets/  /etc/  /private/  /System/
```

### Secret handling

- Secrets loaded at startup from `config/.env` as opaque values
- Never printed, logged, included in briefs, or passed to models
- API keys passed as HTTP headers — never interpolated into prompts

### Nightly loop safety

- Never auto-applies package version upgrades
- Never auto-applies aider patches rated "high-risk"
- All such suggestions go to the **Pending User Approval** section of the morning brief
- Browser automation (Playwright/Firecrawl) will not fill forms on sensitive domains or execute credential transactions

---

## 8. Rollback & Recovery

### Quick rollback

```bash
# Roll back any file to a specific commit
git log --oneline adwi/adwi_cli.py
git checkout <hash> -- adwi/adwi_cli.py

# Verify syntax
python3 -m py_compile adwi/adwi_cli.py && echo "OK"
```

### Service restart

```bash
# Docker stack
cd ~/SuneelWorkSpace/local-ai-stack && docker compose down && docker compose up -d

# Obsidian bridge
mcp-servers/obsidian-bridge/stop.sh && mcp-servers/obsidian-bridge/start.sh

# Reload all LaunchAgents
for plist in ~/Library/LaunchAgents/com.suneel.*.plist; do
  launchctl unload "$plist" 2>/dev/null
  launchctl load "$plist"
done

# Ollama
brew services restart ollama
```

### Rebuild gitignored databases

```bash
# Rebuild knowledge.db (takes ~7 hours)
nohup python3 ~/SuneelWorkSpace/adwi/overnight_learn.py > /tmp/overnight-learn.log 2>&1 &

# Rebuild memory.db (takes ~2 minutes)
echo "/memory-scan\n/exit" | python3 adwi/adwi_cli.py
```

### Full system validation

```bash
python3 -m py_compile adwi/adwi_cli.py     && echo "cli OK"
python3 -m py_compile adwi/nightly.py      && echo "nightly OK"
python3 -m py_compile adwi/overnight_learn.py && echo "overnight OK"
python3 -m py_compile mcp-servers/obsidian-bridge/server.py && echo "bridge OK"
curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print('Ollama OK:', len(json.load(sys.stdin)['models']), 'models')"
curl -s http://localhost:5056/           | python3 -c "import sys,json; d=json.load(sys.stdin); print('Bridge OK:', d['status'])"
curl -s "http://localhost:8888/search?q=test&format=json" | python3 -c "import sys,json; d=json.load(sys.stdin); print('SearXNG OK:', len(d.get('results',[])), 'results')"
```

---

## Getting Started

```bash
# 1. Clone and enter workspace
cd ~/SuneelWorkSpace

# 2. Start Docker services
cd local-ai-stack && docker compose up -d && cd ..

# 3. Start Obsidian bridge (if not already running via launchd)
bin/start-obsidian-bridge

# 4. Launch adwi
bin/adwi
# or: python3 adwi/adwi_cli.py

# 5. Verify everything
/doctor
```

See `notes/ADWI-START-HERE.md` for detailed first-time setup instructions.

---

*Auto-backed up every 30 minutes by the `adwi-git-backup` LaunchAgent.*


## Auto-Managed Reference

### Docker Services

<!-- AUTO:SERVICES -->
| Service | Port | Status |
|---|---|---|
| open-webui | :3000 | ✓ running |
| n8n | :5678 | ✓ running |
| searxng | :8888 | ✓ running |
*Auto-updated: 2026-06-15*
<!-- /AUTO:SERVICES -->

### Background Agents

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

### CLI Commands

<!-- AUTO:COMMANDS -->
**120 registered commands.** Key groups:

**add**: `/add-capability-plan <idea>`  `/add-root`

**backup**: `/backup-audit`  `/backup-disable`  `/backup-enable`  `/backup-log`  `/backup-now`  `/backup-status`

**benchmark**: `/benchmark`

**browse**: `/browse`

**capabilities**: `/capabilities`

**capabilities  or  /capability**: `/capabilities  or  /capability-status`

**capability**: `/capability-audit`  `/capability-status`

**cleanup**: `/cleanup`

**cloud <prompt>  or just type**: `/cloud <prompt>  or just type`

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
