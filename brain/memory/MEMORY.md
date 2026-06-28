# Shared Memory

## Durable Facts

- Canonical workspace path: `~/SuneelWorkSpace`.
- This workspace is shared by ALL agents: Antigravity (agy), Claude Code, Codex CLI, Gemini CLI, and OpenCode.
- All agents read and write the same shared memory, task state, handoff, and log files.
- Suneel may use any agent at any time — they all share one brain.
- Suneel wants local automation and workflows.
- Suneel is new to development and prefers clear, precise, step-by-step behavior.
- Approved local setup actions should be performed directly by the agent when safe.
- Avoid money-related actions.
- Avoid destructive actions without explicit approval.
- Prefer clean organization, minimal duplication, and a single source of truth.
- Suneel wants the workspace to feel alive, self-maintaining, self-repairing, and state of the art while staying simple and transparent.
- Suneel uses the Microsoft 365 Copilot Chat Mac app to brainstorm ideas and engineer prompts. These prompts are pasted into the active workspace agent, which must execute the instructions precisely while aligning with the workspace architecture.


## Environment Notes

- Suneel Bikkasani, Apple M4 Max, macOS 15.
- New projects should generally live under `~/SuneelWorkSpace/projects/`.
- Codex bootstrap files live in `~/SuneelWorkSpace/hands/codex/`.
- Adwi local AI OS archive: `https://github.com/sndboxTesting/adwi`.
- Background maintenance is local, lightweight, implemented with launchd calling workspace scripts.

## Agent Roster

- **Antigravity (agy)**: Primary orchestrator. Global: `~/.gemini/config/AGENTS.md`. Workspace: `~/SuneelWorkSpace/.agents/AGENTS.md`. MCP: headroom + workspace-brain.
- **Claude Code**: Deep coding. Global: `~/.claude/CLAUDE.md`. Workspace: `~/SuneelWorkSpace/CLAUDE.md` + `.claude/settings.local.json`.
- **Codex CLI**: Agentic runs. Global: `~/.hands/codex/AGENTS.md`. Config: `~/.hands/codex/config.toml`.
- **Gemini CLI**: Free fallback (1K req/day). Launch: `swgemini`. Config: `~/.gemini/settings.json`. Workspace: `~/SuneelWorkSpace/GEMINI.md`.
- **OpenCode**: Free fallback (Groq). Launch: `swopencode`. Config: `~/SuneelWorkSpace/opencode.json`.

## Token Optimization Infrastructure

- **Headroom proxy** at `http://127.0.0.1:8787`: Compresses context on every API call. Saves ~$197+ lifetime. Claude, Codex, and Antigravity all route through it.
- **RTK**: Auto-rewrites bash commands for 50-90% CLI output token savings. Configured as PreToolUse hook for Claude Code + workspace, and as a skill for Antigravity.
- **savings** alias: Run `savings` in terminal to see combined savings report.
- **workflow-audit**: Level 1 Agentic OS auditing tool. Analyzes prompt history to find repeated tasks and recommend new skills.
- **gstack-create**: Automates GStack skill stubbing and Claude Code slash-command symlinking.
- **self-repair skill**: A GStack reasoning skill (`/self-repair`) providing systematic diagnostic, health-check, code-fix, and rollback procedures.
- **copilot-optimizer skill**: A GStack reasoning skill (`/copilot-optimizer`) to brainstorm and package raw ideas into structured prompts optimized for Microsoft 365 Copilot Chat.


## Memory Rules

- Store only stable, useful facts here.
- Do not store secrets, tokens, passwords, private keys, billing data, or temporary noise.
- Prefer updating an existing bullet over adding duplicates.

## 2026-06-26 - Personal AI operating system upgrade

- The workspace now has a bounded system intelligence layer: `system-audit`, `system-gaps`, `system-capabilities`, `system-recommend`, and `improve-system`.
- Durable audit artifacts live in `spine/audit/`; safe machine metadata lives in `spine/system-context/system_profile.json`; local tool discovery lives in `spine/tools/`.
- The research engine lives in `brain/research/` and supports `idea-start`, `idea-run`, and lower-level `idea-*` scripts for idea capture, research plans, analyses, and decisions.
- Bounded self-upgrade policy is documented in `skeleton/rules/BOUNDED_SELF_UPGRADE.md`.

## 2026-06-26 - Suneel identity capture

- Identity subsystem lives in `dna/identity/`.
- Suneel's preferred voice is short, direct, casual, conversational, smart, structured, softened, and never harsh or condescending.
- Suneel prefers autopilot by default, with questions only for serious system risk or safety-gated actions.
- Suneel chooses tools by simplicity, cost, power, speed, then reliability.
- Hard boundary: never wipe the system or delete important files automatically.
- Adaptive identity loop lives in `dna/dna/identity/adaptive/` and learns slowly from accepted, edited, rejected, and adjusted outputs while preserving the original identity profile.
- Adaptive identity now uses weighted signals from `dna/dna/identity/adaptive/signal_weights.json` so rejected/manual/heavy-edit feedback influences learning more than simple acceptance.

## 2026-06-26 - Anticipatory intelligence

- Anticipation subsystem lives in `brain/anticipation/`.
- Prediction engine path: `brain/anticipation/prediction_engine.py`.
- Prediction memory path: `brain/anticipation/prediction_memory.json`.
- Current suggestions path: `brain/anticipation/action_suggestions.md`.
- Anticipation suggests next actions only; it never auto-executes or overrides safety boundaries.
- `README.md` is now the complete system blueprint and AI-agent drop-in context.
- Intent detection stores current intent in `brain/anticipation/current_context.json` using categories: messaging, email, research, system_improvement, development, idea_execution, maintenance, unknown.
- Suggestions are ranked with `frequency_weight + success_weight + recency_weight + identity_alignment + intent_alignment` and limited to top 3-5.
- Session boot contract in `README.md` requires agents to say `✅ Loading workspace shared brain` and confirm context loaded before meaningful work.


---
*Added by memory curator — 2026-06-28*

## Recent Projects

List of recent projects under `~/SuneelWorkSpace/projects/` to track progress and identify trends.

## Ollama Integration Progress

Summary of Ollama's integration with the workspace, including any new features or capabilities enabled by this integration.

