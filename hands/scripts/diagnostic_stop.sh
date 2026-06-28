#!/bin/bash
tmux kill-session -t diagnostics 2>/dev/null && echo "Diagnostics stopped" || echo "Not running"
