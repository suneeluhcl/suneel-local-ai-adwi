"""
Adwi Self-Repair Module
Classify errors, snapshot files, apply patches, run tests, write logs.
All mutations are backup-first. Max 2 retries per repair loop.
Hard rules: no secrets, no sudo, no destructive ops.
"""
import json, os, re, shutil, subprocess, textwrap, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

try:
    from adwi.path_validator import PathValidator
except ModuleNotFoundError:
    from path_validator import PathValidator  # type: ignore

# ── Paths ──────────────────────────────────────────────────────────────────────
HOME       = Path.home()
WORKSPACE  = HOME / "SuneelWorkSpace"
ADWI_DIR   = WORKSPACE / "adwi"
NOTES      = WORKSPACE / "notes"
BIN        = WORKSPACE / "bin"
REPAIR_DIR = NOTES / "adwi-repair-logs"
BACKUP_DIR = REPAIR_DIR / "backups"

CLI_FILE       = ADWI_DIR / "adwi_cli.py"
ROUTING_FILE   = ADWI_DIR / "model-routing.env"
ROOTS_FILE     = ADWI_DIR / "allowed-read-roots.txt"
CAPS_FILE      = ADWI_DIR / "capabilities.json"
JOURNAL_FILE   = NOTES / "adwi-learning-journal.md"
MISTAKES_FILE  = NOTES / "adwi-mistakes-and-fixes.md"
ROADMAP_FILE   = NOTES / "adwi-capability-roadmap.md"

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

# Approved files Adwi can patch (no secrets, no system files, no bin scripts)
PATCHABLE_FILES = {
    str(CLI_FILE.resolve()),
    str(ROUTING_FILE.resolve()),
    str(ROOTS_FILE.resolve()),
    str(CAPS_FILE.resolve()),
    str(JOURNAL_FILE.resolve()),
    str(MISTAKES_FILE.resolve()),
    str(ROADMAP_FILE.resolve()),
}

# Error category → relevant files to inspect
CATEGORY_CONTEXT = {
    "adwi_python":     [CLI_FILE],
    "shell_syntax":    [BIN / "adwi"],
    "api_routing":     [ROUTING_FILE],
    "ollama":          [ROUTING_FILE],
    "docker":          [],
    "knowledge_sync":  [],
    "missing_tool":    [],
    "unknown":         [CLI_FILE],
}

ERROR_PATTERNS = [
    (re.compile(r"SyntaxError|IndentationError|adwi_cli\.py.*line|line.*adwi_cli\.py", re.I), "adwi_python"),
    (re.compile(r"NameError|AttributeError|ImportError|TypeError.*adwi|ModuleNotFoundError", re.I), "adwi_python"),
    (re.compile(r"zsh:.*syntax error|parse error|unexpected EOF|heredoc|quoting", re.I), "shell_syntax"),
    (re.compile(r"HTTP Error 400|HTTP Error 401|HTTP Error 429|model.*not.*found|gemini.*flash.*invalid", re.I), "api_routing"),
    (re.compile(r"Ollama|connection refused.*11434|connection.*11434.*refused", re.I), "ollama"),
    (re.compile(r"docker.*not running|container.*exited|port.*already.*in.*use", re.I), "docker"),
    (re.compile(r"sync.openwebui|knowledge.*sync|watcher.*not", re.I), "knowledge_sync"),
    (re.compile(r"command not found|No module named|not installed|cannot import", re.I), "missing_tool"),
]

CATEGORY_HINTS = {
    "adwi_python":    ["Run: python3 -m py_compile adwi/adwi_cli.py", "Check line numbers in the error"],
    "shell_syntax":   ["Check bin/adwi for heredoc quoting", "Use /repair-adwi to auto-check"],
    "api_routing":    ["Check model-routing.env model name", "Verify OPENWEBUI_API_KEY in secrets"],
    "ollama":         ["Start Ollama: start-ai", "Check: ollama list"],
    "docker":         ["Run: docker ps", "Check logs: docker logs suneel-open-webui"],
    "knowledge_sync": ["Run: status-openwebui-knowledge-watcher", "Run: sync-openwebui-knowledge"],
    "missing_tool":   ["Check ~/SuneelWorkSpace/adwi/bin/", "Install missing packages with pip3"],
    "unknown":        ["Run /repair-adwi for diagnostics", "Check recent logs in adwi/notes/adwi-action-logs/"],
}


