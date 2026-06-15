"""
Adwi Nightly Improvement Loop
Runs at 2:00 AM via LaunchAgent com.suneel.adwi-nightly.
Steps: services → log review → AI skill discovery → evals → capability sync → git commit → report
"""

import json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path

HOME      = Path.home()
WORKSPACE = HOME / "SuneelWorkSpace"
ADWI_DIR  = WORKSPACE / "adwi"
NOTES     = WORKSPACE / "notes"
NIGHTLY_LOG_DIR   = NOTES / "nightly-improvement-logs"
CLI_PY            = ADWI_DIR / "adwi_cli.py"
JOURNAL           = NOTES / "adwi-learning-journal.md"
MISTAKES          = NOTES / "adwi-mistakes-and-fixes.md"
CAPABILITIES      = ADWI_DIR / "capabilities.json"
PENDING_FILE      = NOTES / "adwi-pending-improvements.md"
OBSIDIAN_VAULT    = WORKSPACE / "obsidian-vault"
OBSIDIAN_BRIDGE   = "http://127.0.0.1:5056"
SEARXNG_URL       = "http://127.0.0.1:8888"

# Load config/.env for API keys
def _load_env():
    env_file = WORKSPACE / "config" / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ.setdefault(k, v)

_load_env()
TAVILY_API_KEY    = os.environ.get("TAVILY_API_KEY",    "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
EXA_API_KEY       = os.environ.get("EXA_API_KEY",       "")

NOW      = datetime.now()
DATE_STR = NOW.strftime("%Y-%m-%d")
TIME_STR = NOW.strftime("%H:%M")
LOG_PATH = NIGHTLY_LOG_DIR / f"nightly-{DATE_STR}.md"

DESKTOP          = HOME / "Desktop"
AIDER_BIN        = HOME / ".local" / "bin" / "aider"
MAX_FIX_ATTEMPTS = 3

_ANSI = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _strip(text: str) -> str:
    return _ANSI.sub("", text)


def _pr(msg: str):
    print(msg, flush=True)


# ── Ollama ────────────────────────────────────────────────────────────────────

def _ollama_ok() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5)
        return True
    except Exception:
        return False


def _ollama_ask(prompt: str, model: str = "adwi:latest", timeout: int = 180) -> str:
    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.7, "num_predict": 1500}
    }).encode()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate", data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["response"].strip()
    except Exception as e:
        return f"[Ollama error: {e}]"


