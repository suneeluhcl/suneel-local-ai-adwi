#!/usr/bin/env bash
set -euo pipefail
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$WORKSPACE"
source .venv/bin/activate 2>/dev/null || true
exec python3 tests/readme_sync.py "$@"