# ── Error classification ───────────────────────────────────────────────────────
def classify_error(text: str) -> tuple[str, list[str]]:
    """Return (category, hints)."""
    text = str(text or "")
    for pat, cat in ERROR_PATTERNS:
        if pat.search(text):
            return cat, CATEGORY_HINTS.get(cat, [])
    return "unknown", CATEGORY_HINTS["unknown"]


# ── File safety ────────────────────────────────────────────────────────────────
def is_patchable(path: Path) -> bool:
    return str(path.resolve()) in PATCHABLE_FILES

# Blocked roots for file-read operations in the repair loop.
# Uses PathValidator (resolve + relative_to) rather than str.startswith so that
# a path like /tmp/secrets_copy does not accidentally pass a prefix check on "secrets".
_READ_GATE = PathValidator(
    allowed_roots=[],
    blocked_roots=[
        WORKSPACE / "secrets", HOME / ".ssh", HOME / ".gnupg",
        HOME / "Library" / "Keychains", HOME / ".aws",
    ],
)

def is_safe_to_read(path: Path) -> bool:
    ok, _ = _READ_GATE.check(path)
    return ok


# ── Snapshot / patch ──────────────────────────────────────────────────────────
def snapshot_file(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{stamp}-{path.name}"
    shutil.copy2(path, dest)
    return dest

def restore_file(backup: Path, dest: Path) -> None:
    shutil.copy2(backup, dest)

def apply_patch(path: Path, old_text: str, new_text: str) -> tuple[bool, str, Path | None]:
    """
    Replace old_text with new_text in file. Backs up first.
    Returns (success, message, backup_path).
    """
    if not path.exists():
        return False, f"File not found: {path}", None
    if not is_patchable(path):
        return False, f"File not in patchable set: {path.name}", None
    content = path.read_text(encoding="utf-8")
    if old_text not in content:
        return False, f"old_text not found in {path.name} — patch cannot apply", None
    backup = snapshot_file(path)
    try:
        path.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return True, f"Patched {path.name} (backup: {backup.name})", backup
    except Exception as e:
        restore_file(backup, path)
        return False, f"Patch write failed ({e}), restored from backup", backup


# ── Syntax check ──────────────────────────────────────────────────────────────
def syntax_check(py_file: Path) -> tuple[bool, str]:
    r = subprocess.run(
        ["python3", "-m", "py_compile", str(py_file)],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        return True, "Syntax OK"
    return False, (r.stderr or r.stdout or "Unknown error").strip()


# ── Smoke tests ───────────────────────────────────────────────────────────────
def run_smoke_tests() -> list[dict]:
    """
    Run core Adwi smoke tests.
    Returns list of {test, ok, output}.
    """
    results = []

    ok, out = syntax_check(CLI_FILE)
    results.append({"test": "py_compile", "ok": ok, "output": out})
    if not ok:
        return results  # no point if compile fails

    env = {**os.environ, "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}

    def _run(cmds: list[str], label: str):
        inp = "\n".join(cmds) + "\n"
        try:
            r = subprocess.run(
                ["python3", str(CLI_FILE)],
                input=inp, capture_output=True, text=True, timeout=60, env=env,
            )
            out = (r.stdout + r.stderr)[:600]
            ok = r.returncode == 0 and "Traceback" not in out and "SyntaxError" not in out
            results.append({"test": label, "ok": ok, "output": out[:300]})
        except subprocess.TimeoutExpired:
            results.append({"test": label, "ok": False, "output": "timed out"})
        except Exception as e:
            results.append({"test": label, "ok": False, "output": str(e)})

    _run(["/model-status", "/exit"], "/model-status")
    _run(["/status", "/exit"],       "/status")
    _run(["/capabilities", "/exit"], "/capabilities")

    return results


# ── AI analysis for fix suggestions ──────────────────────────────────────────
def ollama_ask(prompt: str, model: str = "adwi:latest", max_tokens: int = 1500) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "You are Adwi's self-repair engine. You analyze Python errors in adwi_cli.py "
                "and propose exact text patches. Output ONLY the structured patch block requested. "
                "Never add explanations outside the block."
            )},
            {"role": "user", "content": "/no_think\n" + prompt},
        ],
        "stream": False, "think": False,
        "options": {"temperature": 0.1, "num_predict": max_tokens, "num_ctx": 16384},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.load(r)
            text = resp.get("message", {}).get("content", "")
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
            if "</think>" in text:
                text = text.split("</think>", 1)[-1]
            return text.strip()
    except Exception as e:
        return f"Ollama error: {e}"