# ── Subprocess helpers ─────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 60, cwd: Path = WORKSPACE) -> tuple[int, str, str]:
    env = {**os.environ,
           "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "HOME": str(HOME)}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       cwd=str(cwd), env=env)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _run_adwi_cmd(command: str, timeout: int = 300) -> str:
    """Pipe a /command into adwi_cli.py and return stripped output."""
    env = {**os.environ,
           "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "HOME": str(HOME)}
    r = subprocess.run(
        ["python3", str(CLI_PY)],
        input=f"{command}\n/exit\n",
        capture_output=True, text=True, timeout=timeout,
        cwd=str(WORKSPACE), env=env
    )
    return _strip(r.stdout + r.stderr)


# ── Step 1: Services ──────────────────────────────────────────────────────────

def step_services() -> dict:
    status: dict = {}

    # Ollama
    if _ollama_ok():
        status["ollama"] = "running"
    else:
        _run(["/opt/homebrew/bin/brew", "services", "start", "ollama"], timeout=30)
        time.sleep(8)
        status["ollama"] = "started" if _ollama_ok() else "failed — manual start needed"

    # Docker
    _, out, _ = _run(["/opt/homebrew/bin/docker", "ps", "--format", "{{.Names}}"], timeout=10)
    running = set(out.splitlines())
    expected = {"suneel-open-webui", "suneel-n8n", "suneel-searxng", "suneel-qdrant"}
    missing = expected - running

    if missing:
        compose = WORKSPACE / "local-ai-stack/docker-compose.yml"
        if compose.exists():
            _run(["/opt/homebrew/bin/docker", "compose", "-f", str(compose), "up", "-d"],
                 timeout=90)
            time.sleep(6)

    _, out2, _ = _run(["/opt/homebrew/bin/docker", "ps", "--format", "{{.Names}}"], timeout=10)
    running2 = set(out2.splitlines())
    status["docker_up"]      = sorted(running2 & expected)
    status["docker_missing"] = sorted(expected - running2)
    return status


# ── Step 2: Log review ────────────────────────────────────────────────────────

def step_review_logs() -> dict:
    summary: dict = {}

    repair_dir = NOTES / "adwi-repair-logs"
    repairs = []
    if repair_dir.exists():
        for f in sorted(repair_dir.glob("*.md"))[-7:]:
            text = f.read_text(encoding="utf-8", errors="ignore")
            repairs.append({"file": f.name, "snippet": text[:400]})
    summary["repair_count"]   = len(repairs)
    summary["repair_snippets"] = repairs

    summary["journal_tail"] = (
        JOURNAL.read_text(encoding="utf-8", errors="ignore")[-2000:]
        if JOURNAL.exists() else ""
    )
    summary["mistakes_tail"] = (
        MISTAKES.read_text(encoding="utf-8", errors="ignore")[-1000:]
        if MISTAKES.exists() else ""
    )
    return summary


# ── Step 3: AI skill discovery ────────────────────────────────────────────────

def step_skill_discovery(logs: dict) -> str:
    caps = []
    if CAPABILITIES.exists():
        try:
            caps = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
        except Exception:
            pass
    cap_names = [c.get("name", "") for c in caps] if isinstance(caps, list) else []

    prompt = f"""You are Adwi's nightly self-improvement engine. Today is {DATE_STR}.

Current state:
- {len(cap_names)} capabilities: {', '.join(cap_names[:30])}
- Hardware: Apple M4 Max 64GB — ONLY suggest models in 8B–35B range. NEVER 70B+.
- Stack: Ollama, Open WebUI, n8n, SearXNG, Qdrant, 10 MCP servers
- Local models: adwi:latest (18GB Qwen3 MoE 30B), llama3.1:8b, qwen3:0.6b, minicpm-v, nomic-embed-text

Recent journal:
{logs.get('journal_tail', '')[-1200:]}

Recent mistakes/fixes:
{logs.get('mistakes_tail', '')[-600:]}

Suggest exactly 5 concrete improvements to make Suneel's daily workflow better.
For each, output one JSON object per line (no extra text, no markdown):
{{"name":"slug","type":"command|model|mcp|workflow|fix","title":"Title","description":"One sentence user benefit","priority":"high|medium|low","effort":"minutes|hours|days","implementation_hint":"One paragraph technical note"}}

Focus on:
1. New /commands filling gaps in current capabilities
2. Ollama models in 8B–35B range (coding, reasoning, vision)
3. New MCP servers (filesystem extensions, calendar, browser, database)
4. n8n workflow automations saving Suneel time
5. Routing improvements or error recovery patterns

Output only the 5 JSON lines, nothing else."""

    return _ollama_ask(prompt, timeout=120)


def _save_pending(suggestions: str):
    header = "# Adwi Pending Improvements\n"
    existing = PENDING_FILE.read_text(encoding="utf-8") if PENDING_FILE.exists() else header
    entry = f"\n## {DATE_STR} {TIME_STR}\n```json\n{suggestions}\n```\n"
    PENDING_FILE.write_text(existing + entry, encoding="utf-8")


# ── Step 3b: Aider Self-Healing ───────────────────────────────────────────────

def _find_test_suite() -> tuple:
    """Return (cmd_list, cwd) for the best test runner found in the workspace."""
    # pytest: explicit evals directory
    evals_dir = ADWI_DIR / "evals"
    if evals_dir.exists() and any(evals_dir.glob("test_*.py")):
        return (
            ["python3", "-m", "pytest", str(evals_dir), "-x", "--tb=short", "-q"],
            WORKSPACE,
        )
    # pytest: project-level markers
    for marker in ("pytest.ini", "pyproject.toml", "setup.cfg"):
        if (WORKSPACE / marker).exists():
            return (
                ["python3", "-m", "pytest", "-x", "--tb=short", "-q"],
                WORKSPACE,
            )
    # npm/jest
    if (WORKSPACE / "package.json").exists():
        return (["npm", "test", "--", "--watchAll=false"], WORKSPACE)
    return ([], WORKSPACE)


def _run_tests(cmd: list, cwd: Path, timeout: int = 120) -> tuple:
    """Return (passed: bool, output: str)."""
    if not cmd:
        return True, "no test suite"
    env = {
        **os.environ,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(HOME),
    }
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(cwd), env=env,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "test suite timed out"
    except Exception as e:
        return False, str(e)


def _extract_failing_files(output: str) -> list:
    """Parse pytest/jest output for source files (not test files) that need fixing."""
    files = set()
    for m in re.finditer(r"([\w/\-\.]+\.py)(?:[::][\w\.]+)?(?::\d+)?", output):
        p = WORKSPACE / m.group(1)
        if p.exists() and "test_" not in p.name and p.name != "__init__.py":
            files.add(p)
    if not files:
        if CLI_PY.exists():
            files.add(CLI_PY)
    return list(files)[:6]


def _invoke_aider(error_output: str, files: list, attempt: int) -> tuple:
    """Run Aider non-interactively on the failing files. Returns (ok: bool, log: str)."""
    if not AIDER_BIN.exists():
        return False, f"Aider not found at {AIDER_BIN}"

    prompt = (
        f"[Adwi nightly self-healing — attempt {attempt}/{MAX_FIX_ATTEMPTS}]\n\n"
        f"Automated test suite failed. Exact error output:\n\n"
        f"```\n{error_output[:3000]}\n```\n\n"
        f"Fix the minimum number of lines needed to make the tests pass. "
        f"Do not add new features, refactor beyond the failing code, or change "
        f"any behaviour that currently passes. Apply changes directly to the files."
    )
    cmd = [
        str(AIDER_BIN),
        "--model", "ollama/adwi:latest",
        "--no-git",        # nightly.py handles its own git operations
        "--yes-always",    # never wait for confirmation
        "--no-pretty",
        "--no-stream",
        "--message", prompt,
    ] + [str(f) for f in files]

    env = {
        **os.environ,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(HOME),
        "OLLAMA_API_BASE": "http://127.0.0.1:11434",
    }
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=str(WORKSPACE), env=env,
        )
        return r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    except subprocess.TimeoutExpired:
        return False, "Aider timed out after 10 minutes"
    except Exception as e:
        return False, str(e)


def step_aider_heal() -> dict:
    """
    Pillar 1 autonomous self-healing:
      1. Detect test suite
      2. Run — if passing, return immediately (nothing to fix)
      3. Invoke Aider up to MAX_FIX_ATTEMPTS times
      4. If fixed: cut auto-fix/morning-review-YYYY-MM-DD branch, commit, push
      5. If still failing after all attempts: rollback Aider changes, write
         failure report to ~/Desktop/adwi-repair-report-YYYY-MM-DD.md
    """
    result = {
        "skipped_reason": None,
        "ran_tests": False,
        "tests_passed_before": None,
        "tests_passed_after": None,
        "attempts": 0,
        "branch": None,
        "report_path": None,
    }

    cmd, cwd = _find_test_suite()
    if not cmd:
        result["skipped_reason"] = "no test suite found in workspace"
        return result

    result["ran_tests"] = True
    passed_before, initial_output = _run_tests(cmd, cwd)
    result["tests_passed_before"] = passed_before

    if passed_before:
        result["skipped_reason"] = "tests already passing — nothing to fix"
        return result

    _pr(f"  ⚠ Tests failing — invoking Aider ({MAX_FIX_ATTEMPTS} max attempts)...")

    # Snapshot git HEAD so we can rollback if all attempts fail
    rc, orig_head, _ = _run(["git", "rev-parse", "HEAD"], timeout=10)
    _, current_branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=10)

    files = _extract_failing_files(initial_output)
    error_log = initial_output
    fixed = False

    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        result["attempts"] = attempt
        _pr(f"    Attempt {attempt}/{MAX_FIX_ATTEMPTS}: Aider on {len(files)} file(s)...")
        _invoke_aider(error_log, files, attempt)
        passed, new_output = _run_tests(cmd, cwd)
        if passed:
            fixed = True
            break
        error_log = new_output
        files = _extract_failing_files(new_output) or files  # reuse previous if no new clues

    result["tests_passed_after"] = fixed

    if fixed:
        branch = f"auto-fix/morning-review-{DATE_STR}"
        _run(["git", "checkout", "-b", branch], timeout=15)
        _run(["git", "add", "-A"], timeout=10)
        _run(
            ["git", "commit", "-m",
             f"auto-fix: nightly self-healing — {DATE_STR} ({result['attempts']} attempt(s))"],
            timeout=20,
        )
        _run(["git", "push", "-u", "origin", branch], timeout=60)
        result["branch"] = branch
        _pr(f"  ✓ Fixed and pushed → {branch}")

    else:
        # Roll back every file Aider touched
        _run(["git", "checkout", "--", "."], timeout=15)
        if current_branch and current_branch != "HEAD":
            _run(["git", "checkout", current_branch], timeout=10)

        DESKTOP.mkdir(parents=True, exist_ok=True)
        report_path = DESKTOP / f"adwi-repair-report-{DATE_STR}.md"
        lines = [
            f"# Adwi Self-Healing Report — {DATE_STR} {TIME_STR}",
            "",
            "**Status: FAILED — manual intervention required**",
            "",
            f"Aider ran **{MAX_FIX_ATTEMPTS} attempts** and could not pass the test suite.",
            "",
            "## Initial Failures",
            "```",
            initial_output[:2000],
            "```",
            "",
            "## Final State After Last Attempt",
            "```",
            error_log[:2000],
            "```",
            "",
            "## Files Targeted",
        ] + [f"- `{f}`" for f in files] + [
            "",
            "## Next Steps",
            "1. Run `python3 -m pytest adwi/evals/ -v` to inspect failures manually",
            "2. Check `notes/adwi-repair-logs/` for prior repair history",
            "3. Review the files listed above for recent changes",
        ]
        report_path.write_text("\n".join(lines), encoding="utf-8")
        result["report_path"] = str(report_path)
        _pr(f"  ✗ Could not auto-fix — see: {report_path}")

    return result


