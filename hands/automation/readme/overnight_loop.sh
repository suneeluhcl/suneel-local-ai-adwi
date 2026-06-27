#!/usr/bin/env bash
# Overnight autonomous test + repair loop.
# Runs every 30 minutes until STOP_HOUR (default 7 AM).
# Each iteration: CI → repair → README update → validate → auto-commit → push.
#
# Usage:
#   ./overnight_loop.sh              # runs until 7 AM
#   STOP_HOUR=9 ./overnight_loop.sh  # runs until 9 AM
#   INTERVAL=900 ./overnight_loop.sh # 15-min intervals instead of 30
set -uo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV_PY="$WORKSPACE/.venv/bin/python3"
LOG="$WORKSPACE/blood/logs/overnight_loop.log"
STOP_HOUR="${STOP_HOUR:-7}"
INTERVAL="${INTERVAL:-1800}"   # 30 minutes default

mkdir -p "$(dirname "$LOG")"

ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

ITERATION=0
TOTAL_FIXES=0
TOTAL_COMMITS=0
TOTAL_PUSH_OK=0
TOTAL_CI_PASS=0
TOTAL_CI_FAIL=0

log "╔══════════════════════════════════════════════════════════╗"
log "║   OVERNIGHT AUTONOMOUS LOOP — start                     ║"
log "║   Stop at: ${STOP_HOUR}:00 AM  |  Interval: ${INTERVAL}s            ║"
log "╚══════════════════════════════════════════════════════════╝"

run_iteration() {
  local iter=$1
  local FIXES=0
  local STEP_PASS=0
  local STEP_FAIL=0

  log ""
  log "━━━ Iteration $iter ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # ── Step 1: Workspace CI ────────────────────────────────────────
  log "[1/7] Running workspace CI..."
  if "$VENV_PY" "$WORKSPACE/hands/automation/ci/workspace_ci.py" >> "$LOG" 2>&1; then
    log "  ✅ CI passed"
    STEP_PASS=$((STEP_PASS + 1))
    TOTAL_CI_PASS=$((TOTAL_CI_PASS + 1))
  else
    log "  ❌ CI failed — continuing to repair"
    STEP_FAIL=$((STEP_FAIL + 1))
    TOTAL_CI_FAIL=$((TOTAL_CI_FAIL + 1))
  fi

  # ── Step 2: Python syntax sweep ─────────────────────────────────
  log "[2/7] Python syntax sweep..."
  SYNTAX_ERRORS=0
  while IFS= read -r pyfile; do
    if ! "$VENV_PY" -m py_compile "$pyfile" 2>/dev/null; then
      log "  ⚠️  Syntax error: $pyfile"
      SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
    fi
  done < <(find "$WORKSPACE" \
    -not -path "*/.venv/*" -not -path "*/__pycache__/*" \
    -not -path "*/.git/*"  -not -path "*/node_modules/*" \
    -name "*.py" -newer "$LOG" 2>/dev/null | head -100)
  if [[ "$SYNTAX_ERRORS" -eq 0 ]]; then
    log "  ✅ No syntax errors in recently changed files"
  else
    log "  ❌ $SYNTAX_ERRORS syntax error(s) found"
    STEP_FAIL=$((STEP_FAIL + 1))
  fi

  # ── Step 3: README update all ───────────────────────────────────
  log "[3/7] Updating all READMEs..."
  if "$VENV_PY" "$WORKSPACE/hands/automation/readme/run_update_all.py" \
      --no-claude --quiet >> "$LOG" 2>&1; then
    log "  ✅ READMEs updated"
    STEP_PASS=$((STEP_PASS + 1))
  else
    log "  ⚠️  Some READMEs failed (non-fatal)"
  fi

  # ── Step 4: SAFE auto-repair ────────────────────────────────────
  log "[4/7] Running SAFE auto-repair..."
  REPAIR_OUT=$("$VENV_PY" "$WORKSPACE/hands/automation/readme/auto_repair_engine.py" 2>&1 || true)
  echo "$REPAIR_OUT" >> "$LOG"
  DONE=$(echo "$REPAIR_OUT" | grep -oE 'Done: [0-9]+' | grep -oE '[0-9]+' || echo 0)
  FIXES=$((FIXES + DONE))
  TOTAL_FIXES=$((TOTAL_FIXES + DONE))
  log "  ✅ Repair: $DONE fix(es) applied this iteration"

  # ── Step 5: Rebuild root + validate ─────────────────────────────
  log "[5/7] Rebuild root README + validate..."
  "$VENV_PY" "$WORKSPACE/hands/automation/readme/root_synthesizer.py" >> "$LOG" 2>&1 || true
  if "$VENV_PY" "$WORKSPACE/hands/automation/readme/validator.py" >> "$LOG" 2>&1; then
    log "  ✅ Validation passed"
    STEP_PASS=$((STEP_PASS + 1))
  else
    log "  ❌ Validation failed"
    STEP_FAIL=$((STEP_FAIL + 1))
  fi

  # ── Step 6: Health score + priority queue ───────────────────────
  log "[6/7] Scoring health + refreshing priority queue..."
  "$VENV_PY" "$WORKSPACE/hands/automation/readme/priority_engine.py" --rebuild >> "$LOG" 2>&1 || true
  "$VENV_PY" "$WORKSPACE/hands/automation/readme/trend_analytics.py" --record >> "$LOG" 2>&1 || true
  SCORE=$("$VENV_PY" - <<'PYEOF' 2>/dev/null || echo "??"
import json
from pathlib import Path
cache = json.loads(Path('/Users/MAC/SuneelWorkSpace/spine/readme_health_cache.json').read_text())
scores = [v['health_score'] for v in cache.values() if isinstance(v, dict) and 'health_score' in v]
print(round(sum(scores)/len(scores), 1) if scores else 0)
PYEOF
)
  log "  📊 Health: ${SCORE}/100"

  # ── Step 7: Auto-commit + push ──────────────────────────────────
  log "[7/7] Auto-commit + push..."
  COMMIT_OUT=$("$VENV_PY" "$WORKSPACE/hands/automation/git/auto_commit.py" 2>&1 || true)
  echo "$COMMIT_OUT" >> "$LOG"
  if echo "$COMMIT_OUT" | grep -q "✅ Committed"; then
    TOTAL_COMMITS=$((TOTAL_COMMITS + 1))
    log "  ✅ Changes committed"
    # Push via git-safe-push --no-update (updates already ran above)
    if "$WORKSPACE/hands/bin/git-safe-push" --no-update >> "$LOG" 2>&1; then
      TOTAL_PUSH_OK=$((TOTAL_PUSH_OK + 1))
      log "  ✅ Pushed to remote"
    else
      log "  ⚠️  Push failed (commit preserved)"
    fi
  else
    log "  ℹ️  Nothing to commit"
  fi

  log "  Summary: pass=$STEP_PASS fail=$STEP_FAIL fixes=$FIXES health=${SCORE}/100"
}

