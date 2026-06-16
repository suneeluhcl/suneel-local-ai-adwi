# Adwi NLU Eval Session — session-20260615-185846
*Generated: 2026-06-15 18:58:48*

---

## 1. Run Summary

| Metric | Value |
|---|---|
| Total scenarios | 5 |
| Passed | 5 (100.0%) |
| Warned (close match) | 0 |
| Failed | 0 |
| Errors | 0 |
| Regex fast-path hits | 4 (80.0%) |
| LLM calls (llama3.1:8b) | 1 |
| Avg LLM latency | 2711 ms |
| P95 LLM latency | 2711 ms |

### Category Breakdown

| Category | Total | Pass | Warn | Fail | Error |
|---|---|---|---|---|---|
| disk | 5 | 5 | 0 | 0 | 0 |

---

## 2. Highest-Value Findings

### Failure Cluster Summary

| Failure Type | Count | Critical? |
|---|---|---|

### Latency Observations

- Average LLM latency: **2711 ms**
- P95 LLM latency: **2711 ms**

**Top 5 slowest prompts:**
  - 2711ms: `check my disk`

---

## 3. Safe Auto-Enhancements Applied

**None.** This was an evidence-collection session. No production files were modified.

---

## 4. Needs Human Review


---

## 5. Prioritized Fix Backlog

| Priority | Title | Count | Impact | Fix Surface |
|---|---|---|---|---|

---

## 6. New Eval Assets Created

- **0 new NLU fixture candidates** generated from routing failures
  - Written to: `/Users/MAC/SuneelWorkSpace/logs/simeval/session-20260615-185846/new_eval_assets.jsonl`
  - Review and add to `adwi/memory.py` NLU_SEED_FIXTURES if correct

---

*Session artifacts in: `/Users/MAC/SuneelWorkSpace/logs/simeval/session-20260615-185846`*