# ── Step 4: Evals ─────────────────────────────────────────────────────────────

def step_evals() -> dict:
    results: dict = {}

    # Syntax check
    rc, _, err = _run(["python3", "-m", "py_compile", str(CLI_PY)], timeout=30)
    results["syntax_ok"]    = rc == 0
    results["syntax_error"] = err if rc != 0 else ""

    # Routing eval (piped)
    try:
        out = _run_adwi_cmd("/eval-routing", timeout=180)
        results["routing_eval"] = out[-2000:]
    except Exception as e:
        results["routing_eval"] = f"Error: {e}"

    return results


# ── Step 5: Capability sync ───────────────────────────────────────────────────

def step_capability_sync() -> dict:
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("repair", str(ADWI_DIR / "repair.py"))
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cmds    = mod.scan_implemented_commands(CLI_PY)
        updated = mod.update_capabilities_json(CLI_PY, cmds)
        return {"commands_found": len(cmds), "capabilities_updated": updated}
    except Exception as e:
        return {"error": str(e)}


# ── Step 6: Git commit ────────────────────────────────────────────────────────

def step_git_commit() -> dict:
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("backup", str(ADWI_DIR / "backup.py"))
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.do_backup(f"Nightly improvement — {DATE_STR} {TIME_STR}")
    except Exception as e:
        return {"success": False, "message": str(e)}


