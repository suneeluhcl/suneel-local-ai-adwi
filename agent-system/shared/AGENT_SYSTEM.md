@~/.claude/RTK.md

# Shared Agent System

## Purpose

This is the canonical instruction source for Suneel's living shared agent workspace at `~/SuneelWorkSpace`.

Claude Code and Codex CLI must use this workspace as the shared source for instructions, identity/context, memory, task state, logs, maintenance state, and session handoffs.

## Source Of Truth

- Canonical workspace: `~/SuneelWorkSpace`
- Canonical instruction file: `~/SuneelWorkSpace/agent-system/shared/AGENT_SYSTEM.md`
- Workspace entrypoints: `~/SuneelWorkSpace/AGENTS.md` and `~/SuneelWorkSpace/CLAUDE.md`
- Codex global entrypoint: `~/.codex/AGENTS.md`
- Claude global entrypoint: `~/.claude/CLAUDE.md`

If instructions conflict inside this workspace, the canonical shared docs under `~/SuneelWorkSpace/agent-system/` are the source of truth. Project-specific instructions may add local detail, but they must not weaken safety boundaries.

## Rules

- Keep shared state file-based, transparent, and easy to inspect.
- Prefer clean organization, minimal duplication, and a single source of truth.
- Keep real source files under `~/SuneelWorkSpace` whenever possible.
- Use symlinks or thin loader files outside the workspace only when a tool needs global discovery.
- Do not perform purchases, billing changes, account upgrades, or other money-related actions.
- Avoid destructive actions. Do not delete or overwrite important files without a timestamped backup and clear reason.
- Before changing files, inspect relevant existing files and prefer upgrading over recreating.
- Perform approved local setup actions directly when safe instead of asking Suneel to copy and paste commands.
- Explain work clearly and step by step because Suneel is new to development.
- Leave a concise, high-value handoff for the next agent.

## Startup

Before meaningful work, read these files in order:

1. `~/SuneelWorkSpace/agent-system/shared/AGENT_SYSTEM.md`
2. `~/SuneelWorkSpace/agent-system/shared/IDENTITY.md`
3. `~/SuneelWorkSpace/agent-system/shared/WORKFLOW_RULES.md`
4. `~/SuneelWorkSpace/agent-system/shared/SAFETY_BOUNDARIES.md`
5. `~/SuneelWorkSpace/agent-system/shared/STARTUP_CHECKLIST.md`
6. `~/SuneelWorkSpace/agent-system/memory/MEMORY.md`
7. `~/SuneelWorkSpace/agent-system/memory/DECISIONS.md`
8. `~/SuneelWorkSpace/agent-system/tasks/ACTIVE_TASKS.md`
9. `~/SuneelWorkSpace/agent-system/tasks/TASK_QUEUE.md`
10. `~/SuneelWorkSpace/agent-system/memory/SESSION_HANDOFF.md`
11. `~/SuneelWorkSpace/agent-system/state/CURRENT_STATE.json`
12. `~/SuneelWorkSpace/agent-system/state/WORKSPACE_HEALTH.json`

Use `~/SuneelWorkSpace/bin/agent-start` or `~/SuneelWorkSpace/bin/workspace-context` to print the startup brief.

Mandatory startup behavior:

- State: "Loading workspace context".
- Read the startup checklist files before making meaningful changes.
- Summarize current state, health, active tasks, and latest handoff before acting.
- If a previous session was left open, run or rely on `agent-start` fail-safe recovery to checkpoint it.

## Closeout

After completing meaningful work, update:

- `agent-system/memory/SESSION_HANDOFF.md`
- `agent-system/tasks/ACTIVE_TASKS.md` and/or `agent-system/tasks/COMPLETED_TASKS.md`
- `agent-system/logs/SESSION_LOG.md`
- `agent-system/state/CURRENT_STATE.json`
- `agent-system/state/WORKSPACE_HEALTH.json` if system condition changed
- `agent-system/memory/MEMORY.md` or `agent-system/memory/DECISIONS.md` if durable knowledge was created

Use `~/SuneelWorkSpace/bin/agent-finish "summary"` for simple closeouts.

Automatic closeout:

