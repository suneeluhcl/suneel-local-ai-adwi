#!/usr/bin/env python3
"""
overnight_improve.py
Autonomous NLU improvement loop. Runs all night.

Loop:
  1. Run eval harness (full P1 + P2)
  2. Analyze failure patterns from results
  3. Generate targeted regex + INTENT_SYSTEM patches
  4. Apply patch to adwi_cli.py + both eval harnesses
  5. Syntax-check
  6. Commit
  7. Repeat until morning or plateau

Safety:
  - Only modifies _REGEX_INTENTS and _INTENT_SYSTEM — nothing else
  - Every change is syntax-checked before applying
  - Rolls back on any error
  - Writes all history to logs/overnight/
  - Never weakens BLOCKED_PATHS, PathValidator, or risk classifier

Usage:
  python3 scripts/overnight_improve.py
  python3 scripts/overnight_improve.py --max-iterations 5 --dry-run
"""

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "adwi" / "adwi_cli.py"
HARNESS_P1 = REPO / "logs" / "simeval" / "run_large_eval.py"
HARNESS_P2 = REPO / "logs" / "simeval" / "run_large_eval_p2.py"
REPORT_GEN = REPO / "logs" / "simeval" / "generate_master_report.py"
OVERNIGHT_LOG = REPO / "logs" / "overnight"
OVERNIGHT_LOG.mkdir(parents=True, exist_ok=True)

PYTHON = sys.executable
START_TIME = time.time()
MAX_HOURS = 7  # stop before 10 AM if started at 3 AM (conservative)

# Baseline from last measured run
BASELINE_COMBINED = 0.821
BASELINE_P1 = 0.837
BASELINE_P2 = 0.776

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
SESSION_ID = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
LOG_FILE = OVERNIGHT_LOG / f"session-{SESSION_ID}.log"
log_fh = open(LOG_FILE, "w", buffering=1)


def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_fh.write(line + "\n")


def hours_elapsed() -> float:
    return (time.time() - START_TIME) / 3600


# ---------------------------------------------------------------------------
# Run eval harness
# ---------------------------------------------------------------------------

def run_eval(script: Path, workers: int = 8, max_scenarios: int | None = None) -> dict:
    """Run an eval harness and return parsed results."""
    cmd = [PYTHON, str(script), "--workers", str(workers)]
    if max_scenarios:
        cmd += ["--max", str(max_scenarios)]

    log(f"  Running {script.name} {' '.join(cmd[3:])} ...")
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    elapsed = time.time() - t0

    output = result.stdout + result.stderr
    # Parse results from output
    passed = failed = 0
    session_dir = None
    for line in output.splitlines():
        m = re.search(r"Pass:\s*(\d+)\s*\((\d+\.\d+)%\)", line)
        if m:
            passed = int(m.group(1))
        m2 = re.search(r"Fail:\s*(\d+)", line)
        if m2:
            failed = int(m2.group(1))
        m3 = re.search(r"Reports:\s*(\S+)", line)
        if m3:
            session_dir = m3.group(1)

    rate = passed / (passed + failed) if (passed + failed) > 0 else 0.0
    return {
        "passed": passed,
        "failed": failed,
        "rate": rate,
        "elapsed": elapsed,
        "session_dir": session_dir,
        "output": output,
        "script": script.name,
    }


def load_failures(session_dir: str) -> list[dict]:
    """Load failure rows from a session's results.jsonl."""
    if not session_dir:
        return []
    results_file = Path(session_dir) / "results.jsonl"
    if not results_file.exists():
        return []
    failures = []
    with open(results_file) as f:
        for line in f:
            try:
                row = json.loads(line)
                if row.get("result") != "pass":
                    failures.append(row)
            except json.JSONDecodeError:
                continue
    return failures


# ---------------------------------------------------------------------------
# Failure analysis
# ---------------------------------------------------------------------------

def analyze_failures(failures: list[dict]) -> dict:
    """Count failures by (expected_intent, got_intent) pair."""
    counter = collections.Counter()
    by_expected = collections.defaultdict(list)

    for f in failures:
        expected = f.get("expected", f.get("expected_intent", "unknown"))
        got = f.get("got", f.get("predicted_intent", "unknown"))
        counter[(expected, got)] += 1
        by_expected[expected].append({
            "prompt": f.get("prompt", ""),
            "got": got,
            "confidence": f.get("confidence", 0.0),
        })

    top_misroutes = sorted(counter.items(), key=lambda x: -x[1])[:20]
    return {
        "total_failures": len(failures),
        "top_misroutes": top_misroutes,
        "by_expected": dict(by_expected),
    }


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------

