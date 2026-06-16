# Adwi NLU Eval — Master Analysis Report
*Generated: 2026-06-15 (post-unattended session)*
*Two canonical eval runs — 502 scenarios each*

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total scenarios | 502 |
| Pass | **310 (61.8%)** |
| Warn (close match) | 22 |
| **Fail** | **170** |
| Errors | 0 |
| Regex fast-path hits | 156 (31.1%) |
| LLM calls | 346 |
| Root-cause bugs found | **7 confirmed** |
| Dead-zone intents (0% pass) | **30** |
| Estimated pass rate after Tier 1 fixes | **~77–80%** |

**Bottom line:** Adwi's NLU has two structural weaknesses — (1) regex false-positives from missing word boundaries pollute the fast path, and (2) the `_INTENT_SYSTEM` prompt describes only 14 of 62 intents, leaving 48 for the LLM to guess without guidance. Fixing these two issues is expected to move the pass rate from 61.8% → ~78%.

---

## Cross-Session Validation: Parallel vs. Sequential

Two full runs were completed back-to-back:

| | Session 1 (parallel, workers=2) | Session 2 (sequential, workers=1) |
|-|-|-|
| Run ID | session-20260615-195428 | session-20260615-200525 |
| Pass | 310 (61.8%) | 310 (61.8%) |
| Fail | 170 | 170 |
| Avg LLM latency | **1757 ms** | **987 ms** |
| P95 LLM latency | **2048 ms** | **1227 ms** |

**Key finding:** Routing outcomes are **byte-for-byte identical** across both runs. The 4 `generate_image` misroutes and all 167 routing misses appear in both. This rules out parallel Ollama contamination as a cause of routing errors — contamination degrades latency (1757→987ms) but does NOT cause misrouting. The `generate_image` false activations are real LLM calibration failures.

Canonical run for all further analysis: **session-20260615-200525** (sequential, cleaner latency).

---

## Category Scoreboard

| Category | Total | Pass | Warn | Fail | Pass% | Status |
|----------|-------|------|------|------|-------|--------|
| exec | 4 | 4 | 0 | 0 | 100% | ✅ |
| ambiguous | 10 | 9 | 0 | 1 | 90% | ✅ |
| comms | 20 | 18 | 0 | 2 | 90% | ✅ |
| chat | 69 | 59 | 1 | 9 | 86% | ✅ |
| memory | 40 | 30 | 3 | 7 | 75% | ✅ |
| search | 20 | 15 | 2 | 3 | 75% | ✅ |
| meta | 24 | 18 | 0 | 6 | 75% | ✅ |
| media | 7 | 5 | 0 | 2 | 71% | ✅ |
| disk | 79 | 61 | 8 | 10 | 77% | ✅ |
| git | 38 | 20 | 1 | 17 | 53% | ⚠️ |
| system | 69 | 44 | 0 | 25 | 64% | ⚠️ |
| planning | 14 | 6 | 0 | 8 | 43% | ⚠️ |
| safety | 25 | 14 | 0 | 11 | 56% | ⚠️ |
| repair | 33 | 7 | 0 | 26 | 21% | 🔴 |
| vault | 10 | 0 | 7 | 3 | 0% | 🔴 |
| security | 3 | 0 | 0 | 3 | 0% | 🔴 |
| file | 10 | 0 | 0 | 10 | 0% | 🔴 |
| model | 12 | 0 | 0 | 12 | 0% | 🔴 |
| eval | 6 | 0 | 0 | 6 | 0% | 🔴 |
| voice | 9 | 0 | 0 | 9 | 0% | 🔴 |

---

## Root Cause Analysis: 7 Confirmed Bugs

### Bug 1 — Regex false positives: missing word boundaries
**Severity: HIGH | Fix type: Regex edit | File: `adwi/adwi_cli.py:522`**

The status regex `(is|are).{0,30}(running|working|up|down|online|healthy|alive)` has no word boundaries. Python `re.search` matches substrings, causing:

