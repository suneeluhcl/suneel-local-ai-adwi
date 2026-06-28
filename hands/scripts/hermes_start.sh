#!/bin/bash
# Start Hermes Agent with workspace context
export PATH="$HOME/.hermes/bin:$HOME/.local/bin:$PATH"
cd ~/SuneelWorkSpace
echo "Starting Hermes Agent with SuneelWorkSpace context..."
exec ~/.hermes/hermes-agent/venv/bin/hermes chat