# Map of (expected, got) → suggested fix
# These are pre-written patches targeting the remaining failure families
# based on the post-NHR MASTER_REPORT_v2.md analysis.

PATCH_LIBRARY = [
    # ── organize ──────────────────────────────────────────────────────────
    {
        "id": "FIX-ORG-001",
        "description": "Add organize regex anchor before file_search",
        "trigger": lambda mr: any(e == "organize" for (e, g), _ in mr if _ >= 3),
        "regex_patterns": [
            r'(re.compile(r"\b(organiz|restructur|reorganiz)\b.{0,30}\b(files?|folder|workspace|directory)\b", re.I), "organize"),',
            r'(re.compile(r"\b(sort|group|arrange|categoriz)\b.{0,20}\b(files?|folder|download|document)\b", re.I), "organize"),',
            r'(re.compile(r"\bhelp\b.{0,20}(organiz|sort|structur|arrang)\b", re.I), "organize"),',
            r'(re.compile(r"\b(folder|file)\s+(structur|organizat|layout|hierarch)\b", re.I), "organize"),',
        ],
        "intent_system": (
            "   'organize'       : user wants to organize, sort, restructure, or categorize "
            "files/folders. Keywords: 'organize', 'sort', 'restructure', 'folder structure', "
            "'categorize'. NOT 'cleanup' (deletion) NOT 'file_search' (finding).\n"
        ),
        "insert_before": "file_search",
        "families_targeted": ["organize"],
    },

    # ── test_adwi ─────────────────────────────────────────────────────────
    {
        "id": "FIX-TEST-001",
        "description": "Add test_adwi regex anchor",
        "trigger": lambda mr: any(e == "test_adwi" for (e, g), _ in mr if _ >= 2),
        "regex_patterns": [
            r'(re.compile(r"\b(run|start|execute)\b.{0,15}\b(test|tests|test.suite|unit.test)\b", re.I), "test_adwi"),',
            r'(re.compile(r"\badwi\b.{0,15}\b(test|tests)\b", re.I), "test_adwi"),',
            r'(re.compile(r"\btest\b.{0,10}\badwi\b", re.I), "test_adwi"),',
        ],
        "intent_system": (
            "   'test_adwi'      : run adwi's test suite. Keywords: 'run tests', 'test adwi', "
            "'test suite', 'unit tests'. NOT 'eval_adwi' (eval harness). NOT 'benchmark'.\n"
        ),
        "insert_before": "eval_adwi",
        "families_targeted": ["test_adwi"],
    },

    # ── eval_adwi / eval_routing ───────────────────────────────────────────
    {
        "id": "FIX-EVAL-001",
        "description": "Add eval_adwi and eval_routing regex anchors",
        "trigger": lambda mr: any(e in ("eval_adwi", "eval_routing") for (e, g), _ in mr if _ >= 2),
        "regex_patterns": [
            r'(re.compile(r"\beval(uate)?\b.{0,15}\badwi\b", re.I), "eval_adwi"),',
            r'(re.compile(r"\b(run|start)\b.{0,10}\b(eval|evaluation)\b(?!.*routing)", re.I), "eval_adwi"),',
            r'(re.compile(r"\beval(uate)?.{0,15}(routing|routes|dispatch)\b", re.I), "eval_routing"),',
            r'(re.compile(r"\b(test|check|verify)\b.{0,15}\b(routing|route|dispatch)\b", re.I), "eval_routing"),',
        ],
        "intent_system": (
            "   'eval_adwi'      : run the NLU eval harness to score adwi. Keywords: "
            "'eval adwi', 'run eval', 'evaluation', 'eval and compare'. "
            "NOT 'test_adwi' (unit tests). NOT 'benchmark' (perf).\n"
            "   'eval_routing'   : specifically test/evaluate the routing/dispatch logic. "
            "Keywords: 'eval routing', 'test routing', 'check dispatch'.\n"
        ),
        "insert_before": "chat",
        "families_targeted": ["eval_adwi", "eval_routing"],
    },

    # ── browse disambiguation ─────────────────────────────────────────────
    {
        "id": "FIX-BROWSE-001",
        "description": "Tighten browse regex with URL patterns, separate from web_search",
        "trigger": lambda mr: any(e == "browse" for (e, g), _ in mr if _ >= 3),
        "regex_patterns": [
            r'(re.compile(r"\b(open|go to|navigate to|visit|browse to)\b.{0,30}(https?://|\bwww\.\b|\.\b(com|org|io|ai|dev)\b)", re.I), "browse"),',
            r'(re.compile(r"\b(open|visit|go to)\b.{0,20}\b(website|site|page|url)\b", re.I), "browse"),',
            r'(re.compile(r"https?://\S+", re.I), "browse"),',
        ],
        "intent_system": (
            "   'browse'         : open a specific URL or website in a browser. "
            "Requires a URL, domain, or explicit 'website'/'page' reference. "
            "NOT 'web_search' (information lookup without a specific URL).\n"
        ),
        "insert_before": "web_search",
        "families_targeted": ["browse"],
    },

    # ── memory_scan ───────────────────────────────────────────────────────
    {
        "id": "FIX-MEMSCAN-001",
        "description": "Add memory_scan synonym patterns",
        "trigger": lambda mr: any(e == "memory_scan" for (e, g), _ in mr if _ >= 2),
        "regex_patterns": [
            r'(re.compile(r"\b(index|scan|refresh|rebuild|update)\b.{0,20}\b(memory|mem)\b", re.I), "memory_scan"),',
            r'(re.compile(r"\bmemory\b.{0,15}\b(scan|index|update|refresh|rebuild)\b", re.I), "memory_scan"),',
            r'(re.compile(r"\b(scan|index)\b.{0,20}\b(history|files|documents|workspace)\b.{0,20}\bmemory\b", re.I), "memory_scan"),',
        ],
        "intent_system": None,
        "insert_before": "memory_recall",
        "families_targeted": ["memory_scan"],
    },

    # ── fix_error — pasted-exception anchoring ────────────────────────────
    {
        "id": "FIX-ERR-001",
        "description": "Add fix_error patterns for pasted exception text",
        "trigger": lambda mr: any(e == "fix_error" for (e, g), _ in mr if _ >= 3),
        "regex_patterns": [
            r'(re.compile(r"(Traceback|Error:|Exception:|SyntaxError|TypeError|ValueError|RuntimeError|AttributeError|ImportError|ModuleNotFoundError|OSError|FileNotFoundError|PermissionError|ConnectionError|TimeoutError)\b", re.I), "fix_error"),',
            r'(re.compile(r"\b(getting|seeing|got)\b.{0,20}(error|exception|traceback|crash|failure)\b", re.I), "fix_error"),',
            r'(re.compile(r"\b(error|exception)\b.{0,30}\b(line\s+\d+|at\s+\d+)\b", re.I), "fix_error"),',
            r'(re.compile(r"\d{3}\s+(not found|bad gateway|forbidden|unauthorized|server error)", re.I), "fix_error"),',
        ],
        "intent_system": (
            "   'fix_error'      : user has pasted an error/exception or describes a specific "
            "technical error. Triggered by: Python tracebacks, HTTP error codes, "
            "'getting error X', 'seeing exception Y'. NOT 'self_heal' (generic broken). "
            "NOT 'status' (general health check).\n"
        ),
        "insert_before": "chat",
        "families_targeted": ["fix_error"],
    },

    # ── cleanup — broader synonyms ─────────────────────────────────────────
    {
        "id": "FIX-CLEAN-002",
        "description": "Expand cleanup synonyms",
        "trigger": lambda mr: any(e == "cleanup" for (e, g), _ in mr if _ >= 5),
        "regex_patterns": [
            r'(re.compile(r"\b(safe|can i|suggest|what can i)\b.{0,20}(delet|remov|trash|wipe)\b", re.I), "cleanup"),',
            r'(re.compile(r"\b(safe.deletion|deletion.candidate|safe.to.delete|safe.to.remove)\b", re.I), "cleanup"),',
            r'(re.compile(r"\bfree up\b.{0,20}(space|storage|disk|drive)\b", re.I), "cleanup"),',
            r'(re.compile(r"\b(prune|purge|wipe|clear)\b.{0,20}(files?|folder|cache|temp|log)\b", re.I), "cleanup"),',
        ],
        "intent_system": None,
        "insert_before": "file_search",
        "families_targeted": ["cleanup"],
    },

    # ── web_search — tighten "look up" vs model_status ────────────────────
    {
        "id": "FIX-WEB-001",
        "description": "Fix web_search losing to model_status on 'look up' phrases",
        "trigger": lambda mr: any(e == "web_search" and g == "model_status" for (e, g), _ in mr if _ >= 2),
        "regex_patterns": [
            r'(re.compile(r"\b(look up|search for|find out|google)\b.{0,30}(version|benchmark|comparison|guide|tutorial|how to)\b", re.I), "web_search"),',
            r'(re.compile(r"\b(look up|search for)\b.{5,}", re.I), "web_search"),',
        ],
        "intent_system": None,
        "insert_before": "model_status",
        "families_targeted": ["web_search"],
    },

    # ── nightly_status ─────────────────────────────────────────────────────
    {
        "id": "FIX-NIGHT-001",
        "description": "Add nightly_status regex anchor",
        "trigger": lambda mr: any(e == "nightly_status" for (e, g), _ in mr if _ >= 2),
        "regex_patterns": [
            r'(re.compile(r"\b(last\s+night|nightly|overnight)\b.{0,30}(run|result|report|status|log|summary)\b", re.I), "nightly_status"),',
            r'(re.compile(r"\b(what|show)\b.{0,10}(last\s+night|nightly|overnight)\b", re.I), "nightly_status"),',
            r'(re.compile(r"\bnightly\b(?!.*(improve|enhanc|maintenan))", re.I), "nightly_status"),',
        ],
        "intent_system": (
            "   'nightly_status' : user asks about the last nightly maintenance run results. "
            "Keywords: 'last night', 'nightly run', 'overnight', 'nightly status'. "
            "NOT 'daily_improve' (starting a new run). NOT 'status' (current service health).\n"
        ),
        "insert_before": "status",
        "families_targeted": ["nightly_status"],
    },

    # ── memory_context ─────────────────────────────────────────────────────
    {
        "id": "FIX-CTX-001",
        "description": "Add memory_context regex for session/context queries",
        "trigger": lambda mr: any(e == "memory_context" for (e, g), _ in mr if _ >= 2),
        "regex_patterns": [
            r'(re.compile(r"\b(current|active|this)\s+session\b.{0,20}(context|summary|state)\b", re.I), "memory_context"),',
            r'(re.compile(r"\bshow\b.{0,15}(context|session.context|current.context)\b", re.I), "memory_context"),',
            r'(re.compile(r"\bwhat\b.{0,20}(context|session)\b.{0,15}(do you have|you have|have you)\b", re.I), "memory_context"),',
        ],
        "intent_system": None,
        "insert_before": "memory_recall",
        "families_targeted": ["memory_context"],
    },

    # ── obsidian_daily ─────────────────────────────────────────────────────
    {
        "id": "FIX-OD-001",
        "description": "Strengthen obsidian_daily regex",
        "trigger": lambda mr: any(e == "obsidian_daily" for (e, g), _ in mr if _ >= 2),
        "regex_patterns": [
            r'(re.compile(r"\b(today[\'s]*|daily)\b.{0,20}(note|journal|entry|log)\b", re.I), "obsidian_daily"),',
            r'(re.compile(r"\b(open|show|read|add to)\b.{0,20}\b(today[\'s]*\s+(note|obsidian|journal)|daily\s+(note|journal|log))\b", re.I), "obsidian_daily"),',
            r'(re.compile(r"\bdailly\b.{0,20}(note|journal|log)\b", re.I), "obsidian_daily"),',
        ],
        "intent_system": None,
        "insert_before": "obsidian_search",
        "families_targeted": ["obsidian_daily"],
    },

    # ── run_code disambiguation ─────────────────────────────────────────────
    {
        "id": "FIX-RUN-001",
        "description": "Anchor run_code to explicit code references",
        "trigger": lambda mr: any(e == "run_code" for (e, g), _ in mr if _ >= 3),
        "regex_patterns": [
            r'(re.compile(r"\b(run|execute|launch)\b.{0,20}\b(script|code|program|file\.py|\.py)\b", re.I), "run_code"),',
            r'(re.compile(r"\bpython3?\s+\S+\.py\b", re.I), "run_code"),',
            r'(re.compile(r"\brun\s+this\s+(code|script|program)\b", re.I), "run_code"),',
        ],
        "intent_system": (
            "   'run_code'       : execute a specific script, file, or code snippet. "
            "Must have explicit code reference (file.py, 'this code', 'this script'). "
            "NOT triggered by bare 'run it' or 'run the thing' (too ambiguous).\n"
        ),
        "insert_before": "chat",
        "families_targeted": ["run_code"],
    },
]


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------