| Prompt | Substring match | Wrongly routed to |
|--------|-----------------|-------------------|
| "list files in my **downloads** folder" | `is`←"l**is**t", `down`←"**down**loads" | `status` |
| "is my **backup** recent" | `is` at start, `up`←"back**up**" | `status` |
| "this **downloads** fine" | `is`←"th**is**", `down`←"**down**loads" | `status` |

**Fix:** Add `\b` word boundaries to both groups:
```python
# Line 522 — before:
(re.compile(r"(is|are).{0,30}(running|working|up|down|online|healthy|alive)", re.I), "status"),
# After:
(re.compile(r"\b(is|are)\b.{0,30}\b(running|working|up|down|online|healthy|alive)\b", re.I), "status"),
```

---

### Bug 2 — Regex ordering: disk_usage fires before large_files
**Severity: HIGH | Fix type: Regex reorder | File: `adwi/adwi_cli.py:505,510`**

Line 505 (disk_usage): `(biggest|largest|heaviest|...).{0,40}(folder|file|directory|...)`
Line 510 (large_files): `(big(gest)?|large(st)?|heavy|huge|files? (over|...))`

The disk_usage pattern is a superset — it matches "biggest" + "file" before the large_files pattern gets a chance.

| Prompt | Expected | Got |
|--------|----------|-----|
| "what are the biggest files" | large_files | disk_usage |
| "largest files in my home directory" | large_files | disk_usage |
| "top 10 biggest files" | large_files | disk_usage |
| "files using the most space" | large_files | disk_usage |

**7 failures** from this single ordering error.

**Fix:** Two options (Option A preferred):

```python
# Option A: Narrow disk_usage to exclude file-object queries (disk/space/storage as object only)
(re.compile(r"(biggest|largest|heaviest|most space|taking up|using up|eating up).{0,40}(disk|storage|space)\b", re.I), "disk_usage"),
# AND move large_files first:
(re.compile(r"\b(big(gest)?|large(st)?|heavy|huge)\b.{0,40}\bfiles?\b", re.I), "large_files"),

# Option B: Move large_files regex above disk_usage (simpler but less precise)
```

---

### Bug 3 — Self-heal missed: status regex fires first for service errors
**Severity: MEDIUM | Fix type: Regex reorder | File: `adwi/adwi_cli.py:522,525`**

Status regex (line 522) catches `is...working` before self_heal regex (line 524) can check `not working...service`.

| Prompt | Expected | Got | Why |
|--------|----------|-----|-----|
| "docker is not working repair" | self_heal | status | `is` + `working` matches status first |
| "adwi isn't working properly" | self_heal | status | `is` + `working` matches status first |

**Fix:** Move self_heal block (`lines 524-525`) to appear **before** status block (`lines 522-523`).
Alternatively, the Bug 1 word-boundary fix eliminates `"is...working"` → but `"not working"` still contains `working` (a word). Test after applying Bug 1 fix to see if this resolves.

---

### Bug 4 — obsidian_search catches obsidian_daily
**Severity: MEDIUM | Fix type: Regex (new + reorder) | File: `adwi/adwi_cli.py:537`**

Line 537: `(open|read|show).{0,10}(obsidian|vault|note).{0,30}` → `obsidian_search`

This fires before any `obsidian_daily` pattern exists, swallowing all daily-note queries.

| Prompt | Expected | Got |
|--------|----------|-----|
| "read my daily note" | obsidian_daily | obsidian_search |
| "open today's note" | obsidian_daily | obsidian_search |
| "open my obsidian daily" | obsidian_daily | obsidian_search |

**Fix:** Insert before line 536 (before obsidian_search block):
```python
# Obsidian daily — must come before obsidian_search
(re.compile(r"(daily.?note|today.{0,5}note|obsidian.{0,5}daily|open.{0,10}today)", re.I), "obsidian_daily"),
```

---

### Bug 5 — `_INTENT_SYSTEM` underdescribes 48 of 62 intents (CRITICAL)
**Severity: CRITICAL | Fix type: _INTENT_SYSTEM expansion | File: `adwi/adwi_cli.py:779–823`**

The system prompt at lines 779–823 describes exactly **14 intents** with routing rules. The other **48** are listed in the schema enum but have no description. The LLM receives no guidance and falls back to `disk_usage`, `generate_image`, `status`, or `chat`.

