# 📁 model_router

## 🧠 Purpose
Goal scheduling, task queue management, and model fallback routing

## ⚙️ Responsibilities
- Goal scheduling
- Task queue management
- Model fallback routing

## 🔗 System Role
Part of the **heart** organ in the 12-organ SuneelWorkSpace architecture.

## 📂 Contents
- `README.md`
- `__init__.py`
- `fallback_log.jsonl`
- `health_checker.py`
- `model_registry.json`
- `quota_state.json`
- `quota_tracker.py`
- `router.py`

## 🔄 Dependencies
- `heart/`

## 🧩 Interactions
Emits `readme_updated` events to nervous system on change.

## 📈 Current Capabilities
- Claude AI integration

## ⚠️ Gaps & Weaknesses
- No test coverage detected

## 🚀 Suggested Enhancements
- Add unit and integration tests
- Add priority queuing with SLA tracking

## 🔗 Connected Modules
- [`../heart/README.md`](../heart/README.md)


## 🏥 Health Score
🟡 **75/100**

| Category | Deduction |
|----------|----------|
| readme_drift | -15 |
| no_tests | -10 |

## 🔥 Critical Issues
- README is older than folder contents
- No test files detected

## ✅ Runtime Status
- Python files: 4 (4 valid, 0 broken)
- Shell scripts: 0 (0 valid)
- Tests detected: ❌

## 📝 Change Log (Auto)
- 2026-06-27: README auto-updated by README Intelligence System
- 2026-06-26: README auto-updated by README Intelligence System

## 🧬 State Alignment

**Status:** ⚠️ DRIFTED

**Ghost references (in README, not on disk):**
- `README.md` *(referenced but missing)*
- `fallback_log.jsonl` *(referenced but missing)*

**Wiring mismatches:**
- README links heart/ but not in dep map

*Last reconciled: 2026-06-27T02:24:15*

## 🎯 Intent Alignment

**Alignment:** ⚠️ PARTIAL (60/100)

*Last checked: 2026-06-27T02:24:15*

## 🌐 Failure Impact Map

**Blast Radius:** 🟡 3 folders affected if this fails

**Direct dependents:**
- `eyes/dashboard/`
- `eyes/dashboard/widgets/`
- `eyes/visual/`

**Cascade (depth 1-1):**
- Depth 1: `eyes/dashboard`, `eyes/dashboard/widgets`, `eyes/visual`

*Computed: 2026-06-27T02:24:15*

## 📈 Trends

**7-day trend:** ❓ INSUFFICIENT_DATA
*0 day(s) of history | updated daily by nightly automation*