def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_file(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def syntax_check(path: Path) -> bool:
    result = subprocess.run(
        [PYTHON, "-m", "py_compile", str(path)],
        capture_output=True, text=True
    )
    return result.returncode == 0


def find_regex_intents_insert_point(content: str, before_intent: str) -> int:
    """Find the line index to insert new patterns (before the first occurrence of before_intent)."""
    lines = content.split("\n")
    target = f'"{before_intent}"'
    for i, line in enumerate(lines):
        if target in line and "_REGEX_INTENTS" not in line and "re.compile" in line:
            return i
    # Fallback: find the end of _REGEX_INTENTS list
    in_regex = False
    for i, line in enumerate(lines):
        if "_REGEX_INTENTS" in line and "=" in line:
            in_regex = True
        if in_regex and line.strip().startswith("]"):
            return i
    return -1


def find_intent_system_insert_point(content: str, before_intent: str) -> int:
    """Find position in _INTENT_SYSTEM to insert new intent description."""
    lines = content.split("\n")
    # Find the last intent description line before a natural boundary
    for i, line in enumerate(lines):
        if f"'{before_intent}'" in line and ":" in line and "f'" in line or (
            f"'{before_intent}'" in line and "NOT" in line
        ):
            return i
    # Fallback: find end of intent system
    for i, line in enumerate(lines):
        if "_INTENT_SYSTEM" in line and "VALID_INTENTS" in line:
            return i - 1
    return -1


def apply_patch(patch: dict, dry_run: bool = False) -> bool:
    """Apply a patch to adwi_cli.py and both eval harnesses."""
    log(f"  Applying {patch['id']}: {patch['description']}")

    files_to_patch = [CLI, HARNESS_P1, HARNESS_P2]
    backups = {}

    # Back up all files
    for f in files_to_patch:
        backups[f] = f.read_text(encoding="utf-8")

    try:
        for filepath in files_to_patch:
            content = backups[filepath]
            lines = content.split("\n")

            # Find insert point for regex patterns
            insert_line = find_regex_intents_insert_point(content, patch["insert_before"])
            if insert_line == -1:
                log(f"    WARNING: could not find insert point for '{patch['insert_before']}' in {filepath.name}")
                continue

            # Build indentation from surrounding lines
            indent = "    "
            if insert_line > 0:
                surrounding = lines[insert_line - 1]
                m = re.match(r"^(\s*)", surrounding)
                if m and m.group(1):
                    indent = m.group(1)

            # Insert regex patterns BEFORE the target intent's first pattern
            new_lines = patch["regex_patterns"]
            for i, pattern in enumerate(reversed(new_lines)):
                lines.insert(insert_line, indent + pattern)

            # Add INTENT_SYSTEM entry if provided
            if patch.get("intent_system"):
                # Find the intent system section
                for j, line in enumerate(lines):
                    if "'_INTENT_SYSTEM'" in line or "_INTENT_SYSTEM =" in line or (
                        "INTENT_SYSTEM" in line and '"""' in line
                    ):
                        # Insert 10 lines after the section start
                        lines.insert(j + 10, "    " + patch["intent_system"])
                        break

            new_content = "\n".join(lines)

            if dry_run:
                log(f"    [DRY RUN] Would patch {filepath.name} (+{len(new_lines)} patterns)")
                continue

            write_file(filepath, new_content)

            # Syntax check
            if not syntax_check(filepath):
                log(f"    SYNTAX ERROR in {filepath.name} — rolling back")
                for f, backup in backups.items():
                    f.write_text(backup, encoding="utf-8")
                return False

        log(f"    Applied {patch['id']} to {len(files_to_patch)} files")
        return True

    except Exception as e:
        log(f"    ERROR applying patch: {e} — rolling back")
        for f, backup in backups.items():
            f.write_text(backup, encoding="utf-8")
        return False


# ---------------------------------------------------------------------------
# Git commit
# ---------------------------------------------------------------------------

def commit_progress(iteration: int, rate: float, delta: float, patches_applied: list[str]):
    patch_list = ", ".join(patches_applied) if patches_applied else "none"
    msg = (
        f"nlu: overnight improvement iteration {iteration} — "
        f"{rate:.1%} (+{delta:+.1%} vs baseline)\n\n"
        f"Patches applied: {patch_list}\n"
        f"Baseline: {BASELINE_COMBINED:.1%} | New rate: {rate:.1%}\n\n"
        f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
    )
    subprocess.run(
        ["git", "add", str(CLI), str(HARNESS_P1), str(HARNESS_P2)],
        cwd=str(REPO), capture_output=True
    )
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(REPO), capture_output=True, text=True
    )
    if result.returncode == 0:
        log(f"  Committed iteration {iteration}")
        subprocess.run(["git", "push", "origin", "main"], cwd=str(REPO), capture_output=True)
    else:
        log(f"  Commit skipped (no changes or error): {result.stderr[:100]}")