- `use-codex`, `use-claude`, and shell exit hooks run `agent-autoclose` automatically.
- Manual `agent-finish` is no longer required for normal operation.
- Agents must still attempt to update handoff, logs, memory, decisions, and tasks before finishing when they can.
- If an agent misses closeout, the next startup must detect the open session and repair it with `agent-autoclose --startup-recovery`.

## Memory Policy

Put stable facts in `MEMORY.md`.

Put important choices and their reasons in `DECISIONS.md`.

Use `NOTES.md` for temporary notes that should not become permanent truth yet.

Do not store secrets, tokens, passwords, private keys, billing data, or financial details in shared memory.

## Task Policy

Use `ACTIVE_TASKS.md` for current work.

Use `TASK_QUEUE.md` for queued future work.

Move completed work to `COMPLETED_TASKS.md` with the date and a short result.

Keep task entries short enough for future agents to scan quickly.

## Handoff Policy

`SESSION_HANDOFF.md` should always describe:

- What was requested.
- What changed.
- What was verified.
- What remains.
- Risks, limits, or follow-up recommendations.

## Maintenance Policy

- Use `agent-doctor` to inspect workspace health.
- Use `agent-repair` to safely fix small issues.
- Use `agent-maintain` for recurring health, repair, index, backup, and report refresh.
- Use `agent-autoclose` for automatic, idempotent session checkpointing on wrapper exit, shell exit, and startup recovery.
- Use `autolab/` for bounded workspace self-improvement experiments. Autolab may improve prompts, docs, scripts, reports, and repair logic only within its mutation policy.
- Autolab changes must be measurable, reversible, logged, and kept only when safety gates pass and score improves.

## Autolab Startup Note

If a user asks for workspace self-improvement, read:

1. `~/SuneelWorkSpace/autolab/program.md`
2. `~/SuneelWorkSpace/autolab/mutation_policy.md`
3. `~/SuneelWorkSpace/autolab/safeguards.md`
4. `~/SuneelWorkSpace/autolab/evaluator.md`
5. `~/SuneelWorkSpace/autolab/current_frontier.md`
- Log maintenance in `agent-system/logs/MAINTENANCE_LOG.md`.
- Track health in `agent-system/state/WORKSPACE_HEALTH.json`.
- Track file locations in `agent-system/state/INDEX.json`.

## Safety Boundaries

See `agent-system/shared/SAFETY_BOUNDARIES.md`.

Short version:

- No money actions.
- No destructive actions without explicit approval and backup where applicable.
- No blind merges between similar workspace folders.
- No complicated database or external service for shared state.
- No hidden state when a plain file will work.

## gstack Skills Available

gstack is installed at `~/.claude/skills/gstack/`. These skills are invoked as slash commands at the start of a Claude Code session to activate a specialist reasoning mode.

**Claude should dynamically choose a gstack skill when the task warrants it. Prefer structured thinking over generic responses.**

| Skill | When to use |
|---|---|
| `/investigate` | Debugging — unknown root cause, multi-file failures, intermittent errors |
| `/cso` | Security — before shipping auth/input/API changes; any security audit |
| `/review` | Code quality — after implementation, before commit |
| `/office-hours` | Planning — before decomposing a new goal; validate framing first |
| `/plan-eng-review` | Architecture — before building a new subsystem; lock interfaces |
| `/ship` | Release — test → version bump → CHANGELOG → PR in one flow |
| `/careful` | Scripting / file ops — preview destructive commands before running |
| `/qa` | UI testing — browser-based flow testing with auto bug filing |
| `/autoplan` | Full pipeline — runs CEO + design + eng review sequentially |

**Routing integration:** The orchestrator's `route-task` recommends a gstack skill alongside agent selection. The goal engine shows skill hints in task cards.

**Usage pattern:**
1. `route-task "describe your task"` → see recommended skill
2. Open Claude Code → type the skill name (e.g. `/investigate`)
3. Describe the task → skill activates its structured methodology

**Policy file:** `orchestrator/router/gstack_policy.json`

## Existing Note

Before this shared system was created, Claude had a global `CLAUDE.md` pointing at `@RTK.md`. That file was preserved in backups. It appeared to be a technical note, not the main workspace policy.

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (90-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk vitest run          # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%)
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->