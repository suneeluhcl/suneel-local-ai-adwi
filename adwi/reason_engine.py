"""
reason_engine.py — Stateful multi-agent reasoning graph for /reason <task>.

Graph flow:
  PlannerAgent → ExecutorAgent (with Phase 2 permission gate + Phase 4 live heal)
               → CriticAgent  → retry / pass / fail
  On completion → Achievement Summary

Phase 2: Every REVIEW-REQUIRED step shows the exact command/patch + WHY before asking.
Phase 4: Runtime errors from approved steps are caught, healed by aider in real-time,
         verified by tests, and reported in the achievement summary.
Phase 3: classify_risk() gate is the single decision point for SAFE / REVIEW / BLOCKED.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from adwi.search_orchestrator import SearchOptions, SearchOrchestrator, metrics_summary
except ModuleNotFoundError:
    from search_orchestrator import SearchOptions, SearchOrchestrator, metrics_summary  # type: ignore

try:
    from adwi.path_validator import PathValidator
except ModuleNotFoundError:
    from path_validator import PathValidator  # type: ignore

# ── Constants ─────────────────────────────────────────────────────────────────
OLLAMA_URL  = "http://127.0.0.1:11434"
MODEL_MAIN  = "adwi:latest"
MODEL_FAST  = "llama3.1:8b"
WORKSPACE   = Path.home() / "SuneelWorkSpace"
ADWI_DIR    = WORKSPACE / "adwi"
AIDER_BIN   = Path.home() / ".local" / "bin" / "aider"
MAX_RETRIES = 3

# Explicit allowlist for autonomous aider live-heal patching.
# Security-boundary files (path_validator, backup, local-command-api,
# obsidian-bridge, simlab, reason_engine itself) are intentionally excluded.
_AIDER_PATCHABLE = frozenset({
    str((ADWI_DIR / "adwi_cli.py").resolve()),
    str((ADWI_DIR / "memory.py").resolve()),
    str((ADWI_DIR / "nlu_fast_path.py").resolve()),
})

# ANSI
_R = "\033[0m"; _B = "\033[1m"; _DIM = "\033[2m"
_CY = "\033[36m"; _GR = "\033[32m"; _YL = "\033[33m"
_RD = "\033[31m"; _PU = "\033[35m"; _GY = "\033[90m"

# ── File-access gate ──────────────────────────────────────────────────────────
# Single PathValidator shared by _exec_file_read and _exec_file_write.
# allowed_roots=[] = deny-blocked, allow everything else (matches prior behaviour).
# adwi/config/.env is an extra block specific to this module — it sits inside the
# workspace so make_workspace_validator() alone would not block it.

def _make_file_gate() -> PathValidator:
    _h = Path.home()
    return PathValidator(
        allowed_roots=[],
        blocked_roots=[
            WORKSPACE / "secrets",
            _h / ".ssh",
            _h / ".gnupg",
            _h / ".aws",
            _h / ".kube",
            _h / ".config" / "gcloud",
            _h / ".npmrc",
            _h / ".netrc",
            _h / "Library" / "Keychains",
            _h / "Library" / "Passwords",
            Path("/etc"),
            Path("/private"),
            Path("/System"),
            Path("/usr/lib"),
            ADWI_DIR / "config" / ".env",
        ],
    )

_FILE_GATE = _make_file_gate()

# ── Phase 3: Safety classification ───────────────────────────────────────────

_BLOCKED = re.compile(
    r"(rm\s+-rf|git\s+push\s+--force|DROP\s+TABLE|truncate\s+table"
    r"|shutdown|reboot|format\s+disk|diskutil\s+erase"
    r"|/etc/|/private/|/System/|~/.ssh|~/.aws|secrets/)",
    re.I,
)
_REVIEW = re.compile(
    r"(git\s+commit|git\s+push\b|docker\s+compose\s+down|brew\s+uninstall"
    r"|pip\s+uninstall|rm\s+-r(?!f)|mv\s+\S+\s+/|launchctl\s+(un)?load"
    r"|chmod|chown|pkill|killall|file_write|obsidian_write)",
    re.I,
)


def classify_risk(action: str, action_type: str = "") -> str:
    """Return BLOCKED | REVIEW-REQUIRED | SAFE."""
    combined = f"{action_type} {action}"
    if _BLOCKED.search(combined):
        return "BLOCKED"
    if _REVIEW.search(combined):
        return "REVIEW-REQUIRED"
    # All file writes and obsidian writes always need review
    if action_type in ("file_write", "obsidian_write"):
        return "REVIEW-REQUIRED"
    return "SAFE"


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _ollama(
    prompt: str,
    system: Optional[str] = None,
    model: str = MODEL_MAIN,
    timeout: int = 180,
) -> str:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": "/no_think\n" + prompt})
    payload = json.dumps(
        {"model": model, "messages": msgs, "stream": False,
         "options": {"temperature": 0.2, "num_predict": 2048}}
    ).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["message"]["content"].strip()
    except Exception as e:
        return f"[LLM error: {e}]"


# ── Achievement Ledger (Phase 2 + 4) ─────────────────────────────────────────

class AchievementLedger:
    """Tracks everything that happens during a graph run for the final summary."""

    def __init__(self, task: str):
        self.task          = task
        self.commands_run:   list[dict] = []   # {cmd, exit_ok, output_snippet}
        self.files_written:  list[dict] = []   # {path, chars}
        self.files_read:     list[str]  = []
        self.searches:       list[str]  = []
        self.errors_healed:  list[dict] = []   # {error, aider_patched, tests_passed}
        self.errors_failed:  list[str]  = []
        self.steps_blocked:  list[str]  = []
        self.steps_declined: list[str]  = []

    def add_command(self, cmd: str, ok: bool, output: str) -> None:
        self.commands_run.append({
            "cmd": cmd[:120], "exit_ok": ok,
            "output_snippet": output[:120].replace("\n", " "),
        })

    def add_file_written(self, path: str, chars: int) -> None:
        self.files_written.append({"path": path, "chars": chars})

    def add_file_read(self, path: str) -> None:
        self.files_read.append(path)

    def add_search(self, query: str) -> None:
        self.searches.append(query[:80])

    def add_heal(self, error: str, patched: bool, tests_passed: Optional[bool]) -> None:
        self.errors_healed.append({
            "error": error[:120], "aider_patched": patched,
            "tests_passed": tests_passed,
        })

    def add_fail(self, msg: str) -> None:
        self.errors_failed.append(msg[:100])

    def add_blocked(self, action: str) -> None:
        self.steps_blocked.append(action[:80])

    def add_declined(self, action: str) -> None:
        self.steps_declined.append(action[:80])

    def render(self) -> str:
        """Render the clean itemized achievement summary."""
        W = 62
        def box_line(text="", fill=False):
            if fill:
                return f"│{'─' * W}│"
            padded = text[:W].ljust(W)
            return f"│  {padded[:-2]}│"  # 2 chars for "│  " prefix leaves W-2 content chars

        lines = [
            f"╭{'─' * W}╮",
            box_line(f"{_B}Achievement Summary{_R}"),
            box_line(f"{_GY}Task: {self.task[:W-8]}{_R}"),
            f"│{'─' * W}│",
        ]

        def section(icon, title, items):
            if not items:
                return
            lines.append(box_line(f"{icon}  {_B}{title}{_R}"))
            for item in items:
                lines.append(box_line(f"   · {item}"))

        # Commands
        if self.commands_run:
            lines.append(box_line(f"{_GR}▶  {_B}Commands executed ({len(self.commands_run)}){_R}"))
            for c in self.commands_run:
                icon = "✓" if c["exit_ok"] else "✗"
                color = _GR if c["exit_ok"] else _YL
                lines.append(box_line(f"   {color}{icon}{_R} {c['cmd']}"))

        # Files written
        if self.files_written:
            lines.append(box_line(f"{_CY}✎  {_B}Files written ({len(self.files_written)}){_R}"))
            for f in self.files_written:
                lines.append(box_line(f"   · {f['path']}  ({f['chars']:,} chars)"))

        # Files read
        if self.files_read:
            lines.append(box_line(f"{_GY}📖  Files read ({len(self.files_read)}){_R}"))
            for p in self.files_read[:5]:
                lines.append(box_line(f"   · {p}"))

        # Searches
        if self.searches:
            lines.append(box_line(f"{_GY}🔍  Web searches ({len(self.searches)}){_R}"))
            for q in self.searches:
                lines.append(box_line(f"   · {q}"))

        # Live heals
        if self.errors_healed:
            lines.append(box_line(f"{_YL}⚕  {_B}Errors caught & healed ({len(self.errors_healed)}){_R}"))
            for h in self.errors_healed:
                patch_tag = f"{_GR}aider ✓{_R}" if h["aider_patched"] else f"{_RD}patch failed{_R}"
                test_tag  = f" · tests {_GR}✓{_R}" if h["tests_passed"] else (f" · tests {_RD}✗{_R}" if h["tests_passed"] is False else "")
                lines.append(box_line(f"   · {h['error'][:50]}"))
                lines.append(box_line(f"     → {patch_tag}{test_tag}"))

        # Declined / blocked
        if self.steps_declined:
            lines.append(box_line(f"{_GY}⊘  Steps declined by user ({len(self.steps_declined)}){_R}"))
            for s in self.steps_declined:
                lines.append(box_line(f"   · {s}"))
        if self.steps_blocked:
            lines.append(box_line(f"{_RD}🛑  Steps hard-blocked ({len(self.steps_blocked)}){_R}"))
            for s in self.steps_blocked:
                lines.append(box_line(f"   · {s}"))

        # Errors that couldn't be fixed
        if self.errors_failed:
            lines.append(box_line(f"{_RD}✗  Unresolved errors ({len(self.errors_failed)}){_R}"))
            for e in self.errors_failed:
                lines.append(box_line(f"   · {e}"))

        lines.append(f"╰{'─' * W}╯")
        return "\n".join(lines)


# ── Phase 2: Permission Gate ──────────────────────────────────────────────────

def _why_explanation(step: dict) -> str:
    """Ask the fast model to explain why this step is needed — one sentence."""
    prompt = (
        f"Task: {step.get('_task','?')}\n"
        f"Step {step.get('id','?')}: {step.get('title','?')}\n"
        f"Action: {step.get('action','?')[:200]}\n\n"
        "In one concise sentence, explain WHY this action is necessary to complete the task."
    )
    raw = _ollama(prompt, model=MODEL_FAST, timeout=20)
    # Strip any LLM preamble
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.lower().startswith(("sure", "of course", "certainly", "this")):
            return line
    return raw.strip()[:200] or "Required to complete the task."


def _format_action_display(action_type: str, action: str) -> str:
    """Format the action for display — show full command or file path."""
    if action_type == "shell":
        return f"  $ {action}"
    elif action_type in ("file_read", "file_write"):
        op = "Write to" if action_type == "file_write" else "Read"
        path = action.split("::")[0] if "::" in action else action
        return f"  {op}: {path}"
    elif action_type == "web_search":
        return f"  Search: \"{action}\""
    elif action_type == "memory_query":
        return f"  Memory query: \"{action}\""
    elif action_type == "obsidian_write":
        return f"  Obsidian write: {action}"
    else:
        return textwrap.fill(action, width=70, initial_indent="  ", subsequent_indent="    ")


def permission_gate(step: dict, ledger: AchievementLedger) -> bool:
    """
    Phase 2 interactive permission surface.
    Displays the full action, the WHY explanation, and asks for explicit approval.
    Returns True if user approves.
    """
    action      = step.get("action", "")
    action_type = step.get("action_type", "llm_reason")
    title       = step.get("title", "?")
    step_id     = step.get("id", "?")

    W = 64
    print(f"\n  ╭{'─' * W}╮")
    print(f"  │  {_B}{_YL}Action Required — Step {step_id}: {title}{_R}{'':<{max(0, W - len(f'Action Required — Step {step_id}: {title}') - 2)}}│")
    print(f"  │{'─' * W}│")

    # WHY section
    why = _why_explanation(step)
    print(f"  │  {_B}Why:{_R}{'':>{W - 6}}│")
    for line in textwrap.wrap(why, width=W - 4):
        print(f"  │  {_GY}{line:<{W-4}}{_R}│")

    print(f"  │{'─' * W}│")

    # ACTION section
    action_label = action_type.upper().replace("_", " ")
    print(f"  │  {_B}Action [{action_label}]:{_R}{'':>{W - len(f'Action [{action_label}]:') - 2}}│")
    action_str = _format_action_display(action_type, action)
    for line in action_str.splitlines():
        print(f"  │  {_CY}{line.rstrip():<{W-4}}{_R}│")

    # Show file content preview for file_write
    if action_type == "file_write" and "::" in action:
        content_preview = action.split("::", 1)[1][:300]
        print(f"  │{'─' * W}│")
        print(f"  │  {_DIM}Content preview (first 300 chars):{_R}{'':>{W - 36}}│")
        for line in content_preview.splitlines()[:8]:
            truncated = line[:W-4]
            print(f"  │  {_GY}{truncated:<{W-4}}{_R}│")

    print(f"  ╰{'─' * W}╯")
    print(f"\n  {_YL}Allow Adwi to execute this action? (y/n):{_R} ", end="", flush=True)

    try:
        ans = input().strip().lower()
        approved = ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        approved = False

    if not approved:
        ledger.add_declined(f"[{action_type}] {action[:60]}")
        print(f"  {_GY}Skipped.{_R}")

    return approved


# ── Phase 4: Live self-healing executor ──────────────────────────────────────

def _extract_error_files(tb_text: str) -> list[Path]:
    """Parse a traceback for source files that belong to this workspace."""
    files = set()
    for m in re.finditer(r'File "([^"]+\.py)"', tb_text):
        p = Path(m.group(1))
        try:
            p.resolve().relative_to(WORKSPACE.resolve())
            if p.exists() and "test_" not in p.name:
                files.add(p)
        except ValueError:
            pass
    return list(files)[:4]


def _looks_like_patchable_error(output: str) -> bool:
    """True if the error is likely code-level and aider could fix it."""
    patchable = (
        "ModuleNotFoundError", "ImportError", "AttributeError",
        "TypeError", "NameError", "SyntaxError", "KeyError",
        "Traceback (most recent call last)",
    )
    return any(p in output for p in patchable)


def _run_tests(timeout: int = 90) -> tuple[bool, str]:
    evals_dir = ADWI_DIR / "evals"
    if evals_dir.exists() and any(evals_dir.glob("test_*.py")):
        cmd = ["python3", "-m", "pytest", str(evals_dir), "-x", "--tb=short", "-q"]
    else:
        cmd = ["python3", "-m", "py_compile", str(ADWI_DIR / "adwi_cli.py")]
    env = {**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(WORKSPACE), env=env,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _invoke_aider_realtime(error_output: str, files: list[Path]) -> tuple[bool, str]:
    """
    Phase 4: invoke aider immediately on the failing file(s).
    Non-interactive, background execution. Returns (ok, log).
    """
    if not AIDER_BIN.exists():
        return False, f"aider not found at {AIDER_BIN}"
    if not files:
        return False, "no patchable files identified in traceback"

    prompt = (
        f"[Adwi live self-heal]\n\n"
        f"A runtime error occurred during an approved action. Error output:\n\n"
        f"```\n{error_output[:2000]}\n```\n\n"
        f"Fix the minimum lines needed to resolve this error. "
        f"Do not add features or change passing behaviour."
    )
    cmd = [
        str(AIDER_BIN),
        "--model", "ollama/adwi:latest",
        "--no-git", "--yes-always", "--no-pretty", "--no-stream",
        "--message", prompt,
    ] + [str(f) for f in files]

    env = {
        **os.environ,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "OLLAMA_API_BASE": "http://127.0.0.1:11434",
    }
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(WORKSPACE), env=env,
        )
        return r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return False, "aider timed out"
    except Exception as e:
        return False, str(e)


def _live_heal(error_output: str, ledger: AchievementLedger) -> bool:
    """
    Phase 4 core: catch a runtime error, try aider, run tests, update ledger.
    Returns True if the error was successfully healed.
    """
    print(f"\n  {_YL}⚕  Live error caught — attempting real-time self-heal …{_R}")

    # Identify files to patch
    files = _extract_error_files(error_output)
    files = [f for f in files if str(f.resolve()) in _AIDER_PATCHABLE]
    if not files:
        print(f"  {_GY}No patchable workspace files in traceback — skipping aider.{_R}")
        ledger.add_heal(error_output[:80], patched=False, tests_passed=None)
        return False

    print(f"  {_GY}Targeting: {', '.join(str(f.name) for f in files)}{_R}")
    print(f"  {_GY}Invoking aider (background) …{_R}")

    aider_ok, aider_log = _invoke_aider_realtime(error_output, files)

    if not aider_ok:
        print(f"  {_YL}Aider pass incomplete: {aider_log[:100]}{_R}")
        ledger.add_heal(error_output[:80], patched=False, tests_passed=None)
        return False

    print(f"  {_GR}Aider patch applied — running verification tests …{_R}")
    tests_ok, test_output = _run_tests()

    if tests_ok:
        print(f"  {_GR}✓ Tests pass — heal confirmed.{_R}")
    else:
        print(f"  {_YL}Tests still failing after patch:{_R}")
        for line in test_output.splitlines()[:6]:
            print(f"    {_GY}{line}{_R}")

    ledger.add_heal(error_output[:80], patched=True, tests_passed=tests_ok)
    return tests_ok


# ── Executor functions ────────────────────────────────────────────────────────

def _exec_shell(cmd: str, ledger: AchievementLedger, timeout: int = 60) -> tuple[bool, str]:
    env = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
    }
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(WORKSPACE), env=env,
        )
        out = (r.stdout + r.stderr).strip()
        ok  = r.returncode == 0

        ledger.add_command(cmd, ok, out)

        # Phase 4: intercept patchable errors from shell commands
        if not ok and _looks_like_patchable_error(out):
            healed = _live_heal(out, ledger)
            if healed:
                # Retry once after heal
                r2 = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=timeout, cwd=str(WORKSPACE), env=env,
                )
                out = (r2.stdout + r2.stderr).strip()
                ok  = r2.returncode == 0
                ledger.add_command(f"[retry after heal] {cmd}", ok, out)

        return ok, out[:3000]
    except subprocess.TimeoutExpired:
        msg = f"Command timed out after {timeout}s"
        ledger.add_fail(msg)
        return False, msg
    except Exception as e:
        tb = traceback.format_exc()
        # Phase 4: catch unexpected executor crashes too
        if _looks_like_patchable_error(tb):
            _live_heal(tb, ledger)
        ledger.add_fail(str(e))
        return False, str(e)


def _exec_file_read(path_str: str, ledger: AchievementLedger) -> tuple[bool, str]:
    p = Path(path_str).expanduser()
    ok, reason = _FILE_GATE.check(p)
    if not ok:
        return False, f"BLOCKED: {reason}"
    if not p.exists():
        return False, f"File not found: {p}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")[:5000]
        ledger.add_file_read(str(p))
        return True, content
    except Exception as e:
        ledger.add_fail(str(e))
        return False, str(e)


def _exec_file_write(spec: str, context: dict, ledger: AchievementLedger) -> tuple[bool, str]:
    if "::" in spec:
        path_str, content = spec.split("::", 1)
    else:
        path_str = spec
        content  = context.get("write_content", "")
    p = Path(path_str).expanduser()
    ok, reason = _FILE_GATE.check(p)
    if not ok:
        return False, f"BLOCKED: write to {reason}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        ledger.add_file_written(str(p), len(content))
        return True, f"Written {len(content):,} chars → {p}"
    except Exception as e:
        ledger.add_fail(str(e))
        return False, str(e)


def _exec_memory_query(query: str, ledger: AchievementLedger) -> tuple[bool, str]:
    try:
        spec = importlib.util.spec_from_file_location("memory", ADWI_DIR / "memory.py")
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mem  = mod.AdwiMemory()
        result = mem.format_context(query, k=5)
        mem.close()
        return True, result or "No relevant memories found."
    except Exception as e:
        ledger.add_fail(str(e))
        return False, f"Memory error: {e}"


def _exec_web_search(query: str, ledger: AchievementLedger) -> tuple[bool, str]:
    try:
        response = SearchOrchestrator().search(
            query,
            SearchOptions(max_results=5, mode="reason"),
        )
        ledger.add_search(query)
        lines = [
            f"- {r.title} ({r.source})\n  {r.url}\n  {r.snippet[:220]}"
            for r in response.results
        ]
        lines.append(f"\nProvider metrics: {metrics_summary(response.metrics)}")
        return True, "\n".join(lines) if lines else "No results."
    except Exception as e:
        return False, f"Search error: {e}"


# ── Executor dispatcher ───────────────────────────────────────────────────────

def executor_agent(
    step: dict,
    context: dict,
    ledger: AchievementLedger,
    interactive: bool = True,
) -> tuple[bool, str]:
    """
    Execute one plan step with Phase 2 gate + Phase 4 live heal.
    Returns (success, output).
    """
    action      = step.get("action", "")
    action_type = step.get("action_type", "llm_reason")

    risk = classify_risk(action, action_type)

    if risk == "BLOCKED":
        msg = f"Hard-blocked by safety gate: {action[:60]}"
        ledger.add_blocked(action)
        return False, f"SAFETY GATE — BLOCKED: {action}"

    if risk == "REVIEW-REQUIRED":
        if interactive:
            approved = permission_gate(step, ledger)
            if not approved:
                return False, "Step declined by user."
        else:
            ledger.add_blocked(action)
            return False, "SAFETY GATE — non-interactive mode, REVIEW-REQUIRED step skipped."

    # Dispatch by type
    if action_type == "shell":
        return _exec_shell(action, ledger)
    elif action_type == "file_read":
        return _exec_file_read(action, ledger)
    elif action_type == "file_write":
        return _exec_file_write(action, context, ledger)
    elif action_type == "memory_query":
        return _exec_memory_query(action, ledger)
    elif action_type == "web_search":
        return _exec_web_search(action, ledger)
    elif action_type == "obsidian_write":
        vault_path = WORKSPACE / "obsidian-vault" / action
        return _exec_file_write(
            str(vault_path) + "::" + context.get("obsidian_content", ""),
            context, ledger,
        )
    else:  # llm_reason
        ctx_block = ""
        if context.get("step_outputs"):
            prior = [f"Step {k}: {v[:400]}" for k, v in context["step_outputs"].items()]
            ctx_block = "\n\nPrior results:\n" + "\n".join(prior)
        result = _ollama(action + ctx_block, timeout=180)
        ok = bool(result) and not result.startswith("[LLM error")
        return ok, result


# ── Planner agent ─────────────────────────────────────────────────────────────

_PLANNER_SYS = """You are Adwi's Planner Agent.

