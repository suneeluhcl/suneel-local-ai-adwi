# Decisions

## 2026-06-26 - Identity system integration

- Decision: Use `dna/identity/` as the source of truth for Suneel's voice, decision style, workflow preferences, and assistant feel.
- Reason: Future Claude, Codex, MCP, orchestrator, goal-engine, and comms behavior needs a shared plain-file identity source.
- Safety: Identity preferences do not override safety boundaries around destructive actions, money/account changes, external installs, private deep indexing, or outbound communication.

## 2026-06-26 - Adaptive identity loop

- Decision: Add `dna/dna/identity/adaptive/` as a bounded learning layer over the base identity.
- Reason: Suneel wants identity to improve from real behavior without becoming generic or drifting away from explicit preferences.
- Safety: Adaptation requires repeated signals, applies only small adjustments, and never overrides `dna/dna/identity/profile/identity_profile.md` or safety boundaries.

## 2026-06-26 - Predictive self-documenting workspace

- Decision: Add `brain/anticipation/` for suggest-only predictive intelligence and rebuild `README.md` as a complete system blueprint.
- Reason: Suneel wants the workspace to be proactive and understandable from README alone.
- Safety: Anticipation can suggest, pre-plan, and pre-compute, but cannot auto-execute actions or bypass approval gates.

## 2026-06-26 - Zero-gap README and intent contract

- Decision: Treat `README.md` as the executable system blueprint and zero-gap spec for all agents.
- Reason: Any agent should understand boot, identity, safety, commands, memory, capabilities, intent, and suggestions from README alone.
- Safety: Intent and ranked suggestions guide behavior only; they do not grant permission to auto-execute risky actions.

## 2026-06-24 - Use A File-Based Shared Agent Workspace

Decision: Use `~/SuneelWorkSpace` as the canonical local workspace for shared agent instructions, memory, tasks, logs, state, and handoffs.

Reason: File-based markdown and JSON are transparent, durable, easy to inspect, and usable by both Claude Code and Codex CLI without an external service.

## 2026-06-24 - Use One Canonical Instruction File

Decision: Use `~/SuneelWorkSpace/skeleton/rules/AGENT_SYSTEM.md` as the canonical shared instruction file.

Reason: A single source of truth avoids drift between `AGENTS.md`, `CLAUDE.md`, and global tool configuration.

## 2026-06-24 - Use Symlink Entrypoints When Possible

Decision: Point `AGENTS.md`, `CLAUDE.md`, `~/.hands/codex/AGENTS.md`, and `~/.claude/CLAUDE.md` to the canonical instruction file with symlinks when possible.

Reason: Symlinks keep instructions synchronized without copying content across files.

## 2026-06-24 - Add Safe Local Self-Maintenance

Decision: Add doctor, repair, maintain, index, backup, report, and context scripts under `~/SuneelWorkSpace/bin`, with implementation kept in readable local shell/Python.

Reason: Suneel wants a living workspace that stays healthy without remembering manual startup steps. Plain scripts and JSON reports provide this without an opaque database or external service.

## 2026-06-24 - Use One Lightweight launchd Job

Decision: Use one user-level launchd job for periodic lightweight maintenance when available.

Reason: A single local job is simpler and safer than multiple noisy watchers. Tool wrappers still run preflight maintenance before launching Claude or Codex.

## 2026-06-24 - Make Auto-Closeout The Default

Decision: Add `agent-autoclose` and run it from Claude/Codex wrappers, zsh shell exit hooks, inactivity maintenance, and startup recovery.

Reason: Suneel should not need to remember `agent-finish` for normal operation. Intentional agent-written closeout is still preferred when possible, but automatic persistence now provides the default safety net.

## 2026-06-24 - Add Workspace Autolab

Decision: Add `~/SuneelWorkSpace/lab/autolab/` as a safe autoresearch-style subsystem for iterative workspace self-improvement.

Reason: Suneel wants the workspace to improve its own prompts, rules, automation, wrappers, validation, reporting, repair logic, and operational behavior over time. Autolab uses file-based evaluation, snapshots, keep/revert decisions, and append-only experiment logs rather than model-weight training or opaque services.

## 2026-06-24 - Add Autolab v2 Meta-Learning

Decision: Extend Autolab with local meta-learning files, pattern analysis, failure intelligence, strategy versioning, and heuristic experiment selection.

Reason: The workspace should learn from its own experiment history. Patterns and failures remain plain JSON/Markdown files so Claude and Codex can inspect and share the same learning without external services.

## 2026-06-25 - Use Microsoft 365 Copilot as Prompt Engineer

Decision: Brainstorm new ideas in Microsoft 365 Copilot Chat (local Mac app) and paste its engineered prompts into the active workspace agents.

Reason: Copilot acts as a specialized prompt engineer to refine tasks, while the workspace agents execute them. Pasting Copilot-engineered prompts ensures high-quality planning and execution, and sharing the README provides Copilot with full context of SuneelWorkSpace.

## 2026-06-25 - Add Custom GStack Creator and Self-Repair Skills

Decision: Add `gstack-create` CLI utility to automate stubbing/linking new slash commands and deploy a dedicated `/self-repair` GStack reasoning mode for troubleshooting.

Reason: Level 1 of the video emphasizes skill creation and loop-engineered self-healing. Automating GStack creation makes it extremely easy to expand custom capabilities, while `/self-repair` provides a structured workflow for agents to debug failures, run workspace checks, apply fixes, and execute rollback procedures safely.

## 2026-06-25 - Add Custom /copilot-optimizer Skill

Decision: Add and register `/copilot-optimizer` custom GStack skill in the workspace.

Reason: To enable structured brainstorming and packaging of raw feature requests or codebase tasks into optimized prompts for Microsoft 365 Copilot Chat, ensuring final prompts generated by Copilot adhere to Suneel's workspace architecture (such as running `agent-doctor`, prefixing commands with `rtk`, and updating handoffs).
## 2026-06-25 - Research decision: Bounded self-upgrade validation

- Decision: Adopt a bounded local-first self-upgrade loop: audit, profile, gap analysis, recommendations, research artifacts, MCP resource coverage, and health integration may refresh autonomously; external installs, private data indexing, communication sends, money actions, and destructive changes require explicit approval.
- Source: `brain/research/decisions/20260625-232344-bounded-self-upgrade-validation-decision.md`


---
*Added by memory curator — 2026-06-28*

## New Entry

Ollama integration has added new models to model_registry.json and Hermes is configured for Ollama. A predictive maintenance system using blood/telemetry data should be developed.