def cloud_ask(prompt: str, secrets_path: Path) -> str:
    """Ask cloud model (Gemini via Open WebUI) if available."""
    try:
        env_file = secrets_path / "secrets.local.env"
        secrets = {}
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            secrets[k.strip()] = v.strip().strip('"').strip("'")

        base = secrets.get("OPENWEBUI_URL", "http://localhost:3000").rstrip("/")
        key  = secrets.get("OPENWEBUI_API_KEY", "")
        if not key or key.startswith("PASTE_"):
            return ""

        routing_text = ROUTING_FILE.read_text() if ROUTING_FILE.exists() else ""
        model = "models/gemini-2.5-flash"
        for line in routing_text.splitlines():
            if line.startswith("ADWI_CLOUD_MODEL="):
                model = line.split("=", 1)[1].strip().strip('"')
                break

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "You are an expert Python code reviewer. Analyze Python errors in adwi_cli.py "
                    "and output minimal, correct patches in the format requested. "
                    "Be precise — the patch will be applied automatically."
                )},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
        }).encode()
        req = urllib.request.Request(
            f"{base}/api/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


# ── Parse AI patch output ──────────────────────────────────────────────────────
PATCH_RE = re.compile(
    r"<<<PATCH_START>>>(.*?)<<<PATCH_END>>>",
    re.S,
)
OLD_RE  = re.compile(r"OLD:\s*```(?:python)?\s*(.*?)```", re.S)
NEW_RE  = re.compile(r"NEW:\s*```(?:python)?\s*(.*?)```", re.S)
FILE_RE = re.compile(r"FILE:\s*(.+)")

def parse_patch(ai_output: str) -> dict | None:
    """
    Parse AI patch output of the form:
        <<<PATCH_START>>>
        FILE: adwi_cli.py
        REASON: <text>
        OLD:
        ```python
        <old code>
        ```
        NEW:
        ```python
        <new code>
        ```
        <<<PATCH_END>>>
    Returns dict with keys: file, reason, old, new — or None if unparseable.
    """
    block_m = PATCH_RE.search(ai_output)
    if not block_m:
        return None
    block = block_m.group(1)
    file_m = FILE_RE.search(block)
    old_m  = OLD_RE.search(block)
    new_m  = NEW_RE.search(block)
    if not (old_m and new_m):
        return None
    return {
        "file":   (file_m.group(1).strip() if file_m else "adwi_cli.py"),
        "reason": re.search(r"REASON:\s*(.+)", block, re.S).group(1).split("\n")[0].strip() if re.search(r"REASON:", block) else "",
        "old":    old_m.group(1),
        "new":    new_m.group(1),
    }


# ── Build fix prompt ───────────────────────────────────────────────────────────
def build_fix_prompt(error_text: str, category: str, file_snippets: dict[str, str]) -> str:
    snippets = "\n\n".join(
        f"=== {name} ===\n{content}" for name, content in file_snippets.items()
    )
    return f"""Error to fix (category: {category}):
```
{error_text[:3000]}
```

Relevant file contents:
{snippets[:6000]}

Analyze the error and write a minimal patch to fix it.
Output ONLY the following block (nothing else):

<<<PATCH_START>>>
FILE: adwi_cli.py
REASON: <one sentence>
OLD:
```python
<exact text currently in the file — copy/paste exactly, no changes>
```
NEW:
```python
<corrected replacement text>
```
<<<PATCH_END>>>

Rules:
- OLD must be an exact substring of the file (copy character-for-character).
- NEW must be a correct Python replacement.
- Minimal change only — do not refactor unrelated code.
- If you cannot determine a safe fix, output: NO_FIX_POSSIBLE
"""


# ── Main fix loop ──────────────────────────────────────────────────────────────
def fix_error_loop(
    error_text: str,
    category: str,
    relevant_files: list[Path],
    secrets_path: Path,
    max_retries: int = 2,
) -> dict:
    """
    Attempt to fix an error. Returns result dict:
    {success, category, patch_applied, backup, steps, log_path, final_error}
    """
    REPAIR_DIR.mkdir(parents=True, exist_ok=True)
    steps = []
    patch_applied = ""
    backup_path = None

    # Gather file snippets
    snippets = {}
    for f in relevant_files:
        if f.exists() and is_safe_to_read(f):
            text = f.read_text(encoding="utf-8", errors="replace")
            snippets[f.name] = text[:8000]

    for attempt in range(1, max_retries + 2):
        steps.append(f"=== Attempt {attempt} ===")

        # Get AI analysis (prefer cloud, fall back to local)
        prompt = build_fix_prompt(error_text, category, snippets)
        steps.append("Asking AI for patch analysis...")
        ai_out = cloud_ask(prompt, secrets_path) or ollama_ask(prompt)

        if "NO_FIX_POSSIBLE" in ai_out or not ai_out or "Ollama error" in ai_out:
            steps.append(f"AI could not determine a fix: {ai_out[:200]}")
            break

        patch = parse_patch(ai_out)
        if not patch:
            steps.append(f"Could not parse AI output as patch (attempt {attempt})")
            steps.append(f"Raw output snippet: {ai_out[:400]}")
            if attempt > max_retries:
                break
            continue

        steps.append(f"Patch parsed. Reason: {patch.get('reason','')}")

        # Locate target file
        target = None
        fname = patch["file"].strip().split("/")[-1]
        for f in [CLI_FILE, ROUTING_FILE, ROOTS_FILE, CAPS_FILE]:
            if f.name == fname:
                target = f
                break
        if not target:
            steps.append(f"Target file not in patchable set: {fname}")
            break

        # Apply patch
        ok, msg, bk = apply_patch(target, patch["old"], patch["new"])
        steps.append(f"apply_patch: {msg}")
        if bk:
            backup_path = bk
        if not ok:
            steps.append(f"Patch could not apply — trying next attempt")
            if attempt > max_retries:
                break
            # Update snippet with current file state
            snippets[target.name] = target.read_text(encoding="utf-8")[:8000]
            error_text = f"Patch did not apply: {msg}\n\nOriginal error: {error_text}"
            continue

        patch_applied = msg

        # Test
        if target == CLI_FILE:
            syn_ok, syn_out = syntax_check(target)
            steps.append(f"Syntax check: {'PASS' if syn_ok else 'FAIL'} — {syn_out}")
            if syn_ok:
                log = write_repair_log(category, error_text, steps, True, patch_applied, str(backup_path))
                return {"success": True, "category": category, "patch_applied": patch_applied,
                        "backup": str(backup_path), "steps": steps, "log_path": log, "final_error": ""}
            else:
                # Syntax failed — restore and retry
                steps.append("Syntax failed after patch — restoring backup and retrying")
                if backup_path:
                    restore_file(backup_path, target)
                    steps.append("Backup restored")
                snippets[target.name] = target.read_text(encoding="utf-8")[:8000]
                error_text = f"After patch, syntax error: {syn_out}\n\nOriginal error: {error_text}"
                patch_applied = ""
        else:
            # Non-Python file — no syntax check, assume OK
            log = write_repair_log(category, error_text, steps, True, patch_applied, str(backup_path))
            return {"success": True, "category": category, "patch_applied": patch_applied,
                    "backup": str(backup_path), "steps": steps, "log_path": log, "final_error": ""}

    # All retries exhausted
    final_err = "Max retries exhausted" if attempt > max_retries else "AI could not determine fix"
    log = write_repair_log(category, error_text, steps, False, patch_applied, str(backup_path or ""))
    return {"success": False, "category": category, "patch_applied": patch_applied,
            "backup": str(backup_path or ""), "steps": steps, "log_path": log, "final_error": final_err}


# ── Repair log writer ─────────────────────────────────────────────────────────
def write_repair_log(
    category: str, error_text: str, steps: list[str],
    success: bool, patch_applied: str = "", backup: str = "",
) -> Path:
    REPAIR_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    status = "SUCCESS" if success else "FAILED"
    path = REPAIR_DIR / f"{stamp}-fix-error.md"
    path.write_text(
        f"# Adwi Repair Log — {status}\n\n"
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Category: {category}\n"
        f"Status: {status}\n\n"
        f"## Error\n```\n{error_text[:2000]}\n```\n\n"
        f"## Steps\n" + "\n".join(f"- {s}" for s in steps) + "\n\n"
        f"## Patch Applied\n{patch_applied or 'None'}\n\n"
        f"## Backup\n{backup or 'None'}\n",
        encoding="utf-8",
    )
    return path


# ── Capability scanner ─────────────────────────────────────────────────────────
def scan_implemented_commands(cli: Path = CLI_FILE) -> list[str]:
    """Extract all /cmd names from the handle() function."""
    text = cli.read_text(encoding="utf-8") if cli.exists() else ""
    cmds = set()
    for m in re.finditer(r'(?:line\s*==\s*|line\.startswith\()(["\'])(/[a-z][a-z0-9_-]*)', text):
        cmds.add(m.group(2))
    return sorted(cmds)

def update_capabilities_json(cli: Path = CLI_FILE, caps: Path = CAPS_FILE) -> int:
    """Add any implemented commands missing from capabilities.json. Returns count added."""
    implemented = scan_implemented_commands(cli)
    try:
        data = json.loads(caps.read_text(encoding="utf-8"))
    except Exception:
        data = {"version": "1.0", "capabilities": []}

    existing_cmds = set()
    for c in data.get("capabilities", []):
        cmd_str = c.get("command", "").split()[0]
        existing_cmds.add(cmd_str)

    added = 0
    for cmd in implemented:
        if cmd not in existing_cmds:
            data["capabilities"].append({
                "name":          cmd.lstrip("/").replace("-", " ").title(),
                "command":       cmd,
                "description":   f"Adwi command {cmd}",
                "risk":          "low",
                "files_touched": [],
                "uses_secrets":  False,
                "logs":          "notes/adwi-action-logs",
                "test_command":  "/test-adwi",
            })
            added += 1

    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    caps.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return added


# ── Allowlisted safe commands ─────────────────────────────────────────────────
SAFE_CMDS = {
    "status-ai":                      ["status-ai"],
    "adwi-self-heal":                 ["adwi-self-heal"],
    "sync-openwebui-knowledge":       ["sync-openwebui-knowledge"],
    "status-openwebui-knowledge-watcher": ["status-openwebui-knowledge-watcher"],
    "adwi-secrets-status":            ["adwi-secrets-status"],
    "index-ai-notes":                 ["index-ai-notes"],
    "ask-ai-profile":                 ["ask-ai-profile"],
    "summarize-url":                  None,  # requires arg
    "summarize-youtube":              None,  # requires arg
    "save-youtube-summary":           None,  # requires arg
    "py-compile":                     ["python3", "-m", "py_compile", str(CLI_FILE)],
    "mcp-status":                     ["bash", str(BIN / "mcp-status")],
}

def run_safe_cmd(action: str, timeout: int = 120) -> tuple[bool, str]:
    """
    Run an allowlisted command. Returns (ok, output).
    action is the key or 'key arg' form.
    """
    parts = action.strip().split(None, 1)
    key = parts[0]
    arg = parts[1] if len(parts) > 1 else None

    if key not in SAFE_CMDS:
        return False, f"'{key}' is not in the safe command allowlist. Use /run-safe without args to list allowed actions."

    cmd_template = SAFE_CMDS[key]
    if cmd_template is None:
        if not arg:
            return False, f"'{key}' requires an argument, e.g.: /run-safe {key} <url>"
        cmd = [key, arg]
    else:
        cmd = list(cmd_template)

    env = {**os.environ, "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        out = ((r.stdout or "") + ("\n[stderr]\n" + r.stderr if r.stderr else "")).strip()
        return r.returncode == 0, out[:3000]
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout}s"
    except Exception as e:
        return False, str(e)