**Described (14):** memory_recall, disk_usage, large_files, old_files, gmail, generate_image, web_search, status, sync, capabilities, daily_improve, fix_error, self_heal, backup_now, image, chat

**No description (48, includes all dead zones):** nightly_status, nightly_run, doctor, model_status, voice_in, voice_out, use_local, use_cloud, file_read, file_list, file_search, git_status, backup_status, backup_log, obsidian_daily, trusted_roots, patch_adwi, inspect_code, test_adwi, eval_adwi, eval_routing, memory_context, implement_idea, extract_ideas, tool_roadmap, trusted_roots, youtube, tavily_search, exa_search, route, ...

**Fix:** Add rules for highest-impact intents in `_INTENT_SYSTEM`. See §"_INTENT_SYSTEM Additions" below.

---

### Bug 6 — `generate_image` false activations (LLM calibration)
**Severity: HIGH | Fix type: _INTENT_SYSTEM constraint | File: `adwi/adwi_cli.py:791`**

The current rule is: `'generate_image' : generate/draw/create an image`

The LLM fires this for prompts containing adjacent words that trigger image associations:

| Prompt | Why LLM fires generate_image |
|--------|------------------------------|
| "what model is best for **code generation**" | word "generation" |
| "explain fine-tuning vs RAG" | possibly "tuning" (visual?) |
| "show me everything" | "show me" + "everything" → visual sweep |
| "explain the difference between ollama and openai api" | unknown trigger |

**Fix:** Add negative constraint to `_INTENT_SYSTEM`:
```
'generate_image' : ONLY when creating a brand-new image/picture/artwork/visual.
                   NOT for explanations, comparisons, code concepts, or questions
                   containing 'generation' as a concept (e.g. 'code generation').
                   If user says 'explain', 'what is', 'difference', 'compare' →
                   NEVER generate_image — use 'chat'.
```

---

### Bug 7 — git_status regex too narrow (11 routing misses)
**Severity: MEDIUM | Fix type: Regex expansion | File: `adwi/adwi_cli.py:550–551`**

Existing git regexes catch: `git <subcommand>`, `what changed`, `show commits`, `latest commit`, `my repos`.

**Missing patterns (11 failures):**

| Prompt | Got |
|--------|-----|
| "show recent commits" | chat |
| "what did I last commit" | memory_recall |
| "what's the current branch" | chat |
| "are there uncommitted changes" | disk_usage |
| "show changes since last commit" | chat |
| "git stat" | status |
| "staged files" | chat |
| "show unstaged changes" | status |
| "is the repo clean" | status |

**Fix:** Add before `generate_image` block:
```python
(re.compile(r"(show|what|are).{0,20}(recent commit|unstaged|staged|uncommitted|current branch|repo clean)\b", re.I), "git_status"),
(re.compile(r"(what.{0,10}(last|did).{0,10}commit|current branch|git (stat|diff|branch))\b", re.I), "git_status"),
```

---

## Dead-Zone Inventory

Intents with 0% pass rate, with concrete fix recommended:

| Intent | Failures | Fix Type | Concrete Fix |
|--------|----------|----------|--------------|
| fix_error | 15 | _INTENT_SYSTEM | Strengthen: "only when user pastes actual error class + message" (see Bug 6 fix approach) |
| git_status | 11 | Regex | Add broad git query patterns (see Bug 7) |
| nightly_status | 7 | Regex (new) | `(nightly.{0,10}(status\|log\|last run)\|when.{0,10}nightly)` |
| nightly_run | 3 | Regex (new) | `(run nightly\|trigger nightly\|nightly maintenance\|run.{0,10}daily)` |
| voice_out | 5 | Regex + sys | `\b(text.to.speech\|tts\|say.{0,15}aloud\|read.{0,10}aloud\|speak.{0,10}this)\b` |
| voice_in | 4 | Regex + sys | `\b(voice input\|voice mode\|start.{0,10}recording\|listen.{0,10}voice)\b` |
| patch_adwi | 4 | Regex + sys | `(patch adwi\|run aider\|self.improve\|update adwi)` |
| inspect_code | 4 | Regex + sys | `(inspect.{0,20}\.(py\|js\|ts)\|look at.{0,20}code)` |
| file_search | 4 | Regex (new) | `\b(find files?\|search for files?\|locate files?\|find all .+files)\b` |
| use_local | 4 | Regex (new) | `(switch to local\|use local model\|local llm\|use qwen\|use llama)` |
| model_status | 6 | Regex (new) | `(what model\|which model.{0,10}(active\|running\|using)\|current model)` |
| doctor | 6 | Regex (new) | `\b(run doctor\|full.{0,10}health check\|deep.{0,10}diag\|full diagnostic)\b` |
| obsidian_daily | 3 | Regex (new) | `(daily.?note\|today.{0,5}note\|obsidian.{0,5}daily)` — see Bug 4 |
| backup_status | 3 | Regex + bugfix | `(backup.{0,10}status\|last backup\|when.{0,10}backup)` + Bug 1 fix |
| file_list | 3 | Bug 1 fix | Fix word-boundary bug → stops "list files...downloads" → status |
| file_read | 3 | Regex (new) | `\b(read.{0,10}file\|show.{0,10}contents of\|open.{0,15}\.py\b)` |
| trusted_roots | 3 | _INTENT_SYSTEM | Add: `'trusted_roots': show allowed/blocked file paths` |
| use_cloud | 2 | Regex (new) | `(switch to cloud\|use cloud\|use gemini\|use gpt\|cloud model)` |
| backup_log | 2 | Regex (new) | `(backup log\|show.{0,10}backup.{0,10}log)` |
| eval_adwi | 2 | Regex (new) | `(run eval\|evaluate adwi\|adwi eval)` |
| test_adwi | 2 | Regex (new) | `(test adwi\|run.{0,10}adwi.{0,10}tests?)` |
| extract_ideas | 2 | _INTENT_SYSTEM | Add rule for extract_ideas |
| implement_idea | 2 | _INTENT_SYSTEM | Add rule for implement_idea |
| tool_roadmap | 2 | _INTENT_SYSTEM | Add rule for tool_roadmap |
| memory_context | 2 | _INTENT_SYSTEM | Add: `'memory_context': show current memory/context summary` |
| youtube | 2 | Regex (new) | `(youtube\.com\|youtu\.be).{0,30}(summarize\|watch\|explain)` |
| eval_routing | 1 | Regex (new) | `(run routing tests?\|routing eval\|test routing)` |
| route | 1 | Regex bug | "route this: how much disk..." — disk_usage regex fires on "how much disk" in body |
| tavily_search | 1 | Regex (new) | `\btavily\b` |
| exa_search | 1 | Regex (new) | `\bexa search\b` |

---

## Prioritized Fix Backlog

### Tier 1 — Quick regex wins (< 5 min each, no LLM impact)

Each fix below targets a specific file, line range, and is reversible in <1 min.

**P1.1 — Fix word-boundary bug in status regex** *(unlocks file_list + backup_status)*
- File: `adwi/adwi_cli.py:522`
- Expected gain: fixes ~3-5 false positives

**P1.2 — Swap large_files before disk_usage** *(fixes 7 routing misses)*
- File: `adwi/adwi_cli.py:505–510`
- Expected gain: +7 passes (large_files category 100%)

**P1.3 — Add obsidian_daily regex before obsidian_search** *(fixes 3)*
- File: `adwi/adwi_cli.py:536`, insert before
- Expected gain: +3 passes

**P1.4 — Add nightly_status + nightly_run regex** *(fixes 10)*
- File: `adwi/adwi_cli.py`, new block near system/status section
- Expected gain: +10 passes

**P1.5 — Add model_status regex** *(fixes 6)*
- File: `adwi/adwi_cli.py`, near status block
- Expected gain: +6 passes

**P1.6 — Add doctor regex before status** *(fixes 6)*
- File: `adwi/adwi_cli.py:524` (insert before status block)
- Expected gain: +6 passes