# ── Step 5b: System Health ────────────────────────────────────────────────────

def step_system_health() -> dict:
    """Non-destructive audits: brew, npm, disk, docker stats. Report only — never auto-applies."""
    health: dict = {}

    # Disk
    rc, out, _ = _run(["df", "-h", "/"], timeout=10)
    if rc == 0 and out:
        line = out.splitlines()[-1].split()
        health["disk_used"]  = line[2] if len(line) > 2 else "?"
        health["disk_avail"] = line[3] if len(line) > 3 else "?"
        health["disk_pct"]   = line[4] if len(line) > 4 else "?"

    # Brew outdated (safe, read-only)
    rc, out, _ = _run(["/opt/homebrew/bin/brew", "outdated", "--verbose"], timeout=60)
    lines  = [l for l in out.splitlines() if l.strip()]
    health["brew_outdated_count"] = len(lines)
    health["brew_outdated"]       = lines[:20]  # cap at 20 for the brief

    # npm outdated globals (safe, read-only)
    rc, out, _ = _run(["/opt/homebrew/bin/npm", "outdated", "-g", "--depth=0"], timeout=30)
    npm_lines = [l for l in out.splitlines() if l.strip() and "Package" not in l]
    health["npm_outdated_count"] = len(npm_lines)
    health["npm_outdated"]       = npm_lines[:10]

    # Docker stats snapshot (one-shot, no stream)
    rc, out, _ = _run(
        ["/opt/homebrew/bin/docker", "stats", "--no-stream",
         "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
        timeout=15,
    )
    health["docker_stats"] = out.splitlines()

    return health


# ── Step 5c: Web Research ─────────────────────────────────────────────────────

_RESEARCH_TOPICS = [
    ("Ollama",     "ollama release notes latest version"),
    ("Open WebUI", "open-webui new release changelog"),
    ("n8n",        "n8n workflow automation release notes"),
    ("Qdrant",     "qdrant vector database release"),
    ("Aider",      "aider AI coding assistant release"),
]


def _searxng_query(query: str, max_results: int = 3) -> list:
    """Try Tavily first (better quality for release notes), fall back to SearXNG."""
    # Primary: Tavily
    if TAVILY_API_KEY:
        try:
            payload = json.dumps({
                "api_key": TAVILY_API_KEY, "query": query,
                "search_depth": "basic", "max_results": max_results,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.tavily.com/search", data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            results = [
                {"title": i.get("title",""), "url": i.get("url",""), "content": i.get("content","")[:300]}
                for i in data.get("results", [])[:max_results]
            ]
            if results:
                return results
        except Exception:
            pass  # fall through to SearXNG

    # Fallback: SearXNG (local)
    params = urllib.parse.urlencode({
        "q": query, "format": "json", "language": "en",
        "engines": "google,duckduckgo", "safesearch": "0",
    })
    try:
        req = urllib.request.Request(
            f"{SEARXNG_URL}/search?{params}", headers={"User-Agent": "Adwi-Nightly/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return [
            {"title": i.get("title",""), "url": i.get("url",""), "content": i.get("content","")[:300]}
            for i in data.get("results", [])[:max_results]
        ]
    except Exception as e:
        return [{"title": "search error", "url": "", "content": str(e)}]


def step_web_research() -> dict:
    """Query SearXNG for release notes on key stack tools. Read-only."""
    research: dict = {}
    for tool, query in _RESEARCH_TOPICS:
        _pr(f"  searching: {query}")
        results = _searxng_query(query)
        research[tool] = results
        time.sleep(2)  # polite pacing
    return research


# ── Step 10: Obsidian Daily Note ─────────────────────────────────────────────

def step_obsidian_daily_note(data: dict) -> str | None:
    """Write a structured daily note to the Obsidian vault daily-notes/ directory."""
    OBSIDIAN_VAULT.mkdir(parents=True, exist_ok=True)
    daily_dir = OBSIDIAN_VAULT / "daily-notes"
    daily_dir.mkdir(parents=True, exist_ok=True)

    svc    = data.get("services",  {})
    health = data.get("sys_health", {})
    sk     = data.get("skill_suggestions", "")
    gc     = data.get("git_commit", {})
    research = data.get("web_research", {})

    lines = [
        f"# Daily Note — {DATE_STR}",
        f"*Generated by adwi nightly loop at {TIME_STR}*",
        "",
        "## System Status",
        f"- Ollama: {svc.get('ollama', 'unknown')}",
        f"- Docker: {', '.join(svc.get('docker_up', []))}",
        f"- Disk: {health.get('disk_used','?')} used / {health.get('disk_avail','?')} free ({health.get('disk_pct','?')})",
        f"- Brew packages outdated: {health.get('brew_outdated_count', 0)}",
        "",
        "## Git Commit",
    ]
    if gc.get("success"):
        lines.append(f"- ✓ {gc.get('commit_hash','')} — pushed: {gc.get('pushed', False)}")
    else:
        lines.append(f"- ⚠ {gc.get('message','no changes')}")

    if research:
        lines += ["", "## Web Research Highlights"]
        for tool, results in research.items():
            for r in results[:1]:
                if r.get("title"):
                    lines.append(f"- **{tool}**: [{r['title']}]({r['url']})")

    if sk and sk != "[Ollama offline — skipped]":
        lines += ["", "## AI Skill Suggestions (Pending Approval)", "```json", sk[:1500], "```"]

    lines += ["", "---", f"*Full log: `notes/nightly-improvement-logs/nightly-{DATE_STR}.md`*", ""]

    note_path = daily_dir / f"{DATE_STR}.md"
    # Append if exists (preserve any manual entries from the day)
    existing = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    note_path.write_text(existing + "\n" + "\n".join(lines), encoding="utf-8")

    # Also try the bridge (non-fatal if not running)
    try:
        payload = json.dumps({"content": "\n".join(lines)}).encode("utf-8")
        req = urllib.request.Request(
            f"{OBSIDIAN_BRIDGE}/daily-note", data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # bridge offline is fine — file was written directly

    return str(note_path)


# ── Step 7: Write report ──────────────────────────────────────────────────────

def step_write_report(data: dict) -> Path:
    NIGHTLY_LOG_DIR.mkdir(parents=True, exist_ok=True)

    svc  = data.get("services", {})
    lr   = data.get("log_review", {})
    heal = data.get("aider_heal", {})
    ev   = data.get("evals", {})
    cs   = data.get("cap_sync", {})
    gc   = data.get("git_commit", {})
    sk   = data.get("skill_suggestions", "[none]")

    lines = [
        f"# Adwi Nightly Improvement — {DATE_STR} {TIME_STR}",
        "",
        "## 1. Services",
        f"- Ollama: {svc.get('ollama', 'unknown')}",
        f"- Docker up: {', '.join(svc.get('docker_up', []))}",
    ]
    if svc.get("docker_missing"):
        lines.append(f"- Docker missing: {', '.join(svc['docker_missing'])}")

    lines += [
        "",
        "## 2. Log Review",
        f"- Repair logs reviewed: {lr.get('repair_count', 0)}",
    ]

    lines += [
        "",
        "## 3. AI Skill Discovery",
        "```json",
        sk,
        "```",
    ]

    lines += ["", "## 3b. Aider Self-Healing"]
    if heal.get("skipped_reason"):
        lines.append(f"- Skipped: {heal['skipped_reason']}")
    elif not heal.get("ran_tests"):
        lines.append("- Not run (no result)")
    else:
        lines.append(f"- Tests before: {'✓ passing' if heal.get('tests_passed_before') else '✗ failing'}")
        if not heal.get("tests_passed_before"):
            lines.append(f"- Aider attempts: {heal.get('attempts', 0)}")
            if heal.get("tests_passed_after"):
                lines.append(f"- ✓ Fixed → branch: `{heal.get('branch')}`")
            else:
                lines.append(f"- ✗ Could not fix — report on Desktop: `{heal.get('report_path')}`")

    lines += [
        "",
        "## 4. Evals",
        f"- Syntax: {'✓ OK' if ev.get('syntax_ok') else '✗ ' + ev.get('syntax_error', '')}",
        "- Routing eval output:",
        "```",
        ev.get("routing_eval", "")[-1500:],
        "```",
    ]

    lines += ["", "## 5. Capability Sync"]
    if "error" in cs:
        lines.append(f"- ✗ {cs['error']}")
    else:
        lines.append(f"- Commands found: {cs.get('commands_found', 0)}")
        lines.append(f"- Capabilities updated: {cs.get('capabilities_updated', 0)}")

    lines += ["", "## 6. Git Commit"]
    if gc.get("success"):
        lines.append(f"- ✓ {gc.get('commit_hash', '')} pushed: {gc.get('pushed', False)}")
    else:
        lines.append(f"- ⚠ {gc.get('message', 'no changes or error')}")

    # ── System Health section ──────────────────────────────────────────────────
    health = data.get("sys_health", {})
    lines += [
        "",
        "## 7. System Health",
        f"- Disk: {health.get('disk_used','?')} used, {health.get('disk_avail','?')} free ({health.get('disk_pct','?')})",
        f"- Brew packages outdated: {health.get('brew_outdated_count', 0)}",
    ]
    if health.get("brew_outdated"):
        for pkg in health["brew_outdated"][:5]:
            lines.append(f"  - {pkg}")
    if health.get("npm_outdated_count", 0) > 0:
        lines.append(f"- npm globals outdated: {health['npm_outdated_count']}")
        for pkg in health.get("npm_outdated", [])[:5]:
            lines.append(f"  - {pkg}")
    if health.get("docker_stats"):
        lines.append("- Docker stats:")
        for s in health["docker_stats"]:
            lines.append(f"  - {s}")

    # ── Web Research section ───────────────────────────────────────────────────
    research = data.get("web_research", {})
    if research:
        lines += ["", "## 8. Web Research (Release Notes)"]
        for tool, results in research.items():
            lines.append(f"\n### {tool}")
            for r in results:
                if r.get("title"):
                    lines.append(f"- [{r['title']}]({r['url']})")
                    if r.get("content"):
                        lines.append(f"  > {r['content'][:200]}")

    # ── Pending User Approval section ─────────────────────────────────────────
    pending = []
    if health.get("brew_outdated_count", 0) > 0:
        pending.append(f"- `brew upgrade` — {health['brew_outdated_count']} package(s) available. Review with: `brew outdated --verbose`")
    if health.get("npm_outdated_count", 0) > 0:
        pending.append(f"- `npm update -g` — {health['npm_outdated_count']} global npm package(s) outdated")
    if sk and sk != "[none]" and sk != "[Ollama offline — skipped]":
        pending.append("- Review AI skill suggestions in Section 3 above — implement with your approval")

    lines += ["", "## ⚠ Pending User Approval"]
    if pending:
        lines += pending
    else:
        lines.append("- Nothing requires approval tonight — system is healthy ✓")

    LOG_PATH.write_text("\n".join(lines), encoding="utf-8")

    # Also write morning brief to Desktop
    brief_path = HOME / "Desktop" / "morning_brief.md"
    brief_lines = [
        f"# 🌅 Adwi Morning Brief — {DATE_STR}",
        f"*Nightly run completed at {TIME_STR}*",
        "",
        "## Quick Status",
        f"- Ollama: {svc.get('ollama', '?')}",
        f"- Docker: {', '.join(svc.get('docker_up', []))}",
        f"- Disk: {health.get('disk_used','?')} used / {health.get('disk_avail','?')} free",
        f"- Syntax check: {'✓ OK' if ev.get('syntax_ok') else '✗ ' + ev.get('syntax_error','')}",
        "",
        "## ⚠ Pending User Approval",
    ] + (pending if pending else ["- Nothing — all clear ✓"]) + [
        "",
        "## AI Skill Suggestions",
        "```json", sk[:1500], "```",
        "",
        "## Release Notes Found",
    ]
    for tool, results in research.items():
        for r in results[:1]:
            if r.get("title"):
                brief_lines.append(f"- **{tool}**: [{r['title']}]({r['url']})")
    brief_lines += [
        "",
        f"*Full nightly log: `notes/nightly-improvement-logs/nightly-{DATE_STR}.md`*",
        f"*Obsidian daily note: `obsidian-vault/daily-notes/{DATE_STR}.md`*",
    ]
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text("\n".join(brief_lines), encoding="utf-8")

    return LOG_PATH


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    NIGHTLY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    _pr(f"\n{'='*60}")
    _pr(f"  ADWI NIGHTLY IMPROVEMENT — {DATE_STR} {TIME_STR}")
    _pr(f"{'='*60}\n")

    data: dict = {}

    _pr("[1/6] Services health check...")
    data["services"] = step_services()
    svc = data["services"]
    _pr(f"  ollama={svc.get('ollama')}  docker_up={svc.get('docker_up')}")

    _pr("[2/6] Reviewing logs...")
    data["log_review"] = step_review_logs()
    _pr(f"  {data['log_review'].get('repair_count', 0)} repair logs reviewed")

    _pr("[3/7] AI skill discovery...")
    if _ollama_ok():
        data["skill_suggestions"] = step_skill_discovery(data["log_review"])
        _save_pending(data["skill_suggestions"])
        _pr("  Suggestions saved → notes/adwi-pending-improvements.md")
    else:
        data["skill_suggestions"] = "[Ollama offline — skipped]"
        _pr("  ⚠ Ollama offline, skipping")

    _pr("[3b/7] Aider self-healing (detect & fix test failures)...")
    data["aider_heal"] = step_aider_heal()
    ah = data["aider_heal"]
    if ah.get("skipped_reason"):
        _pr(f"  skipped: {ah['skipped_reason']}")
    elif ah.get("tests_passed_after"):
        _pr(f"  ✓ Fixed → {ah.get('branch')}")
    elif not ah.get("tests_passed_before"):
        _pr(f"  ✗ Could not auto-fix — check ~/Desktop for report")

    _pr("[4/7] Running evals...")
    data["evals"] = step_evals()
    ev = data["evals"]
    _pr(f"  Syntax: {'OK' if ev.get('syntax_ok') else 'FAIL: ' + ev.get('syntax_error','')}")

    _pr("[5/7] Memory scan (terminal + git + notes)...")
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("memory", ADWI_DIR / "memory.py")
        _mod  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mem  = _mod.AdwiMemory()
        _t = _mem.scan_terminal(200)
        _g = _mem.scan_git_commits(n=30)
        _n = _mem.scan_notes(max_per_file=8)
        _mem.close()
        data["memory_scan"] = {"terminal": _t, "git": _g, "notes": _n}
        _pr(f"  +{_t} terminal, +{_g} git, +{_n} notes")
    except Exception as _e:
        data["memory_scan"] = {"error": str(_e)}
        _pr(f"  ⚠ memory scan: {_e}")

    _pr("[5b/10] System health audit (brew, npm, disk, docker)...")
    data["sys_health"] = step_system_health()
    sh = data["sys_health"]
    _pr(f"  disk {sh.get('disk_avail','?')} free | brew outdated: {sh.get('brew_outdated_count',0)} | npm outdated: {sh.get('npm_outdated_count',0)}")

    _pr("[5c/10] Web research (SearXNG release note queries)...")
    try:
        data["web_research"] = step_web_research()
        _pr(f"  searched {len(data['web_research'])} tool(s)")
    except Exception as _e:
        data["web_research"] = {}
        _pr(f"  ⚠ web research: {_e}")

    _pr("[6/10] Capability sync...")
    data["cap_sync"] = step_capability_sync()
    cs = data["cap_sync"]
    if "error" not in cs:
        _pr(f"  {cs.get('commands_found',0)} commands, {cs.get('capabilities_updated',0)} updated")
    else:
        _pr(f"  ⚠ {cs['error']}")

    _pr("[7/10] Git commit + push...")
    data["git_commit"] = step_git_commit()
    gc = data["git_commit"]
    if gc.get("success"):
        pushed = "→ pushed" if gc.get("pushed") else "→ local only"
        _pr(f"  ✓ {gc.get('commit_hash','')} {pushed}")
    else:
        _pr(f"  ⚠ {gc.get('message','no changes')}")

    _pr("[8/10] Writing Obsidian daily note...")
    try:
        note_path = step_obsidian_daily_note(data)
        _pr(f"  ✓ {note_path}")
    except Exception as _e:
        _pr(f"  ⚠ daily note: {_e}")

    report = step_write_report(data)
    _pr(f"\n✓ Nightly log:     {report}")
    _pr(f"✓ Morning brief:   ~/Desktop/morning_brief.md")
    _pr(f"✓ Obsidian note:   obsidian-vault/daily-notes/{DATE_STR}.md")
    _pr(f"{'='*60}\n")


if __name__ == "__main__":
    main()
