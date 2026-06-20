# Adwi System Inspection

Date: 2026-06-20 10:45:14


## System
- **OS:** 26.5.1
- **Architecture:** arm64
- **Hostname:** SuneelKumarBikkasani
- **CPU:** Apple M4 Max
- **RAM:** 64GB
- **Disk /:** /dev/disk3s1s1   926Gi    12Gi   692Gi     2%    459k  4.3G    0%   /
- **PATH:** /Users/MAC/.bun/bin:/Users/MAC/.local/bin:/Users/MAC/SuneelWorkSpace/adwi/bin:/Users/MAC/.abacusai/bin:/Users/MAC/.local

## Homebrew
- ✓ **brew:** Homebrew 6.0.2
- ✓ **git:** git version 2.54.0
- ✓ **gh:** gh version 2.94.0 (2026-06-10)
- ✓ **node:** v26.3.0
- ✓ **python3:** Python 3.14.5
- ✓ **docker:** Docker version 29.5.3, build d1c06ef6b4
- ✓ **ollama:** ollama version is 0.30.7
- ✓ **uv:** uv 0.11.21 (Homebrew 2026-06-11 aarch64-apple-darw
- ✗ **ffmpeg:** 

## Python
- **python3:** Python 3.14.5
- **pip3:** pip 26.1.1 from /opt/homebrew/lib/python3.14/site-packages/pip (python 3.14)
- **uv:** uv 0.11.21 (Homebrew 2026-06-11 aarch64-apple-darwin)
- **uvx:** uvx 0.11.21 (Homebrew 2026-06-11 aarch64-apple-darwin)

## Node / npm / npx
- **node:** v26.3.0
- **npm:** 11.16.0
- **npx:** 11.16.0

## Docker
- ✓ **docker:** Docker version 29.5.3, build d1c06ef6b4
  - suneel-open-webui (Up 3 days (healthy))
  - suneel-grafana (Up 3 days)
  - suneel-qdrant (Up 3 days)
  - suneel-cadvisor (Up 3 days (healthy))
  - suneel-loki (Up 3 days)
  - suneel-prometheus (Up 3 days)
  - suneel-node-exporter (Up 3 days)
  - suneel-searxng (Up 3 days)
  - suneel-n8n (Up 3 days)
  - suneel-promtail (Up 4 days)
  - suneel-cloudflared (Up 5 days)
  - suneel-homeassistant (Up 4 days)

## AI Services
- ✓ **Ollama :11434:** online
- ✓ **Open WebUI :3000:** online
- ✓ **n8n :5678:** online
- ✓ **SearXNG :8888:** online
- ✓ **Safe API :5055:** online
- ✓ **Qdrant :6333:** online
- ✗ **LocalAI :8080:** offline
- ✗ **ComfyUI :8188:** offline

## Ollama Models
  - minicpm-v:latest           c92bfad01205    5.5 GB    5 days ago
  - qwen3:0.6b                 7df6b6e09427    522 MB    5 days ago
  - adwi:latest                43cb05eda51d    18 GB     5 days ago
  - nomic-embed-text:latest    0a109f422b47    274 MB    6 days ago
  - qwen3:30b                  ad815644918f    18 GB     6 days ago
  - llama3.1:8b                46e0c10c039e    4.9 GB    7 days ago

## Adwi Files
- ✓ **SuneelWorkSpace/adwi/adwi_cli.py:** 561KB
- ✓ **SuneelWorkSpace/adwi/bin/adwi:** 0KB
- ✓ **SuneelWorkSpace/adwi/model-routing.env:** 0KB
- ✓ **SuneelWorkSpace/adwi/capabilities.json:** 48KB
- ✓ **SuneelWorkSpace/adwi/repair.py:** 22KB
- ✓ **SuneelWorkSpace/adwi/backup.py:** 24KB

## Model Routing
- **backend:** local
- **cloud model:** models/gemini-2.5-flash
- **local model:** adwi:latest

## MCP Servers
- **Configured servers:** 10
  - playwright
  - fetch
  - github
  - sqlite
  - memory
  - sequential-thinking
  - qdrant
  - comfyui
  - adwi-sandbox
  - filesystem

## Bin Scripts
- ✓ **adwi:** executable
- ✓ **adwi-e2e-status-reader:** executable
- ✓ **adwi-git-backup:** executable
- ✓ **adwi-nightly:** executable
- ✓ **adwi-route:** executable
- ✓ **adwi-scheduled-send-runner:** executable
- ✓ **adwi-secrets-edit:** executable
- ✓ **adwi-secrets-status:** executable
- ✓ **adwi-self-heal:** executable
- ✓ **adwi-start-localai:** executable
- ✓ **adwi.backup.20260614-090424:** executable
- ✓ **ask-ai-profile:** executable
- ✓ **auto-ai-maintenance:** executable
- ✓ **auto-update-readme:** executable
- ✓ **benchmark-adwi:** executable
- ✓ **check-github-latest-release:** executable
- ✓ **cliprun:** executable
- ✓ **cr:** executable
- ✓ **daily-ai-status-report:** executable
- ✓ **generate-manifest:** executable
- ✓ **git-status-workspace:** executable
- ✓ **index-ai-notes:** executable
- ✓ **logs-ai:** executable
- ✓ **mcp-status:** executable
- ✓ **plan-local-task:** executable
- ✓ **rag-index:** executable
- ✓ **save-youtube-summary:** executable
- ✓ **show-ai-tree:** executable
- ✓ **start-ai:** executable
- ✓ **start-command-api:** executable
- ✓ **start-homeassistant:** executable
- ✓ **start-openwebui-knowledge-watcher:** executable
- ✓ **start-phoenix:** executable
- ✓ **status-ai:** executable
- ✓ **status-command-api:** executable
- ✓ **status-openwebui-knowledge-watcher:** executable
- ✓ **stop-ai:** executable
- ✓ **stop-command-api:** executable
- ✓ **stop-openwebui-knowledge-watcher:** executable
- ✓ **stop-phoenix:** executable
- ✓ **summarize-url:** executable
- ✓ **summarize-youtube:** executable
- ✓ **suneel-command-api:** executable
- ✓ **sync-openwebui-knowledge:** executable
- ✓ **validate-docs:** executable
- ✓ **watch-openwebui-knowledge:** executable

## Secrets (names only)
  - OPENWEBUI_URL: [REDACTED]
  - OPENWEBUI_API_KEY: [REDACTED]
  - OPENWEBUI_KNOWLEDGE_ID: [REDACTED]
  - OPENWEBUI_JWT_TOKEN: [REDACTED]
  - GOOGLE_CLIENT_ID: [REDACTED]
  - GOOGLE_CLIENT_SECRET: [REDACTED]
  - GOOGLE_PROJECT_ID: [REDACTED]
  - GITHUB_TOKEN: [REDACTED]

## Git Backup
- ✓ **git repo:** main
- **remote:** https://github.com/sndboxTesting/adwi.git
- **last commit:** f24c299 feat: add PRIMEFILE-005 test-count check + refresh system_manifest.json
- **pending files:** 11

## Action Log Summary
- **Total action logs:** 716
- **Repair logs:** 1

## RAG Index
- **Documents indexed:** 64