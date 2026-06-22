# Setting Up Adwi on a New Machine

This guide brings a fresh macOS clone of this repo to a fully working Adwi development environment. Follow the sections in order. Each section ends with a validation command so you know when you can move on.

**Time estimate:** 45–90 minutes (mostly waiting for model downloads)

---

## Prerequisites

| Requirement | Check |
|-------------|-------|
| macOS 14+ | `sw_vers` |
| Apple Silicon (M1/M2/M3/M4) recommended | `uname -m` → arm64 |
| Homebrew | `brew --version` |
| Git | `git --version` |
| Docker Desktop | `docker --version` |
| 32 GB+ RAM (64 GB for full model stack) | Activity Monitor |
| 100 GB+ free disk | `df -h ~` |

---

## Step 1 — Clone and PATH setup

```bash
# Clone to the same expected workspace path
git clone <your-repo-url> ~/SuneelWorkSpace
cd ~/SuneelWorkSpace

# Add bin/ to PATH (do this in ~/.zshrc too)
export PATH="$HOME/SuneelWorkSpace/adwi/bin:$PATH"
echo 'export PATH="$HOME/SuneelWorkSpace/adwi/bin:$PATH"' >> ~/.zshrc
```

**Validate:** `which adwi` → should show `~/SuneelWorkSpace/adwi/bin/adwi`

---

## Step 2 — Python venv

The repo uses Python 3.14 via `uv`. You can use 3.12+ if 3.14 is unavailable.

```bash
# Install uv if not present
curl -Ls https://astral.sh/uv/install.sh | sh

# Create venv in the expected location
cd ~/SuneelWorkSpace/adwi
uv venv --python 3.14   # or: uv venv --python 3.12

# Install core dependencies
.venv/bin/pip install \
    prompt_toolkit \
    instructor \
    openai \
    qdrant-client \
    faster-whisper \
    markitdown \
    requests \
    httpx

# Optional but recommended
.venv/bin/pip install \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp \
    langchain \
    langgraph \
    arize-phoenix
```

**Validate:** `adwi/.venv/bin/python3 -c "import prompt_toolkit; print('OK')"` → `OK`

> **Note:** `adwi/.venv/` is gitignored. You must recreate it on each machine.

---

## Step 3 — Ollama + models

```bash
# Install Ollama via Homebrew
brew install ollama
brew services start ollama

# Wait for Ollama to start (takes 5–10 seconds)
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do sleep 2; done
echo "Ollama ready"

# Pull required models (large — 30+ GB total, takes time)
ollama pull llama3.1:8b          # NLU classifier (~4.9 GB)
ollama pull nomic-embed-text     # Embeddings (~274 MB)
ollama pull qwen3:0.6b           # NLU fallback (~400 MB)

# Build the custom adwi model (requires qwen3:30b base — ~18 GB)
ollama pull qwen3:30b
ollama create adwi:latest -f ~/SuneelWorkSpace/adwi/Modelfile

# Optional: vision model
ollama pull minicpm-v:latest     # (~5 GB)
```

**Validate:**
```bash
ollama list | grep -E "adwi|llama3.1|nomic"
# Should show all three
curl -s http://localhost:11434/api/tags | python3 -c \
    "import sys,json; models=json.load(sys.stdin)['models']; print(f'{len(models)} models loaded')"
```

> **Storage note:** Full model stack is ~25–35 GB. Ollama stores models in `~/.ollama/` (not gitignored, not in this repo).

---

## Step 4 — Environment variables (secrets)

```bash
# Create config directory if missing (it should exist in the clone)
mkdir -p ~/SuneelWorkSpace/config

# Copy the example template
cp ~/SuneelWorkSpace/adwi/config/.env.example ~/SuneelWorkSpace/adwi/config/.env

# Edit and fill in real values
$EDITOR ~/SuneelWorkSpace/adwi/config/.env
```

Fill in at minimum:
- `TAVILY_API_KEY` — free at https://tavily.com (web search)
- `HOME_ASSISTANT_TOKEN` + `HOME_ASSISTANT_URL` — if you use Home Assistant
- `EXA_API_KEY` — optional, for Exa neural search
- `BRAVE_SEARCH_API_KEY` — optional, for Brave Search API web results
- `FIRECRAWL_API_KEY` — optional, for clean web scraping
- `JINA_API_KEY` — optional, for Jina Reader fallback page extraction

**Adwi will work in reduced mode without these.** Core functionality (local models, file ops, git, memory) works without any API keys. Search falls back to SearXNG and local fetch fallbacks only.

**Validate:** `adwi → /secrets-status` (after full setup)

---

## Step 5 — Docker services

```bash
cd ~/SuneelWorkSpace/adwi/infra/docker
docker compose up -d
```

This starts:
- Open WebUI :3000 (browser chat UI)
- n8n :5678 (automation workflows)
- SearXNG :8888 (local web search)
- Qdrant :6333 (vector DB for memory)
- Prometheus :9090, Loki :3100, Grafana :4000 (monitoring)

