#!/usr/bin/env bash
# Nightly README refresh — updates all READMEs, rebuilds root, validates, indexes, evolves.
# Runs at 00:00 via LaunchAgent com.suneelworkspace.readme.plist
set -uo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV_PY="$WORKSPACE/.venv/bin/python3"
LOG="$WORKSPACE/blood/logs/readme_intelligence.log"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

log() { echo "[$TIMESTAMP] $*" | tee -a "$LOG"; }

mkdir -p "$(dirname "$LOG")"
log "=== Nightly README refresh started ==="

# Step 1: Update all READMEs (rule-based, no Claude API cost)
log "Step 1/10: Updating all folder READMEs..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/run_update_all.py" --no-claude --quiet \
   >> "$LOG" 2>&1; then
  log "  ✅ All READMEs updated"
else
  log "  ⚠️  Some READMEs failed (non-fatal, continuing)"
fi

# Step 2: Rebuild root README
log "Step 2/10: Rebuilding root README..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/root_synthesizer.py" >> "$LOG" 2>&1; then
  log "  ✅ Root README rebuilt"
else
  log "  ❌ Root rebuild failed"
fi

# Step 3: Rebuild dependency map (fixed: no heredoc, uses temp script)
log "Step 3/10: Rebuilding dependency map..."
TMPSCRIPT="$(mktemp /tmp/readme_depmap_XXXXXX.py)"
cat > "$TMPSCRIPT" << EOF
import sys, json, datetime
sys.path.insert(0, '$WORKSPACE')
from hands.automation.readme.intelligence_engine import analyze_workspace, build_dependency_map
analyses = analyze_workspace('$WORKSPACE')
dep_map = build_dependency_map(analyses)
out = {'generated': datetime.datetime.now().isoformat(), 'folder_count': len(dep_map), 'folders': dep_map}
open('$WORKSPACE/spine/readme_dependency_map.json', 'w').write(json.dumps(out, indent=2))
print(f'Wrote {len(dep_map)} entries to dependency map')
EOF
if "$VENV_PY" "$TMPSCRIPT" >> "$LOG" 2>&1; then
  log "  ✅ Dependency map rebuilt"
else
  log "  ⚠️  Dependency map failed (non-fatal)"
fi
rm -f "$TMPSCRIPT"

# Step 4: Validate
log "Step 4/10: Running validation..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/validator.py" >> "$LOG" 2>&1; then
  log "  ✅ Validation passed"
else
  log "  ❌ Validation failed — check $LOG"
fi

# Step 5: Build knowledge index
log "Step 5/10: Building knowledge index..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/knowledge_indexer.py" >> "$LOG" 2>&1; then
  log "  ✅ Knowledge index built"
else
  log "  ⚠️  Knowledge index failed (non-fatal)"
fi

# Step 6: Trigger lab evolution for low-health folders
log "Step 6/10: Checking for low-health folders (threshold=60)..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/lab_bridge.py" --threshold 60 >> "$LOG" 2>&1; then
  log "  ✅ Lab bridge check complete"
else
  log "  ⚠️  Lab bridge failed (non-fatal)"
fi

# Step 7: Compute priority queue
log "Step 7/10: Computing priority queue..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/priority_engine.py" --rebuild >> "$LOG" 2>&1; then
  log "  ✅ Priority queue updated"
else
  log "  ⚠️  Priority queue failed (non-fatal)"
fi

# Step 8: Record trend snapshot
log "Step 8/10: Recording health trend snapshot..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/trend_analytics.py" --record >> "$LOG" 2>&1; then
  log "  ✅ Trend snapshot recorded"
else
  log "  ⚠️  Trend snapshot failed (non-fatal)"
fi

# Step 9: Auto-repair SAFE issues
log "Step 9/10: Auto-repairing SAFE issues..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/auto_repair_engine.py" >> "$LOG" 2>&1; then
  log "  ✅ Auto-repair complete"
else
  log "  ⚠️  Auto-repair failed (non-fatal)"
fi

# Step 10: Self-reflection
log "Step 10/10: Running self-reflection..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/self_reflection.py" >> "$LOG" 2>&1; then
  log "  ✅ Self-reflection complete"
else
  log "  ⚠️  Self-reflection failed (non-fatal)"
fi

# Step 11: Auto-commit README + state changes
log "Step 11/12: Auto-committing changes..."
if "$VENV_PY" "$WORKSPACE/hands/automation/git/auto_commit.py" >> "$LOG" 2>&1; then
  log "  ✅ Auto-commit complete"
else
  log "  ⚠️  Auto-commit failed (non-fatal — changes preserved locally)"
fi

# Step 12: Auto-push (only if auto_push=true in spine/readme_policy.json)
AUTO_PUSH=$(python3 -c \
  "import json; d=json.load(open('$WORKSPACE/spine/readme_policy.json')); print(str(d.get('auto_push',False)).lower())" \
  2>/dev/null || echo "false")
log "Step 12/12: Auto-push check (enabled=$AUTO_PUSH)..."
if [[ "$AUTO_PUSH" == "true" ]]; then
  if "$WORKSPACE/hands/bin/git-safe-push" >> "$LOG" 2>&1; then
    log "  ✅ Auto-push succeeded"
  else
    log "  ⚠️  Auto-push failed (commit preserved — check pre-push guard log)"
  fi
else
  log "  ℹ️  Auto-push disabled (set auto_push=true in spine/readme_policy.json to enable)"
fi

# Notify nervous system
"$VENV_PY" "$WORKSPACE/nervous/nerve_propagator.py" notify spine "nightly_readme_refresh" \
  >> /dev/null 2>&1 || true

log "=== Nightly README refresh complete (12 steps) ==="
