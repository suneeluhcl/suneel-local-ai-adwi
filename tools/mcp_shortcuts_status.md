# macOS Shortcuts MCP Integration Status

- **Status**: Enabled (via local wrapper)
- **Scope**: Local macOS Shortcuts application list and execute commands
- **CLI Executable**: `bin/macos-shortcuts-mcp`
- **MCP Resource**: `workspace://shortcuts/status`

## Operational Safety
- Listing shortcuts is safe and run automatically.
- Running individual shortcuts is treated as a **CONTROLLED** action and requires explicit user confirmation.