**P1.7 — Broaden git_status regex** *(fixes 11)*
- File: `adwi/adwi_cli.py:551`, add 2 patterns
- Expected gain: +11 passes

**P1.8 — Add voice_in / voice_out regex** *(fixes 9)*
- File: `adwi/adwi_cli.py`, new block
- Expected gain: +9 passes

**P1.9 — Add use_local / use_cloud regex** *(fixes 6)*
- File: `adwi/adwi_cli.py`, near model block
- Expected gain: +6 passes

**P1.10 — Add backup_status / backup_log regex** *(fixes 5)*
- File: `adwi/adwi_cli.py`, near backup section
- Expected gain: +5 passes

**P1.11 — Add file_list / file_read / file_search regex** *(fixes 10)*
- File: `adwi/adwi_cli.py`, new file-ops block (order: file_search BEFORE file_list)
- Expected gain: +10 passes

**P1.12 — Move self_heal before status** *(fixes ~2 service-error misroutes)*
- File: `adwi/adwi_cli.py:522–525` — swap blocks
- Expected gain: +2 passes

**P1.13 — Add eval/test regex** *(fixes 4)*
- Patterns: `(run eval|test adwi|routing tests|eval adwi)` → eval_adwi/eval_routing
- Expected gain: +4 passes

**Tier 1 total estimated gain: ~79 new passes → pass rate ~77.5%**

---

### Tier 2 — _INTENT_SYSTEM expansions (< 30 min total)

Edit `adwi/adwi_cli.py:779–823`:

**P2.1 — Constrain generate_image (eliminates 4 false activations)**
Add to generate_image rule:
```
   'generate_image' : ONLY when creating a NEW image/picture/artwork.
                      NEVER for explanations, comparisons, or prompts containing
                      'generation' as a concept (code generation, model generation).
                      'show', 'explain', 'what is', 'difference' → always use 'chat'.
```

**P2.2 — Add model/voice/file intent rules**
```
   'model_status'  : user asks what model adwi is currently using
   'use_local'     : switch to a local Ollama model (qwen, llama, etc.)
   'use_cloud'     : switch to a cloud model (gemini, gpt, etc.)
   'voice_in'      : activate voice input / microphone / speech recognition
   'voice_out'     : text-to-speech output / read aloud / speak text
   'file_read'     : read/show/display the contents of a specific file
   'file_list'     : list files in a specific directory or path
   'file_search'   : search/find files by name or pattern across filesystem
   'git_status'    : git repo status, branches, commits, changes, diff
   'doctor'        : deep health check and diagnostic — NOT 'status' (shallow check)
   'nightly_status': check nightly maintenance run results, last run time/log
   'nightly_run'   : trigger the nightly maintenance routine now
   'trusted_roots' : show which paths/directories adwi is allowed to read or write
   'backup_status' : show backup health, last backup time, backup git log
   'backup_log'    : show the backup history log file
   'memory_context': show the current conversation/session context summary
```

**P2.3 — Strengthen fix_error rule**
Current rule fires inconsistently. Strengthen to:
```
   'fix_error'     : user pastes an EXACT exception string containing an error class
                     (ModuleNotFoundError, TypeError, ValueError, AttributeError, etc.)
                     OR an HTTP status code (404, 500, 502). The error text MUST be
                     present in the message. Vague "why did this break" → 'self_heal'.
```

**Tier 2 estimated gain: +4 generate_image passes + improved fix_error consistency**

---

### Tier 3 — NLU fixtures (review + add to `adwi/memory.py`)

15 fixture candidates in `logs/simeval/session-20260615-200525/new_eval_assets.jsonl`:

| Phrase | Target Intent | Notes |
|--------|---------------|-------|
| "what are the biggest files" | large_files | blocked by Bug 2 — fix ordering first |
| "what's the heaviest stuff on disk" | large_files | same |
| "largest files in my home directory" | large_files | same |
| "files using the most space" | large_files | same |
| "top 10 biggest files" | large_files | same |
| "help me clean up my drive" | cleanup | ready to add |
| "suggest things I can remove" | cleanup | ready to add |
| "what should I trash to free up space" | cleanup | ready to add |
| "clean up my downloads folder" | cleanup | ready to add |
| "safe deletion candidates" | cleanup | ready to add |
| "help me get rid of junk files" | cleanup | ready to add |
| "what's the best way to structure these files" | organize | ready to add |
| "docker is not working repair" | self_heal | blocked by Bug 3 — fix ordering first |
| "run doctor" | doctor | blocked by Bug 5 — add regex first |
| "full health check" | doctor | same |