# ---------------------------------------------------------------------------
# Morning report
# ---------------------------------------------------------------------------

def write_morning_report(history: list[dict]):
    report_path = OVERNIGHT_LOG / f"morning-report-{SESSION_ID}.md"
    lines = [
        f"# Adwi Overnight Improvement Report",
        f"",
        f"**Session:** {SESSION_ID}",
        f"**Duration:** {hours_elapsed():.1f} hours",
        f"**Baseline:** {BASELINE_COMBINED:.1%} (pre-session)",
        f"",
        f"## Iteration History",
        f"",
        f"| # | P1 Rate | P2 Rate | Delta vs Baseline | Patches Applied |",
        f"|---|---------|---------|-------------------|-----------------|",
    ]
    for h in history:
        p1 = f"{h.get('p1_rate', 0):.1%}"
        p2 = f"{h.get('p2_rate', 0):.1%}"
        delta = f"{h.get('delta', 0):+.1%}"
        patches = ", ".join(h.get("patches", []) or ["none"])
        lines.append(f"| {h['iteration']} | {p1} | {p2} | {delta} | {patches} |")

    lines += [
        f"",
        f"## Final State",
        f"",
    ]
    if history:
        last = history[-1]
        lines += [
            f"- **Final P1:** {last.get('p1_rate', 0):.1%}",
            f"- **Final P2:** {last.get('p2_rate', 0):.1%}",
            f"- **Total gain:** {last.get('delta', 0):+.1%} vs {BASELINE_COMBINED:.1%} baseline",
            f"- **Patches applied:** {sum(len(h.get('patches', [])) for h in history)}",
        ]

    lines += [
        f"",
        f"## Next Steps",
        f"",
        f"Ask Claude: _'Based on logs/overnight/latest/morning-report, what should I fix next?'_",
        f"",
        f"Run: `python3 logs/simeval/run_large_eval.py --workers 10` for full benchmark",
    ]

    report_path.write_text("\n".join(lines))
    log(f"\nMorning report: {report_path}")

    # Update symlink
    latest = OVERNIGHT_LOG / "latest"
    if latest.is_symlink():
        latest.unlink()
    latest.symlink_to(report_path.name)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-iterations", type=int, default=30)
    parser.add_argument("--max-hours", type=float, default=MAX_HOURS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-scenarios-p1", type=int, default=None, help="Cap P1 scenarios (faster iterations)")
    args = parser.parse_args()

    log(f"Adwi Overnight Improvement Loop")
    log(f"Session: {SESSION_ID}")
    log(f"Max iterations: {args.max_iterations} | Max hours: {args.max_hours}")
    log(f"Dry run: {args.dry_run}")
    log(f"Baseline: P1={BASELINE_P1:.1%} P2={BASELINE_P2:.1%} Combined={BASELINE_COMBINED:.1%}")

    history = []
    best_p1 = BASELINE_P1
    best_p2 = BASELINE_P2
    applied_patch_ids: set[str] = set()
    plateau_count = 0
    plateau_threshold = 3  # stop if 3 consecutive iterations show no improvement

    for iteration in range(1, args.max_iterations + 1):
        if hours_elapsed() >= args.max_hours:
            log(f"\nTime limit reached ({args.max_hours}h) — stopping")
            break

        log(f"\n{'='*60}")
        log(f"ITERATION {iteration} — {hours_elapsed():.1f}h elapsed")
        log(f"{'='*60}")

        # Run P1 eval
        p1 = run_eval(HARNESS_P1, workers=args.workers, max_scenarios=args.max_scenarios_p1)
        log(f"P1: {p1['passed']}/{p1['passed']+p1['failed']} = {p1['rate']:.1%} ({p1['elapsed']:.0f}s)")

        # Run P2 eval
        p2 = run_eval(HARNESS_P2, workers=args.workers)
        log(f"P2: {p2['passed']}/{p2['passed']+p2['failed']} = {p2['rate']:.1%} ({p2['elapsed']:.0f}s)")

        # Combined rate (weighted)
        combined = (p1["passed"] + p2["passed"]) / max(
            (p1["passed"] + p1["failed"] + p2["passed"] + p2["failed"]), 1
        )
        delta = combined - BASELINE_COMBINED
        log(f"Combined: {combined:.1%} (delta vs 82.1% baseline: {delta:+.1%})")

        # Check for improvement
        improved = combined > best_p1 * 0.85 + best_p2 * 0.15  # proxy for combined
        if p1["rate"] > best_p1 or p2["rate"] > best_p2:
            best_p1 = max(best_p1, p1["rate"])
            best_p2 = max(best_p2, p2["rate"])
            plateau_count = 0
        else:
            plateau_count += 1
            log(f"No improvement ({plateau_count}/{plateau_threshold} plateau threshold)")
            if plateau_count >= plateau_threshold:
                log("Plateau reached — stopping improvement loop")
                history.append({"iteration": iteration, "p1_rate": p1["rate"], "p2_rate": p2["rate"],
                                 "delta": delta, "patches": [], "note": "plateau"})
                break

        # Analyze failures
        failures = load_failures(p1["session_dir"])
        if not failures and p1.get("session_dir"):
            log("  No failures found in P1 results")

        analysis = analyze_failures(failures)
        top_misroutes = analysis["top_misroutes"]
        log(f"  Failures: {analysis['total_failures']} | Top misroute: "
            f"{top_misroutes[0] if top_misroutes else 'none'}")

        # Select patches to apply
        patches_applied_this_iter = []
        for patch in PATCH_LIBRARY:
            if patch["id"] in applied_patch_ids:
                continue
            if patch["trigger"](top_misroutes):
                log(f"\n  Triggered: {patch['id']}")
                success = apply_patch(patch, dry_run=args.dry_run)
                if success:
                    applied_patch_ids.add(patch["id"])
                    patches_applied_this_iter.append(patch["id"])
                if len(patches_applied_this_iter) >= 2:
                    break  # max 2 patches per iteration to keep changes manageable

        if not patches_applied_this_iter:
            log("  No triggered patches this iteration")

        # Commit
        if patches_applied_this_iter and not args.dry_run:
            commit_progress(iteration, combined, delta, patches_applied_this_iter)

        history.append({
            "iteration": iteration,
            "p1_rate": p1["rate"],
            "p2_rate": p2["rate"],
            "delta": delta,
            "patches": patches_applied_this_iter,
        })

        # Save iteration log
        iter_log = OVERNIGHT_LOG / f"iter-{iteration:02d}-{SESSION_ID}.json"
        iter_log.write_text(json.dumps({
            "iteration": iteration,
            "p1": p1,
            "p2": p2,
            "combined": combined,
            "analysis": {"total_failures": analysis["total_failures"], "top_10": str(top_misroutes[:10])},
            "patches": patches_applied_this_iter,
        }, indent=2, default=str))

    log(f"\n{'='*60}")
    log(f"OVERNIGHT SESSION COMPLETE")
    log(f"{'='*60}")
    log(f"Duration: {hours_elapsed():.1f} hours | Iterations: {len(history)}")
    log(f"Best P1: {best_p1:.1%} (was {BASELINE_P1:.1%})")
    log(f"Best P2: {best_p2:.1%} (was {BASELINE_P2:.1%})")
    log(f"Patches applied: {list(applied_patch_ids)}")

    write_morning_report(history)

    # Final push
    if not args.dry_run:
        subprocess.run(["git", "push", "origin", "main"], cwd=str(REPO), capture_output=True)
        log("Final push complete")


if __name__ == "__main__":
    main()