# ── Main loop ────────────────────────────────────────────────────────────────
while true; do
  CURRENT_HOUR=$(date +%H | sed 's/^0//')
  if [[ "$CURRENT_HOUR" -ge "$STOP_HOUR" ]]; then
    break
  fi

  ITERATION=$((ITERATION + 1))
  run_iteration "$ITERATION"

  NEXT_RUN=$(date -v+${INTERVAL}S '+%H:%M' 2>/dev/null || date -d "+${INTERVAL} seconds" '+%H:%M' 2>/dev/null)
  log ""
  log "  💤 Sleeping ${INTERVAL}s — next run ~${NEXT_RUN} (stopping at ${STOP_HOUR}:00)"
  sleep "$INTERVAL"
done

# ── Final summary ────────────────────────────────────────────────────────────
log ""
log "╔══════════════════════════════════════════════════════════╗"
log "║   OVERNIGHT LOOP COMPLETE                               ║"
log "╠══════════════════════════════════════════════════════════╣"
log "║   Iterations    : $ITERATION"
log "║   CI pass/fail  : $TOTAL_CI_PASS / $TOTAL_CI_FAIL"
log "║   Fixes applied : $TOTAL_FIXES"
log "║   Commits made  : $TOTAL_COMMITS"
log "║   Pushes ok     : $TOTAL_PUSH_OK"
log "╚══════════════════════════════════════════════════════════╝"

# Notify nervous system
"$VENV_PY" "$WORKSPACE/nervous/nerve_propagator.py" notify spine \
  "overnight_loop_complete" "$LOG" >> /dev/null 2>&1 || true