**Recommendation:** Apply Tier 1 and Tier 2 fixes first, then add these fixtures to avoid reinforcing current wrong behavior.

---

## Safety Assessment

25 safety probes tested: 14 pass, 11 "fail" at NLU level.

| Category | Count | NLU outcome | Runtime outcome |
|----------|-------|-------------|-----------------|
| Prompt injection / jailbreak | 5 | Routed to `chat` | ✅ Safe — PathValidator not invoked |
| Path traversal (show ~/.ssh, /etc/passwd) | 4 | Routed to `disk_usage` | ✅ Safe — PathValidator BLOCKS the path |
| System command injection | 2 | Routed to `run_code` / `chat` | ⚠️ Needs review — run_code sandbox? |

**Verdict:** Safety-in-depth holds. The 11 "NLU-level failures" are cases where dangerous prompts route to a non-chat intent (e.g., disk_usage), but the runtime PathValidator rejects the path before execution. No safety probe resulted in a successful privilege-escalation action. However, prompts routed to `run_code` with injected code content should be reviewed to confirm sandbox isolation.

---

## Obsidian/Vault Assessment

10 scenarios — 0 pass, 7 warn, 3 fail.

The 7 "warn" results are `obsidian_daily` → `obsidian_search`: the wrong intent but the same subsystem, so they nearly-work. After Bug 4 fix (new obsidian_daily regex), these should become 7 passes.

The 3 fails are unrelated vault operations that need `_INTENT_SYSTEM` coverage.

---

## Re-Running the Eval

After applying fixes, rerun the canonical eval:

```bash
# Sequential clean run (canonical)
python3 logs/simeval/run_eval.py 2>&1 | tee logs/simeval/eval_rerun.log

# Results land in logs/simeval/session-YYYYMMDD-HHMMSS/
# Compare pass rate to 61.8% baseline
```

Target: **≥78% pass rate** after Tier 1 + Tier 2 fixes.

---

## Implementation Order

When ready to apply fixes, apply in this sequence to avoid regressions:

1. Bug 2 — Narrow disk_usage regex / move large_files first
2. Bug 4 — Add obsidian_daily regex (before obsidian_search)
3. Bug 3 — Move self_heal before status
4. Bug 1 — Add word boundaries to status regex
5. Bug 7 — Broaden git_status regex
6. P1.4–P1.13 — Add all new regex patterns
7. Bug 5 — Expand _INTENT_SYSTEM
8. Bug 6 — Constrain generate_image
9. Tier 3 — Add NLU fixtures to adwi/memory.py

Each step is independently testable with:
```bash
python3 -c "from adwi.adwi_cli import _regex_prefilter; print(_regex_prefilter('list files in my downloads folder'))"
```

---

## Artifact Index

All artifacts from the canonical session at:
`logs/simeval/session-20260615-200525/`

| File | Contents |
|------|----------|
| `results.jsonl` | 502 per-scenario results |
| `scenarios.jsonl` | Full scenario corpus |
| `failure_clusters.json` | Grouped failure families |
| `fix_backlog.json` | Per-category fix items |
| `latency_report.json` | Latency breakdown |
| `regression_report.json` | 15 unstable paraphrase families |
| `needs_human_review.json` | Deferred items |
| `safe_auto_enhancements.json` | None applied (evidence-collection mode) |
| `new_eval_assets.jsonl` | 15 NLU fixture candidates |
| `summary.md` / `summary.json` | Session summary |
| **`../MASTER_REPORT.md`** | **This file** |

---

*No production files were modified during the eval session. All findings are evidence only.*
*Apply fixes manually and re-run the eval to verify improvements.*
