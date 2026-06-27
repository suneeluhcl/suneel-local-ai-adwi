#!/usr/bin/env bash
# Nightly README refresh — updates all READMEs, rebuilds root, validates.
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
log "Step 1/4: Updating all folder READMEs..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/run_update_all.py" --no-claude --quiet \
   >> "$LOG" 2>&1; then
  log "  ✅ All READMEs updated"
else
  log "  ⚠️  Some READMEs failed (non-fatal, continuing)"
fi

# Step 2: Rebuild root README
log "Step 2/4: Rebuilding root README..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/root_synthesizer.py" >> "$LOG" 2>&1; then
  log "  ✅ Root README rebuilt"
else
  log "  ❌ Root rebuild failed"
fi

# Step 3: Rebuild dependency map
log "Step 3/4: Rebuilding dependency map..."
if "$VENV_PY" - << 'PYEOF' >> "$LOG" 2>&1
import sys, json, datetime
sys.path.insert(0, '$WORKSPACE')
from hands.automation.readme.intelligence_engine import analyze_workspace, build_dependency_map
analyses = analyze_workspace()
dep_map = build_dependency_map(analyses)
out = {'generated': datetime.datetime.now().isoformat(), 'folder_count': len(dep_map), 'folders': dep_map}
open('$WORKSPACE/spine/readme_dependency_map.json', 'w').write(json.dumps(out, indent=2))
print(f'Wrote {len(dep_map)} entries to dependency map')
PYEOF
then
  log "  ✅ Dependency map rebuilt"
else
  log "  ⚠️  Dependency map failed (non-fatal)"
fi

# Step 4: Validate
log "Step 4/6: Running validation..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/validator.py" >> "$LOG" 2>&1; then
  log "  ✅ Validation passed"
else
  log "  ❌ Validation failed — check $LOG"
fi

# Step 5: Build knowledge index
log "Step 5/6: Building knowledge index..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/knowledge_indexer.py" >> "$LOG" 2>&1; then
  log "  ✅ Knowledge index built"
else
  log "  ⚠️  Knowledge index failed (non-fatal)"
fi

# Step 6: Trigger lab evolution for low-health folders
log "Step 6/6: Checking for low-health folders (threshold=60)..."
if "$VENV_PY" "$WORKSPACE/hands/automation/readme/lab_bridge.py" --threshold 60 >> "$LOG" 2>&1; then
  log "  ✅ Lab bridge check complete"
else
  log "  ⚠️  Lab bridge failed (non-fatal)"
fi

# Notify nervous system
"$VENV_PY" "$WORKSPACE/nervous/nerve_propagator.py" notify spine "nightly_readme_refresh" \
  >> /dev/null 2>&1 || true

log "=== Nightly README refresh complete (6 steps) ==="
