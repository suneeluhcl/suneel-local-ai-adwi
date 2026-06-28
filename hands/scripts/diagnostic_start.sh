#!/bin/bash
tmux new-session -d -s diagnostics \
  "cd ~/SuneelWorkSpace && python3 spine/diagnostics/diagnostic_scheduler.py 2>&1 | tee blood/logs/diagnostic_daemon.log"
echo "Diagnostic scheduler started in tmux session 'diagnostics'"
echo "   View: tmux attach -t diagnostics"
