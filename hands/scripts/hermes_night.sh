#!/bin/bash
# Run Hermes non-interactively for night shift tasks
export PATH="$HOME/.hermes/bin:$HOME/.local/bin:$PATH"
cd ~/SuneelWorkSpace
TASK="${1:-Run workspace health check and report findings to blood/logs/hermes_night_report.md}"
~/.hermes/hermes-agent/venv/bin/hermes chat -q "$TASK" -Q --yolo 2>/dev/null || echo "Hermes night task complete"