Map a complex task to a strict JSON array of execution steps.
Each step object must have exactly:
  "id":               integer starting at 1
  "title":            ≤ 8 words
  "action_type":      "shell" | "file_read" | "file_write" | "memory_query" | "web_search" | "llm_reason" | "obsidian_write"
  "action":           exact command, path, query, or prompt
  "depends_on":       list of prerequisite step ids ([] for none)
  "success_criteria": one sentence — what a passing output looks like

Hard rules:
- Never target secrets/, .ssh, .aws, credentials, tokens.
- Prefer read-only steps first; batch mutations last.
- Maximum 8 steps.
- Output ONLY the JSON array. No markdown fences. No explanation.
"""


def planner_agent(task: str) -> list[dict]:
    raw = _ollama(f"Task: {task}\n\nExecution plan:", system=_PLANNER_SYS, timeout=120)
    m   = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return _single_step(task)
    try:
        steps = json.loads(m.group(0))
        if not isinstance(steps, list) or not steps:
            return _single_step(task)
        # Inject task reference for WHY explanations
        for s in steps:
            s["_task"] = task
        return steps
    except Exception:
        return _single_step(task)


def _single_step(task: str) -> list[dict]:
    return [{
        "id": 1, "title": "Direct reasoning", "action_type": "llm_reason",
        "action": task, "depends_on": [], "_task": task,
        "success_criteria": "Coherent, accurate answer produced.",
    }]


# ── Critic agent ──────────────────────────────────────────────────────────────

_CRITIC_SYS = """You are Adwi's Critic Agent.
Respond with ONLY valid JSON: {"verdict": "PASS"|"RETRY"|"FAIL", "reason": "one sentence"}
PASS  = output satisfies success_criteria
RETRY = recoverable error or incomplete (max 3 retries)
FAIL  = hard error, blocked, or declined by user
"""


def critic_agent(step: dict, output: str, attempt: int) -> dict:
    criteria = step.get("success_criteria", "Task completed without error.")
    prompt = (
        f"Step: {step.get('title','?')}\n"
        f"Criteria: {criteria}\n"
        f"Output (attempt {attempt}):\n{output[:1200]}\n\nVerdict?"
    )
    raw = _ollama(prompt, system=_CRITIC_SYS, model=MODEL_FAST, timeout=25)
    m = re.search(r"\{.*?\}", raw, re.S)
    if m:
        try:
            v = json.loads(m.group(0))
            if v.get("verdict") in ("PASS", "RETRY", "FAIL"):
                return v
        except Exception:
            pass
    # Heuristics
    if any(t in output for t in ("BLOCKED", "SAFETY GATE", "declined", "[LLM error")):
        return {"verdict": "FAIL", "reason": "Hard stop or user declined."}
    if "error" in output.lower() and attempt < MAX_RETRIES:
        return {"verdict": "RETRY", "reason": "Error string in output."}
    return {"verdict": "PASS", "reason": "Output looks complete."}


# ── Main graph runner ─────────────────────────────────────────────────────────

class ReasonGraph:

    def __init__(self, task: str, interactive: bool = True):
        self.task        = task
        self.interactive = interactive
        self.plan:     list[dict]      = []
        self.outputs:  dict[int, str]  = {}
        self.verdicts: dict[int, str]  = {}
        self.log:      list[str]       = []
        self.ledger    = AchievementLedger(task)

    def _emit(self, msg: str) -> None:
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log.append(line)
        print(f"  {_GY}{line}{_R}")

    def run(self) -> dict:
        # ── Plan ──────────────────────────────────────────────────────────
        self._emit("Planner: mapping task …")
        self.plan = planner_agent(self.task)
        self._emit(f"Plan: {len(self.plan)} step(s)")
        for s in self.plan:
            risk = classify_risk(s.get("action", ""), s.get("action_type", ""))
            risk_tag = f"  [{_YL}REVIEW{_R}]" if risk == "REVIEW-REQUIRED" else (f"  [{_RD}BLOCKED{_R}]" if risk == "BLOCKED" else "")
            self._emit(f"  [{s['id']}] {s['title']} ({s['action_type']}){risk_tag}")

        # ── Execute + Critique ─────────────────────────────────────────────
        context = {"task": self.task, "step_outputs": self.outputs}

        for step in self.plan:
            sid  = step["id"]
            deps = step.get("depends_on", [])

            dep_failed = [d for d in deps if self.verdicts.get(d) == "FAIL"]
            if dep_failed:
                self._emit(f"  [{sid}] Skipped — dep(s) failed: {dep_failed}")
                self.verdicts[sid] = "FAIL"
                self.outputs[sid]  = f"Skipped: deps {dep_failed} failed."
                self.ledger.add_fail(f"step {sid} skipped due to deps {dep_failed}")
                continue

            attempt = 0
            verdict = {"verdict": "RETRY", "reason": "initial"}

            while verdict["verdict"] == "RETRY" and attempt < MAX_RETRIES:
                attempt += 1
                self._emit(f"  [{sid}] Executing (attempt {attempt}): {step['title']}")

                success, output = executor_agent(
                    step, context, self.ledger, self.interactive
                )

                snip = output[:80].replace("\n", " ")
                self._emit(f"  [{sid}] {'✓' if success else '✗'} → {snip}")

                verdict = critic_agent(step, output, attempt)
                self._emit(f"  [{sid}] Critic: {verdict['verdict']} — {verdict['reason']}")

                if verdict["verdict"] == "RETRY":
                    self._emit(f"  [{sid}] Retrying …")

            self.verdicts[sid]      = verdict["verdict"]
            self.outputs[sid]       = output
            context["step_outputs"] = self.outputs

            if verdict["verdict"] == "FAIL" and not output.startswith("Step declined"):
                self.ledger.add_fail(f"step {sid} ({step['title']}): {output[:60]}")

        # ── Synthesis ─────────────────────────────────────────────────────
        passed  = [sid for sid, v in self.verdicts.items() if v == "PASS"]
        failed  = [sid for sid, v in self.verdicts.items() if v == "FAIL"]
        partial = bool(failed) and bool(passed)

        self._emit(f"Graph complete — {len(passed)} passed / {len(failed)} failed")

        outputs_block = "\n\n".join(
            f"Step {sid} [{self.plan[sid-1]['title'] if sid <= len(self.plan) else '?'}]:\n{out}"
            for sid, out in self.outputs.items()
        )
        summary_prompt = (
            f"Original task: {self.task}\n\n"
            f"Execution results:\n{outputs_block[:4000]}\n\n"
            + ("PARTIAL COMPLETION — some steps failed or were declined.\n\n" if partial else "")
            + "Write a concise, actionable summary of what was accomplished and what (if anything) remains."
        )
        final_answer = _ollama(summary_prompt, timeout=180)

        return {
            "task":         self.task,
            "plan":         self.plan,
            "outputs":      self.outputs,
            "verdicts":     self.verdicts,
            "passed":       passed,
            "failed":       failed,
            "partial":      partial,
            "final_answer": final_answer,
            "log":          self.log,
            "ledger":       self.ledger,
        }


# ── Public entry point ────────────────────────────────────────────────────────

def run_reason(task: str, interactive: bool = True) -> str:
    """Entry point called by adwi_cli.py /reason handler."""
    graph  = ReasonGraph(task, interactive=interactive)
    result = graph.run()

    lines = [
        f"\n{_PU}{_B}  Adwi Reason Engine — Complete{_R}",
        f"  {_GY}Steps: {len(result['plan'])} planned  ·  "
        f"{len(result['passed'])} passed  ·  {len(result['failed'])} failed{_R}",
    ]
    if result["failed"]:
        lines.append(f"  {_YL}Failed steps: {result['failed']}{_R}")

    lines.append(f"\n{result['final_answer']}\n")

    # Achievement Summary (Phase 2 — printed, not returned as string)
    print("\n" + result["ledger"].render())

    return "\n".join(lines)