**Validate:**
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
curl -s http://localhost:8888/search?q=test&format=json | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print('SearXNG OK:', len(d.get('results',[])))"
curl -s http://localhost:6333/ | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print('Qdrant OK:', d.get('version'))"
```

> **n8n workflows:** Not automatically cloned. Export workflows from your old machine (n8n → Settings → Export) and import on the new one. Webhook secrets are machine-local.

---

## Step 6 — Obsidian bridge (MCP server)

The Obsidian bridge provides HTTP CRUD access to your vault at :5056.

```bash
cd ~/SuneelWorkSpace/adwi/services/mcp/obsidian-bridge
# Start it (stdlib-only — no pip install needed)
python3 server.py &
# Or use the bin script:
~/SuneelWorkSpace/adwi/bin/start-obsidian-bridge
```

**Validate:**
```bash
curl -s http://localhost:5056/ | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print('Bridge:', d.get('status'))"
```

---

## Step 7 — Safe Command API (for n8n / iPhone)

```bash
~/SuneelWorkSpace/adwi/bin/start-command-api
```

**Validate:** `curl -s http://localhost:5055/status-ai | head -5`

---

## Step 8 — LaunchAgents (optional but recommended for production use)

LaunchAgents run the 30-min backup, 2 AM nightly maintenance, and persistent services automatically.

```bash
# Install LaunchAgents
# (These plist files live in ~/Library/LaunchAgents/ — created by adwi /backup-enable)
adwi
/backup-enable     # installs adwi-git-backup LaunchAgent
```

To manually install the nightly agent:
```bash
# The plist must be created — run adwi and let it create the agent on first nightly run
# Or check notes/ADWI-START-HERE.md for the plist template
```

**Validate:** `launchctl list | grep com.suneel`

---

## Step 9 — NLU fixtures (Qdrant collection)

The NLU fast-path uses a Qdrant collection called `nlu_fixtures` with 96 seed scenarios for few-shot routing. Rebuild it after Qdrant is running:

```bash
cd ~/SuneelWorkSpace
python3 adwi/memory.py provision-nlu
```

**Validate:**
```bash
curl -s http://localhost:6333/collections/nlu_fixtures | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print('Fixtures:', d.get('result',{}).get('points_count'))"
# Should show ~96 points
```

---

## Step 10 — Rebuild gitignored databases (optional)

`adwi/memory.db` and `adwi/knowledge.db` are gitignored and must be rebuilt per-machine.

```bash
# memory.db (~2 minutes — indexes terminal history, git log, notes)
echo "/memory-scan
/exit" | python3 ~/SuneelWorkSpace/adwi/adwi_cli.py

# knowledge.db (~7 hours — deep knowledge indexer, run overnight)
nohup python3 ~/SuneelWorkSpace/adwi/overnight_learn.py \
    > /tmp/overnight-learn.log 2>&1 &
echo "overnight_learn running in background, PID: $!"
```

> These databases are local working state. Adwi works without them (falls back to direct LLM without memory injection). Rebuild during off-hours.

---

## Step 11 — Gmail auth (if using Gmail integration)

```bash
adwi
/gmail-auth    # walks through OAuth2 flow
```

The token is saved to `secrets/gmail-token.json` (gitignored). Repeat this step on each machine.

---

## Step 12 — Final validation

```bash
# Run the full environment validator
python3 ~/SuneelWorkSpace/adwi/scripts/validate_adwi_env.py

# Then do a smoke test
adwi
/doctor
/status
/capabilities
```

---

## What is machine-local vs repo-tracked

| Asset | Location | Tracked? | Rebuild how |
|-------|----------|----------|-------------|
| Source code | `adwi/`, `bin/`, etc. | ✅ Yes | `git clone` |
| Config template | `config/.env.example` | ✅ Yes | Already in repo |
| API keys | `config/.env` | ❌ No | Fill from template |
| Secrets/tokens | `secrets/` | ❌ No | Re-auth per machine |
| Python venv | `adwi/.venv/` | ❌ No | `uv venv` + pip |
| Ollama models | `~/.ollama/` | ❌ No | `ollama pull` |
| memory.db | `adwi/memory.db` | ❌ No | `/memory-scan` |
| knowledge.db | `adwi/knowledge.db` | ❌ No | `overnight_learn.py` |
| Docker runtime | `local-ai-stack/*-data/` | ❌ No | `docker compose up -d` |
| LaunchAgent plists | `~/Library/LaunchAgents/` | ❌ No | `/backup-enable` in adwi |
| Eval artifacts | `logs/simeval/*.md`, `*.json` | ✅ Yes (reports) | Reports tracked; large results are gitignored |
| Eval large results | `logs/simeval/large-*/` | ❌ No | `python3 logs/simeval/run_large_eval.py` |
| n8n workflows | n8n runtime DB | ❌ No | Manual export/import |

---

## Troubleshooting

### adwi starts but LLM calls time out
- Check Ollama: `curl http://localhost:11434/api/tags`
- Check models are pulled: `ollama list`
- On 8 GB RAM machines: `ollama pull qwen3:0.6b` and set `ADWI_LOCAL_MODEL=qwen3:0.6b` in `config/.env`

### Docker services fail to start
- Ensure Docker Desktop is running
- Check port conflicts: `lsof -i :3000 -i :5678 -i :8888 -i :6333`
- Check logs: `cd local-ai-stack && docker compose logs <service-name>`

### NLU routes everything to `chat`
- The NLU fixture collection may not be seeded: `python3 adwi/memory.py provision-nlu`
- Check Qdrant is running: `curl http://localhost:6333/`

### Voice input not working
- Install sox: `brew install sox`
- Install piper-tts: `pip install piper-tts` (in adwi/.venv)
- faster-whisper: `pip install faster-whisper`

### Eval harness fails to connect
- Requires Ollama with llama3.1:8b loaded
- Eval harness uses Ollama HTTP directly (not adwi_cli.py)
