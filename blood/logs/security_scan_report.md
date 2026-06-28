# Security Scan Report — 2026-06-28 10:38

**Files scanned:** 1229 | **Issues:** 4 (CRITICAL: 0, HIGH: 0, MEDIUM: 4)

## MEDIUM
- **heart/orchestrator/dag/dag_runner.py** line 71: eval() call (code injection risk)
- **lab/autolab/evaluator.py** line 153: os.system() call (prefer subprocess)
- **lab/autolab/evaluator.py** line 182: os.system() call (prefer subprocess)
- **brain/anticipation/execution_engine.py** line 162: shell=True in subprocess (injection risk)
