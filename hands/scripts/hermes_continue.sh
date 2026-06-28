#!/bin/bash
# Resume last Hermes session
export PATH="$HOME/.hermes/bin:$HOME/.local/bin:$PATH"
cd ~/SuneelWorkSpace
exec ~/.hermes/hermes-agent/venv/bin/hermes chat --continue
