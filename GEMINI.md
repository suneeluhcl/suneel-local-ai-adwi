# GEMINI.md — Gemini CLI Workspace Instructions
# This file is loaded automatically by `gemini` when run from ~/SuneelWorkSpace

## Identity

You are Gemini, operating inside Suneel's shared agent workspace at `~/SuneelWorkSpace`.

## Shared Workspace

This workspace is a central control center shared with Claude Code and Codex CLI. All agents read and write the same memory, task state, and handoff files.

## Optimization & MCP Infrastructure

- **Headroom**: A local proxy at `http://127.0.0.1:8787` that provides context compression. You have access to the `headroom` MCP server (with tools like `headroom_compress`, `headroom_retrieve`, and `headroom_stats`).
- **Workspace Brain**: You have access to the `workspace-brain` MCP server to interact programmatically with tasks, memory, decisions, and state files.
- **gstack**: Specialist reasoning templates (such as `/investigate` for debugging, `/cso` for security audits, and `/review` for quality checkups) are located in `~/.claude/skills/gstack/`. Since you do not run slash commands natively, you can read the instructions in these folders to guide your reasoning when assigned complex engineering, security, or planning tasks.

## Source Of Truth


- Canonical workspace: `~/SuneelWorkSpace`
- Canonical instructions: `~/SuneelWorkSpace/agent-system/shared/AGENT_SYSTEM.md`
- Memory: `~/SuneelWorkSpace/agent-system/memory/MEMORY.md`
- Active tasks: `~/SuneelWorkSpace/agent-system/tasks/ACTIVE_TASKS.md`
- Handoff: `~/SuneelWorkSpace/agent-system/memory/SESSION_HANDOFF.md`

## Startup

Before meaningful work, read:
1. `~/SuneelWorkSpace/agent-system/shared/AGENT_SYSTEM.md`
2. `~/SuneelWorkSpace/agent-system/memory/MEMORY.md`
3. `~/SuneelWorkSpace/agent-system/tasks/ACTIVE_TASKS.md`
4. `~/SuneelWorkSpace/agent-system/memory/SESSION_HANDOFF.md`

State "Loading workspace context" before starting meaningful work.

## Closeout

After meaningful work, update:
- `agent-system/memory/SESSION_HANDOFF.md`
- `agent-system/tasks/ACTIVE_TASKS.md`
- `agent-system/logs/SESSION_LOG.md`

## Rules (Same as All Agents)

- No money-related actions.
- No destructive actions without explicit approval and backup.
- Keep state file-based and human-readable.
- Prefer upgrading existing systems over creating parallel ones.
- Explain work clearly — Suneel is new to development.
- Leave a concise, useful handoff at the end of every session.
