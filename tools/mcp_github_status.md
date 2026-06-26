# GitHub MCP Integration Status

- **Status**: Enabled (via local wrapper)
- **Scope**: Bounded to target repositories
- **CLI Executable**: `bin/github-mcp`
- **MCP Resource**: `workspace://github/status`

## Operational Safety
- Outbound mutations (like PR merges, commits, issue creations) require confirmation and approval before execution.
- Reads are safe to perform automatically.
