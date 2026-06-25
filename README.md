# SuneelWorkSpace

Welcome to the shared local workspace and control center for Suneel Bikkasani. Located at:

`~/SuneelWorkSpace`

This workspace is a unified orchestrator hub designed to coordinate and share context across multiple AI coding agents, including **Claude Code** (`swclaude`), **Codex CLI** (`swcodex`), **Gemini CLI** (`swgemini`), **OpenCode** (`swopencode`), and **Google Antigravity** (`agy`). By keeping a shared memory, task engine, routing protocol, and self-maintenance scripts, agents work collaboratively without stepping on each other's toes or resetting state.

---

## 📂 Workspace Subsystems

The workspace is organized into specific subsystems. Click any link below to explore the configuration and source code:

| Subsystem | Location | Description |
| :--- | :--- | :--- |
| **Core Shared State** | [agent-system](file:///Users/MAC/SuneelWorkSpace/agent-system) | Houses the shared agent system rule books, durable memory logs, active task tables, state JSON parameters, and closeout checklists. |
| **Unified CLI Bin** | [bin](file:///Users/MAC/SuneelWorkSpace/bin) | Hosts the executable tools, aliases, launchers, and automated scripts powering the workspace. |
| **Smart Router** | [orchestrator](file:///Users/MAC/SuneelWorkSpace/orchestrator) | Evaluates tasks against 14 distinct categories and routes them to the best-suited agent (Claude for reasoning/design; Codex for fast edits/scripts). |
| **Autonomous Goal Engine** | [goal-engine](file:///Users/MAC/SuneelWorkSpace/goal-engine) | Decomposes high-level objectives into dependency task graphs, automates step execution, monitors progress, and adapts to failures. |
| **Model Context Protocol (MCP)** | [mcp](file:///Users/MAC/SuneelWorkSpace/mcp) | Contains the local `workspace-brain` MCP server providing structured SQL/JSON API interfaces for agent memory, tasks, and state. |
| **Messaging Gateway** | [comms](file:///Users/MAC/SuneelWorkSpace/comms) | Hooks up local workflows to read, search, draft, and confirm iMessages and email communications. |
| **Experimental Autolab** | [autolab](file:///Users/MAC/SuneelWorkSpace/autolab) | Executes bounded self-improvement experiments on agent prompts and rule instructions, evaluating metric changes under strict safeguards. |
| **Workspace Automation** | [automation](file:///Users/MAC/SuneelWorkSpace/automation) | Handles periodic background tasks, health monitors, self-repair scripts, and launchd configuration services. |
| **Personal Obsidian Vault** | [obsidian-vault](file:///Users/MAC/SuneelWorkSpace/obsidian-vault) | Suneel's personal vault for daily notes, experimental ideation, prompts, templates, and Canvas maps. |
| **Development Projects** | [projects](file:///Users/MAC/SuneelWorkSpace/projects) | The destination for new code bases, repositories, and individual app directories. |
| **Snapshot Backups** | [snapshots](file:///Users/MAC/SuneelWorkSpace/snapshots) | Storage for offline dependencies (such as local `gstack` skill templates) and workspace restoration points. |

---

## 🛠️ CLI Command Reference

All agent command binaries are kept in the [bin](file:///Users/MAC/SuneelWorkSpace/bin) directory. Shorter terminal aliases are available in new sessions.

### 1. Core Agent & Session Control
- **`agent-start`** (Alias: `swroot` / `swstatus` equivalent): Initializes the workspace context, detects open sessions, and ensures state directories are prepared.
- **`agent-status`**: Displays active session information, current goals, active tasks, and the latest handoff.
- **`agent-finish "<summary>"`**: Runs the closeout checklist, drafts a session log entry, updates state JSONs, and gracefully ends the session.
- **`agent-autoclose`**: Checks in logs, state, and recent edits on shell exit or wrapper crash.

### 2. Maintenance & Health Checks
- **`agent-doctor`** (Alias: `swdoctor`): Evaluates directory integrity, verifies permissions, checks environment variables, and lists health reports.
- **`agent-repair`** (Alias: `swrepair`): Safely performs automated corrections of common workspace issues.
- **`agent-maintain`**: The central background master loop that updates health checks, executes self-repairs, refreshes indices, and creates backups.
- **`agent-test-loop`**: Runs end-to-end workspace tests and triggers a self-train, self-repair, and self-improving loop until the pass percentage reaches >= 99%.
- **`workspace-backup`**: Compiles a timestamped backup of core instruction files, configs, and state inside [.agent-backups](file:///Users/MAC/SuneelWorkSpace/.agent-backups).

### 3. Agent Launchers
- **`use-claude`** (Alias: `swclaude`): Spawns a Claude Code shell pre-configured with the workspace parameters and proxy paths.
- **`use-codex`** (Alias: `swcodex`): Spawns a Codex CLI shell configured with the workspace instructions.

### 4. Task Routing & Learning
- **`route-task "<task description>"`**: Recommends the ideal agent (Claude or Codex), confidence score, and suggests matching `gstack` cognitive mode.
- **`route-learn`**: Scans execution logs to update pattern profiling weights in [orchestrator/router/history.json](file:///Users/MAC/SuneelWorkSpace/orchestrator/router/history.json).

### 5. Autonomous Goal Management
- **`goal-create "<description>" --priority <lvl> --complexity <lvl>`**: Instantiates a new high-level goal in the system.
- **`goal-plan <goal_id>`**: Generates a dependencies task graph.
- **`goal-execute <goal_id>`**: Executes the next ready task in the graph (requires human confirmation before running).
- **`goal-status <goal_id>`**: Views structural completion percentage and task states.
- **`goal-adapt <goal_id>`**: Adapts to a failed task by retrying, swapping assigned agents, splitting the task, or skipping.

### 6. Local MCP Server Operations
- **`mcp-start`** / **`mcp-stop`** / **`mcp-status`**: Controls the daemon lifecycle for the local `workspace-brain` Model Context Protocol server.
- **`mcp-reindex`**: Rebuilds the fast SQLite search index database located in [mcp/server/storage/memory_index.db](file:///Users/MAC/SuneelWorkSpace/mcp/server/storage/memory_index.db).

### 7. Communications (iMessage & Mail)
- **`imsg-recent`** / **`imsg-search`**: Retrieves or filters recent local iMessages context.
- **`imsg-draft`** / **`imsg-send-confirmed`**: Generates draft messages or sends messages.
- **`mail-recent`** / **`mail-search`** / **`mail-draft-reply`**: Accesses and drafts replies to local mail workflows.
- **`comms-status`** / **`comms-doctor`**: Tests Full Disk Access permissions and handles notification gateways.

---

## ⚡ gstack specialist Reasoning Modes

For Claude Code sessions, **gstack** adds specialized expert methodologies (slash commands) loaded from `~/.claude/skills/gstack/`. 

### Available gstack Commands:
- `/investigate`: Debugging — 5-phase systematic root-cause analysis (Observe → Hypothesize → Test → Fix → Verify).
- `/cso`: Security — OWASP Top 10 + STRIDE threat modeling and trust boundary checks.
- `/review`: Code Quality — Review files for bug risks, edge cases, and standard optimizations.
- `/office-hours`: Scope Planning — Challenges design complexity and trims unnecessary work.
- `/plan-eng-review`: System Architecture — Locks interfaces and dependencies before building.
- `/ship`: Release Management — Test execution, version bumping, changelog compilation, and git commit/PR flow.
- `/careful`: Safe CLI Operations — Preview destructive commands before executing.
- `/qa`: Browser UI Testing — Automated client verification with bug-filing logic.
- `/autoplan`: CEO & Design Pipeline — Sequential automation of engineering design review.

### Supply Chain Protection:
To guard against silent updates, the workspace pins and verifies gstack files:
- **Pin File**: [mcp/config/gstack_version.json](file:///Users/MAC/SuneelWorkSpace/mcp/config/gstack_version.json) containing version `1.58.4.0` and commit `9fd03fae9e74f5daa7a138366aca8f86c7367c5c`.
- **`gstack-verify`**: Compares the live installation against the pin, alerting to integrity drift.
- **`gstack-repair [--upgrade]`**: Resets corrupted files or completes controlled upgrades after human review.

---

## 🔌 Headroom Context Compression

To optimize LLM token usage, all primary reasoning agents (Claude Code, Codex CLI, and Antigravity) are integrated with **Headroom**, a local context compression proxy:
- **Local Proxy URL**: Running at `http://127.0.0.1:8787` (intercepts and processes Anthropic/OpenAI API requests).
- **Token Savings**: Compresses prose and code contexts semantically, saving **~22-30% of input tokens** per session.
- **MCP Tool Integration**: The headroom MCP server is configured globally (exposing `headroom_compress`, `headroom_retrieve`, and `headroom_stats` tools to agents).
- **Downtime Monitoring**: The automated hourly maintenance loop and `agent-doctor` verify that the proxy is actively running on port `8787` and log warnings if it becomes inactive.

---


## 📄 Key Entrypoints & Guidance

- **Main Agent system Guidelines**: [agent-system/shared/AGENT_SYSTEM.md](file:///Users/MAC/SuneelWorkSpace/agent-system/shared/AGENT_SYSTEM.md) (Symlinked from root [AGENTS.md](file:///Users/MAC/SuneelWorkSpace/AGENTS.md) and [CLAUDE.md](file:///Users/MAC/SuneelWorkSpace/CLAUDE.md)).
- **Durable Memory & Facts**: [agent-system/memory/MEMORY.md](file:///Users/MAC/SuneelWorkSpace/agent-system/memory/MEMORY.md) and [agent-system/memory/DECISIONS.md](file:///Users/MAC/SuneelWorkSpace/agent-system/memory/DECISIONS.md).
- **Security & Integrity Policy**: [docs/GSTACK_INTEGRATION.md](file:///Users/MAC/SuneelWorkSpace/docs/GSTACK_INTEGRATION.md).

For detailed subsystem architectures, review the files in the [agent-system/docs/](file:///Users/MAC/SuneelWorkSpace/agent-system/docs) folder:
1. [HOW_IT_WORKS.md](file:///Users/MAC/SuneelWorkSpace/agent-system/docs/HOW_IT_WORKS.md) — Workflow patterns and core agent loops.
2. [FILE_MAP.md](file:///Users/MAC/SuneelWorkSpace/agent-system/docs/FILE_MAP.md) — Detailed mapping of all workspace data tracks.
3. [RECOVERY.md](file:///Users/MAC/SuneelWorkSpace/agent-system/docs/RECOVERY.md) — Repair procedures for state/index mismatches.
4. [AUTOMATION.md](file:///Users/MAC/SuneelWorkSpace/agent-system/docs/AUTOMATION.md) — Background services and agent-maintain details.
5. [OPERATOR_GUIDE.md](file:///Users/MAC/SuneelWorkSpace/agent-system/docs/OPERATOR_GUIDE.md) — Guide for using and extending commands.
