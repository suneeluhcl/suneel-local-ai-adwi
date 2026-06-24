# Adwi Pending Improvements

## 2026-06-18 02:00
```json

```

## 2026-06-19 02:00
```json
[Ollama error: timed out]
```

## 2026-06-20 02:00
```json
{"name":"email-ai","type":"command","title":"Secure Email Integration Command","description":"Sends emails via Safe API with tokenized permissions, no SMTP config needed","priority":"medium","effort":"hours","implementation_hint":"Extends the existing Safe Local Command API to add /email route using n8n's email module with permission-scoped tokens and audit logging."}
{"name":"codellama:7b","type":"model","title":"Add Codellama 7B for Code Tasks","description":"Enables efficient code generation and debugging within Ollama's local stack","priority":"high","effort":"minutes","implementation_hint":"Run `ollama pull codellama:7b`—fits 8B-35B range, complements existing models without exceeding M4 Max memory limits."}
{"name":"filesystem-mcp","type":"mcp","title":"Filesystem MCP Server for Safe Access","description":"Allows n8n to read/write files via API without direct shell access","priority":"medium","effort":"days","implementation_hint":"Builds on current command API with path validation, permission checks, and audit logs—avoids risky file operations."}
{"name":"model-update-workflow","type":"workflow","title":"Auto-Update Model Release Workflow","description":"Checks GitHub for new models daily and updates Ollama via approved commands","priority":"high","effort":"hours","implementation_hint":"Uses n8n to run `check-github-latest-release` then trigger `auto-ai-maintenance` with approval steps before model pull."}
{"name":"error-routing-fix","type":"fix","title":"Improved Command Error Handling","description":"Prevents wasted commands by verifying service status first (e.g., Ollama running)","priority":"medium","effort":"minutes","implementation_hint":"Modifies `status-ai` to check Ollama API endpoint before executing dependent commands, reducing failed workflows."}
```

## 2026-06-21 02:00
```json

```

## 2026-06-22 02:12
```json
[Ollama error: HTTP Error 500: Internal Server Error]
```

## 2026-06-22 14:32
```json
{"name":"search-note","type":"command","title":"Smart Note Search","description":"Search local notes by content using semantic embedding without leaving terminal.","priority":"high","effort":"hours","implementation_hint":"Build on nomic-embed-text model to create a CLI tool that queries Qdrant vector DB of note embeddings."}
{"name":"codellama:
```

## 2026-06-23 02:00
```json

```

## 2026-06-24 02:00
```json

```
