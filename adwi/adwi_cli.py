#!/usr/bin/env python3
"""
Adwi — Suneel's Local AI Operating Assistant
Natural language interface: just talk, Adwi figures out what to do.
Models: adwi:latest (30.5B reasoning) + qwen3:0.6b (instant NLU) + minicpm-v (local vision)
Workspace: /Users/MAC/SuneelWorkSpace
"""
import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.styles import Style
    PROMPT_TOOLKIT = True
except ImportError:
    PROMPT_TOOLKIT = False

# ── Paths ─────────────────────────────────────────────────────────────────────
HOME          = Path.home()
BASE          = HOME / "SuneelWorkSpace"
BIN           = BASE / "bin"
NOTES         = BASE / "notes"
ADWI_DIR      = BASE / "adwi"
SECRETS_DIR   = BASE / "secrets"
KNOWLEDGE_DIR = BASE / "open-webui-knowledge-upload"
LOG_DIR       = NOTES / "adwi-action-logs"
ROOTS_FILE    = ADWI_DIR / "allowed-read-roots.txt"
ROUTING_FILE  = ADWI_DIR / "model-routing.env"
CAPS_FILE     = ADWI_DIR / "capabilities.json"
JOURNAL_FILE  = NOTES / "adwi-learning-journal.md"
MISTAKES_FILE = NOTES / "adwi-mistakes-and-fixes.md"
ROADMAP_FILE  = NOTES / "adwi-capability-roadmap.md"
HISTORY_FILE  = HOME / ".adwi_history"
RAG_DB_DIR    = ADWI_DIR / "rag-db"
IMG_GEN_DIR   = NOTES / "generated-images"
MCP_CONFIG    = HOME / ".config" / "mcp" / "servers.json"
CLI_FILE      = ADWI_DIR / "adwi_cli.py"     # self-reference for repair commands
TRACE_DIR     = NOTES / "adwi-trace-logs"   # activity trace logs
OBSIDIAN_VAULT   = BASE / "obsidian-vault"
OBSIDIAN_BRIDGE  = "http://127.0.0.1:5056"
SEARXNG_URL      = "http://127.0.0.1:8888"
CONFIG_ENV       = BASE / "config" / ".env"

# Model identifiers
MODEL_MAIN    = "adwi:latest"          # 30.5B MoE — reasoning, long context
MODEL_FAST    = "qwen3:0.6b"           # 522MB — instant NLU classification
MODEL_VISION  = "minicpm-v:latest"     # 5.5GB — local vision
MODEL_EMBED   = "nomic-embed-text"     # embeddings
CLOUD_DEFAULT = "models/gemini-2.5-flash"

# Paths that are NEVER readable even with full-home access
HARD_BLOCKED = [
    BASE / "secrets",
    HOME / ".ssh",
    HOME / ".gnupg",
    HOME / "Library" / "Keychains",
    HOME / "Library" / "Passwords",
    HOME / ".aws",
    HOME / ".config" / "gcloud",
    HOME / ".kube",
    HOME / ".npmrc",
    HOME / ".netrc",
    Path("/etc"),
    Path("/private"),
    Path("/System"),
    Path("/usr/lib"),
]

IMAGE_EXTS = {".jpg",".jpeg",".png",".gif",".webp",".bmp",".tiff",".tif",".heic",".heif"}
TEXT_EXTS  = {".md",".txt",".json",".yml",".yaml",".py",".sh",".js",".ts",".env",".toml",".cfg",".ini",".xml",".csv",".log",".zsh",".bash"}

for d in [LOG_DIR, NOTES, KNOWLEDGE_DIR, ADWI_DIR, OBSIDIAN_VAULT]:
    d.mkdir(parents=True, exist_ok=True)

# Load optional config/.env (non-fatal — keys override module-level defaults)
def _load_config_env():
    if not CONFIG_ENV.exists():
        return
    try:
        for raw in CONFIG_ENV.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k and v:
                os.environ.setdefault(k, v)
    except Exception:
        pass

_load_config_env()
# Allow runtime override of service URLs via env
SEARXNG_URL      = os.environ.get("SEARXNG_URL",         SEARXNG_URL)
OBSIDIAN_BRIDGE  = os.environ.get("OBSIDIAN_BRIDGE_URL",  OBSIDIAN_BRIDGE)
# External API keys — loaded from config/.env
TAVILY_API_KEY    = os.environ.get("TAVILY_API_KEY",    "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
EXA_API_KEY       = os.environ.get("EXA_API_KEY",       "")

if not ROUTING_FILE.exists():
    ROUTING_FILE.write_text(
        f'ADWI_CHAT_BACKEND="openwebui"\nADWI_CLOUD_MODEL="{CLOUD_DEFAULT}"\nADWI_LOCAL_MODEL="{MODEL_MAIN}"\n',
        encoding="utf-8",
    )

# ── ANSI colors ───────────────────────────────────────────────────────────────
RESET ="\033[0m"; BOLD="\033[1m"; DIM="\033[2m"
CYAN="\033[36m";  GREEN="\033[32m"; YELLOW="\033[33m"
PURPLE="\033[35m"; WHITE="\033[97m"; GRAY="\033[90m"; RED="\033[31m"

def cprint(t, c="", bold=False): print(f"{BOLD if bold else ''}{c}{t}{RESET}")
def adwi_say(t):                  print(f"\n{BOLD}{PURPLE}Adwi{RESET}  {t}\n")
def adwi_head(t):                 cprint(f"\n  {t}", CYAN, bold=True)

# ── Activity Stream + Trace Log ───────────────────────────────────────────────
# Real-time progress display styled like Copilot/Claude Code activity panels.
# Each action writes a structured trace to notes/adwi-trace-logs/.

_TRACE: dict = {}   # accumulates steps for the current action; reset per action

_STEP_ICONS = {
    "inspecting": "📂", "running": "▶️ ", "testing": "🧪",
    "retrying":   "🔁", "patching": "🔧", "syncing":  "🔄",
    "reading":    "📖", "writing":  "✏️ ", "indexing": "🗂️ ",
    "committing": "📦", "pushing":  "🚀", "scanning": "🔍",
    "classifying":"🏷️ ", "staging":  "📋", "verifying":"🔎",
}

def activity_start(user_goal: str, selected_action: str) -> None:
    """Begin a new activity: print intent header and reset trace accumulator.
    Idempotent — if a trace is already active (set by dispatch_natural before
    calling the command), skip the header print to avoid duplication."""
    global _TRACE
    already_active = bool(_TRACE)
    _TRACE = {
        "ts":             datetime.now().strftime("%Y%m%d-%H%M%S"),
        "goal":           _TRACE.get("goal", user_goal) if already_active else user_goal,
        "action":         _TRACE.get("action", selected_action) if already_active else selected_action,
        "steps":          _TRACE.get("steps", []) if already_active else [],
        "files_inspected":_TRACE.get("files_inspected", []) if already_active else [],
        "files_changed":  _TRACE.get("files_changed", []) if already_active else [],
        "commands":       _TRACE.get("commands", []) if already_active else [],
        "result":         "",
        "error":          "",
        "logs":           [],
    }
    if not already_active:
        cprint(f"\n  🧭 Understanding: {user_goal[:120]}", CYAN)
        cprint(f"  🛠️  Action: {selected_action}", CYAN)

def activity_step(label: str, message: str) -> None:
    """Print a labelled progress step and record it."""
    icon = _STEP_ICONS.get(label.lower().split()[0], "  ·")
    cprint(f"  {icon} {label}: {message}", GRAY)
    if _TRACE:
        _TRACE["steps"].append(f"{label}: {message}")

def activity_running(command_or_action: str) -> None:
    cprint(f"  ▶️  Running: {command_or_action}", GRAY)
    if _TRACE:
        _TRACE["commands"].append(command_or_action)
        _TRACE["steps"].append(f"Running: {command_or_action}")

def activity_inspecting(path: str) -> None:
    cprint(f"  📂 Inspecting: {path}", GRAY)
    if _TRACE:
        _TRACE["files_inspected"].append(path)
        _TRACE["steps"].append(f"Inspecting: {path}")

def activity_changed(path: str) -> None:
    if _TRACE:
        _TRACE["files_changed"].append(path)

def activity_success(summary: str, log_path=None) -> None:
    cprint(f"  ✅ Done: {summary}", GREEN)
    if log_path:
        cprint(f"  📝 Log: {log_path}", GRAY)
    if _TRACE:
        _TRACE["result"] = summary
        if log_path:
            _TRACE["logs"].append(str(log_path))

def activity_warning(summary: str) -> None:
    cprint(f"  ⚠️  Issue: {summary}", YELLOW)
    if _TRACE:
        _TRACE["steps"].append(f"⚠ {summary}")

def activity_error(summary: str, log_path=None) -> None:
    cprint(f"  ❌ Error: {summary}", RED)
    if log_path:
        cprint(f"  📝 Log: {log_path}", GRAY)
    if _TRACE:
        _TRACE["error"] = summary
        if log_path:
            _TRACE["logs"].append(str(log_path))

def activity_done(summary: str, log_path=None) -> None:
    """Final success step — prints ✅ and flushes trace to disk."""
    activity_success(summary, log_path)
    _flush_trace()

def _flush_trace() -> "Path | None":
    """Write the current _TRACE accumulator to notes/adwi-trace-logs/ and reset."""
    global _TRACE
    if not _TRACE:
        return None
    t = dict(_TRACE)
    _TRACE = {}
    try:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", t["action"].lower())[:28].strip("-")
        path = TRACE_DIR / f"{t['ts']}-{slug}-trace.md"

        steps_md  = "\n".join(f"{i+1}. {s}" for i, s in enumerate(t["steps"])) or "(none)"
        inspected = "\n".join(f"- {f}" for f in t["files_inspected"])  or "- none"
        changed   = "\n".join(f"- {f}" for f in t["files_changed"])    or "- none"
        commands  = "\n".join(f"- `{c}`" for c in t["commands"])       or "- none"
        logs      = "\n".join(f"- {l}" for l in t["logs"])             or "- none"

        path.write_text(
            f"# Adwi Activity Trace\n\n"
            f"Generated: {t['ts']}\n\n"
            f"## User Request\n\n{t['goal']}\n\n"
            f"## Selected Action\n\n{t['action']}\n\n"
            f"## Activity Steps\n\n{steps_md}\n\n"
            f"## Files Inspected\n\n{inspected}\n\n"
            f"## Files Changed\n\n{changed}\n\n"
            f"## Commands / Built-in Actions\n\n{commands}\n\n"
            f"## Result\n\n{t['result'] or '(no result recorded)'}\n\n"
            f"## Error\n\n{t['error'] or 'none'}\n\n"
            f"## Log Links\n\n{logs}\n\n"
            f"## Redaction Note\n\n"
            f"All API keys, tokens, JWTs, and bearer tokens are redacted from this trace.\n",
            encoding="utf-8",
        )
        return path
    except Exception:
        return None

def cmd_trace_log(n: int = 0) -> None:
    """Show the most recent activity trace log (or the nth most recent)."""
    adwi_head("Activity trace log")
    if not TRACE_DIR.exists() or not list(TRACE_DIR.glob("*-trace.md")):
        cprint("  No trace logs yet — they are created after each action.", GRAY)
        return
    logs = sorted(TRACE_DIR.glob("*-trace.md"))
    try:
        target = logs[-(n + 1)]
    except IndexError:
        target = logs[-1]
    cprint(f"  {GRAY}{target.name}{RESET}", "")
    cprint("", "")
    for line in target.read_text(encoding="utf-8").splitlines()[:80]:
        cprint(f"  {line}", "")
    total = len(target.read_text(encoding="utf-8").splitlines())
    if total > 80:
        cprint(f"\n  {GRAY}... ({total-80} more lines){RESET}", "")
    cprint(f"\n  All traces: {TRACE_DIR}", GRAY)

# ── Safety ────────────────────────────────────────────────────────────────────
def redact(t):
    t = str(t or "")
    t = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "sk-REDACTED", t)
    t = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "JWT-REDACTED", t)
    t = re.sub(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9._-]+", r"\1REDACTED", t, flags=re.I)
    t = re.sub(r"(OPENWEBUI_API_KEY=).*", r'\1REDACTED', t)
    return t

DENY_PAT = re.compile(
    r"(^|[ ;|&])(rm\s+-rf|rmdir|dd\s+|mkfs|shutdown|reboot|sudo\s|killall)([ ;|&]|$)"
    r"|payment|bank transfer|crypto wallet|wire transfer|venmo|paypal|cashapp|credit.card",
    re.I,
)
def denied(t): return bool(DENY_PAT.search(str(t or "")))

def is_hard_blocked(path: Path) -> bool:
    try:
        p = path.resolve()
        return any(p == b.resolve() or b.resolve() in p.parents for b in HARD_BLOCKED)
    except Exception:
        return True

def safe_to_read(path) -> tuple[bool, str]:
    """Returns (ok, reason). Checks roots, hard blocks, secrets."""
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return False, "invalid path"
    if is_hard_blocked(p):
        return False, "blocked (sensitive system/credential path)"
    if SECRETS_DIR.resolve() in [p, *p.parents]:
        return False, "blocked (secrets vault)"
    roots_list = [Path(x).expanduser().resolve()
                  for x in ROOTS_FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
    if any(p == r or r in p.parents for r in roots_list):
        return True, ""
    return False, "outside allowed roots (add with: /add-root <path>)"

# ── URL / content detection ───────────────────────────────────────────────────
YT_RE  = re.compile(r"(https?://)?(www\.)?(youtube\.com/watch\?[^\s]+|youtu\.be/[^\s]+|youtube\.com/shorts/[^\s]+|youtube\.com/live/[^\s]+)", re.I)
URL_RE = re.compile(r"https?://[^\s]+", re.I)

# Regex pre-filters — catch common phrases the tiny model misclassifies
_REGEX_INTENTS = [
    # Disk / space — must come before file_list
    (re.compile(r"(biggest|largest|heaviest|most space|taking up|using up|eating up).{0,40}(folder|file|directory|space|disk|storage)", re.I), "disk_usage"),
    (re.compile(r"(disk|storage|space).{0,40}(usage|breakdown|breakdown|overview|used|free|full)", re.I), "disk_usage"),
    (re.compile(r"(what|what.s|how much).{0,30}(space|room|storage|disk)", re.I),  "disk_usage"),
    (re.compile(r"(free up|clean up).{0,20}(space|disk|storage|room)", re.I),       "cleanup"),
    # Large files
    (re.compile(r"(big(gest)?|large(st)?|heavy|huge|files? (over|bigger|larger|more than))", re.I), "large_files"),
    # Old files
    (re.compile(r"(old|haven.t (used|opened|touched)|stale|unused|not (used|opened|accessed)).{0,30}(file|folder|doc)", re.I), "old_files"),
    (re.compile(r"files?.{0,20}(not|never).{0,20}(used|opened).{0,20}(year|month|day)", re.I), "old_files"),
    # Duplicates
    (re.compile(r"(duplicate|identical|same file|copy|copies|redundant)", re.I),    "duplicates"),
    # Organize
    (re.compile(r"(organiz|tidy|restructure|better structure|sort out|clean up).{0,30}(folder|file|download|desktop|document)", re.I), "organize"),
    # Cleanup suggestions
    (re.compile(r"(what|which).{0,20}(can|should|could|to).{0,20}(delete|remove|trash|clear|get rid)", re.I), "cleanup"),
    (re.compile(r"(safe to delete|safely delete|safely remove)", re.I),             "cleanup"),
    # Status
    (re.compile(r"(is|are).{0,30}(running|working|up|down|online|healthy|alive)", re.I), "status"),
    (re.compile(r"(check|verify).{0,20}(setup|stack|services|system)", re.I),       "status"),
    # Self-heal
    (re.compile(r"(fix|repair|restart|broken|not working|crashed|down).{0,20}(setup|stack|service|ollama|docker)", re.I), "self_heal"),
    # What next
    (re.compile(r"(what|what.s).{0,20}(next|build|improve|add|create).{0,20}(adwi|setup|ai|local)", re.I), "what_next"),
    (re.compile(r"(suggest|recommend).{0,20}(next|improvement|feature|capability)", re.I), "what_next"),
    # RAG / knowledge search
    (re.compile(r"(search|find|look up|recall|what do i know).{0,30}(my notes|my knowledge|local knowledge|knowledge base|from notes)", re.I), "rag_search"),
    (re.compile(r"(in my notes|from my notes|check my notes).{0,30}(about|for|on)", re.I), "rag_search"),
    # Web search (SearXNG)
    (re.compile(r"(search the web|web search|google|search online|look up online|find online|search internet).{0,50}", re.I), "web_search"),
    (re.compile(r"(what('s| is) (the latest|new in|current).{0,30}(release|version|update|news|changelog))", re.I), "web_search"),
    # Obsidian vault
    (re.compile(r"(obsidian|vault|my notes?).{0,20}(search|find|look up|what do i have)", re.I), "obsidian_search"),
    (re.compile(r"(open|read|show).{0,10}(obsidian|vault|note).{0,30}", re.I), "obsidian_search"),
    # Browse / fetch URL
    (re.compile(r"(browse|visit|open|fetch|go to|check out|navigate to).{0,15}(https?://|website|site|webpage|url|\.(com|io|org|dev|net))", re.I), "browse"),
    # GitHub repo visibility — must come BEFORE git_status and github_connected
    (re.compile(r"(make|set|change|convert).{0,20}(git.?repo|repo|repository).{0,20}(public|private|open source)", re.I), "github_visibility"),
    (re.compile(r"(make|set).{0,15}(public|private).{0,15}(repo|repository|github)", re.I), "github_visibility"),
    (re.compile(r"(repo|repository).{0,20}(visibility|public|private)", re.I), "github_visibility"),
    # GitHub connectivity — must come BEFORE git_status
    (re.compile(r"(is|are).{0,20}(github|git hub).{0,20}(connected|linked|set up|configured|working|authenticated|logged in)", re.I), "github_connected"),
    (re.compile(r"(is adwi|adwi).{0,20}(connected|linked).{0,20}(github|git)", re.I), "github_connected"),
    (re.compile(r"(github|git hub).{0,20}(account|auth|login|connection|access)", re.I), "github_connected"),
    (re.compile(r"(connected to|link(ed)? to|set up).{0,20}(github|git hub)", re.I), "github_connected"),
    # Git
    (re.compile(r"git\s+(status|diff|log|show|repos?)\b", re.I), "git_status"),
    (re.compile(r"(what (changed|committed)|show commits|latest commit|my repos?)\b", re.I), "git_status"),
    # Image generation
    (re.compile(r"(generate|create|draw|make|design).{0,20}(an? )?(image|picture|photo|illustration|artwork)", re.I), "generate_image"),
    # Code execution
    (re.compile(r"(run|execute|test).{0,15}(this |the )?(python|code|script)\b", re.I), "run_code"),
    # Benchmark
    (re.compile(r"(benchmark|speed.?test|how fast|tokens? per second).{0,20}(adwi|model|local|ollama)\b", re.I), "benchmark"),
    # Gmail
    (re.compile(r"(check|show|read|open|get|fetch|look at).{0,20}(my )?(email|gmail|inbox|mail)\b", re.I), "gmail"),
    (re.compile(r"(any (new|unread) )?emails?\b", re.I), "gmail"),
    (re.compile(r"gmail\b", re.I), "gmail"),
    # Memory ledger
    (re.compile(r"(scan|index|update|build).{0,20}(my )?(memory|memories|ledger|context)", re.I), "memory_scan"),
    (re.compile(r"(remember|recall|what do you know about|memory).{0,30}\?", re.I), "memory_recall"),
    (re.compile(r"memory (stats|status|ledger|database|db)\b", re.I), "memory_stats"),
    # Semantic router
    (re.compile(r"route (this|the|my)?\s*(query|question|request|command)\b", re.I), "route"),
    (re.compile(r"which tool (should|would|to) (handle|use for|run)\b", re.I), "route"),
]

def _regex_prefilter(text: str):
    """Fast regex pre-classification before calling the small model."""
    for pattern, intent in _REGEX_INTENTS:
        if pattern.search(text):
            return intent
    return None

def extract_youtube_url(text):
    m = YT_RE.search(text)
    if not m: return None
    u = m.group(0)
    return u if u.startswith("http") else "https://" + u

def extract_image_path(text):
    """Detect if text IS an image file path."""
    t = text.strip().strip("'\"")
    p = Path(t).expanduser()
    if p.suffix.lower() in IMAGE_EXTS and (p.exists() or p.is_absolute()):
        return str(p)
    return None

# ── Config ────────────────────────────────────────────────────────────────────
def load_env(path):
    d = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip().strip('"').strip("'")
    return d

def load_routing():
    d = {"ADWI_CHAT_BACKEND":"openwebui","ADWI_CLOUD_MODEL":CLOUD_DEFAULT,"ADWI_LOCAL_MODEL":MODEL_MAIN}
    if ROUTING_FILE.exists(): d.update(load_env(ROUTING_FILE))
    return d

def save_routing(d):
    ROUTING_FILE.write_text(
        f'ADWI_CHAT_BACKEND="{d.get("ADWI_CHAT_BACKEND","openwebui")}"\n'
        f'ADWI_CLOUD_MODEL="{d.get("ADWI_CLOUD_MODEL",CLOUD_DEFAULT)}"\n'
        f'ADWI_LOCAL_MODEL="{d.get("ADWI_LOCAL_MODEL",MODEL_MAIN)}"\n',
        encoding="utf-8",
    )

def load_secrets():
    f = BASE / "secrets" / "secrets.local.env"
    return load_env(f) if f.exists() else {}

# ── Logging ───────────────────────────────────────────────────────────────────
def log_action(name, output):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    f = LOG_DIR / f"{stamp}-{name}.md"
    f.write_text(f"# Adwi Log: {name}\n\nGenerated: {datetime.now()}\n\n```\n{redact(output)}\n```\n", encoding="utf-8")
    return f

def log_journal(entry: str):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n## {stamp}\n\n{entry.strip()}\n\n---\n"
    with JOURNAL_FILE.open("a", encoding="utf-8") as f: f.write(block)
    try: (KNOWLEDGE_DIR/"adwi-learning-journal.md").write_text(JOURNAL_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception: pass

def log_mistake(asked, tried, error, fix, rule):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n## {stamp}\n\n**Asked:** {asked}\n\n**Tried:** {tried}\n\n**Error:** {error}\n\n**Fix:** {fix}\n\n**Rule:** {rule}\n\n---\n"
    with MISTAKES_FILE.open("a", encoding="utf-8") as f: f.write(block)
    try: (KNOWLEDGE_DIR/"adwi-mistakes-and-fixes.md").write_text(MISTAKES_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception: pass

# ── Shell runner ──────────────────────────────────────────────────────────────
def run_cmd(name, cmd, timeout=900, quiet=False, input_data=None):
    activity_running(name)
    env = {**os.environ, "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                          input=input_data)
        out = redact(((r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")).strip())
        lp = log_action(name, out)
        if not quiet:
            # Show first 20 meaningful lines + summary line
            lines = [l for l in out.splitlines() if l.strip()]
            preview = "\n".join(lines[:20])
            print(preview)
            if len(lines) > 20:
                cprint(f"  {GRAY}... ({len(lines)-20} more lines — see log){RESET}", "")
            activity_success(f"{name} complete", lp)
        return out
    except Exception as e:
        out = f"ERROR: {e}"
        if not quiet:
            activity_error(str(e))
        return out

def run_shell(cmd_str, timeout=60) -> str:
    """Run a shell command string, return stdout."""
    env = {**os.environ, "PATH": f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:{BIN}"}
    try:
        r = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=timeout, env=env)
        return (r.stdout or "").strip()
    except Exception as e:
        return f"ERROR: {e}"

# ── AI Model calls ────────────────────────────────────────────────────────────

def _ollama_chat(model, messages, stream=False, max_tokens=None, temperature=0.25, ctx=131072):
    opts = {"temperature": temperature, "num_ctx": ctx}
    if max_tokens: opts["num_predict"] = max_tokens
    payload = {"model": model, "messages": messages, "stream": stream, "think": False, "options": opts}
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return req

def strip_think(t):
    t = str(t or "")
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S | re.I)
    if "</think>" in t: t = t.split("</think>", 1)[-1]
    return t.strip()

# ── Intent classification (qwen3:0.6b — instant) ─────────────────────────────
INTENT_SCHEMA = """Classify the user message. Return ONLY valid JSON, nothing else.

Intents:
disk_usage    - storage overview, what's using space, how full is disk
large_files   - find files bigger than X, what are the biggest files
old_files     - files not opened/used in a long time, stale files
duplicates    - find duplicate or identical files, copies
organize      - suggest how to organize a folder or restructure files
cleanup       - what can I delete, safe to remove, declutter, free space
file_read     - show/read/open a specific file (extract path into target)
file_search   - search for files by name or content (extract query)
file_list     - list what's in a folder (extract path into target)
youtube       - YouTube URL or video summary request
image         - analyze image, screenshot, photo (extract path into target)
status        - check health, is everything running, system check
self_heal     - fix, repair, restart, something broken
what_next     - roadmap, what to build next, suggestions for improvement
daily_improve - daily routine, daily improvement run
sync          - sync knowledge, sync files to Open WebUI
model_status  - which model is active, model routing info
use_local     - switch to local model, go offline
use_cloud     - switch to cloud model
capabilities  - what can you do, list capabilities
rag_search    - search my notes, what do I know about X, find in local knowledge
browse        - browse/fetch a website URL (not YouTube)
git_status    - check git status, commits, repo changes
generate_image - generate/draw/create an image with AI
run_code      - run/execute Python code or a script
benchmark     - benchmark Adwi speed, test performance, tokens per second
gmail         - check email, show inbox, read gmail, any new emails
chat          - anything else: questions, conversation, explanations

JSON: {"intent":"<intent>","target":"<path, URL, or query if mentioned, else null>"}
Examples:
user: "what is eating my disk space?" -> {"intent":"disk_usage","target":null}
user: "find files bigger than 1GB in Downloads" -> {"intent":"large_files","target":"/Users/MAC/Downloads"}
user: "read my notes/profile.md" -> {"intent":"file_read","target":"/Users/MAC/SuneelWorkSpace/notes/suneel-local-ai-profile.md"}
user: "https://youtu.be/abc" -> {"intent":"youtube","target":"https://youtu.be/abc"}"""

def classify_intent(text: str) -> dict:
    """Classify user intent: regex pre-filter → qwen3:0.6b model fallback."""
    # 1. Instant checks (no model needed)
    yt = extract_youtube_url(text)
    if yt: return {"intent": "youtube", "target": yt}
    img = extract_image_path(text)
    if img: return {"intent": "image", "target": img}

    # 2. Regex pre-filter — fast, handles common phrases the tiny model misses
    pre = _regex_prefilter(text)
    if pre: return {"intent": pre, "target": None}

    msgs = [
        {"role": "system", "content": INTENT_SCHEMA},
        {"role": "user",   "content": text},
    ]
    req = _ollama_chat(MODEL_FAST, msgs, stream=False, max_tokens=60, temperature=0, ctx=512)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.load(resp).get("message", {}).get("content", "{}")
        raw = strip_think(raw)
        # Extract JSON from response (model might wrap it)
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            result = json.loads(m.group(0))
            # Resolve relative paths
            if result.get("target") and not result["target"].startswith("/") and not result["target"].startswith("http"):
                guessed = Path(HOME / result["target"]).expanduser()
                if guessed.exists(): result["target"] = str(guessed)
            return result
    except Exception:
        pass
    return {"intent": "chat", "target": None}

# ── Local streaming (adwi:latest) ─────────────────────────────────────────────
def stream_local(prompt, system=None, model=None):
    m = model or load_routing().get("ADWI_LOCAL_MODEL", MODEL_MAIN)
    sys_msg = system or (
        "You are Adwi, Suneel's local AI assistant running on his M4 Max Mac (131K context, 64GB RAM). "
        "Your real capabilities include: web browsing (/browse), Gmail read-only (/gmail), "
        "git repo inspection (/git), semantic notes search (/rag), code execution (/run-python), "
        "image analysis (minicpm-v), YouTube summarization, disk analysis, and SearXNG web search. "
        "You DO have internet access through these tools. "
        "You are connected to GitHub via the gh CLI tool. "
        "Be practical, concise, warm. Never reveal secrets or do destructive/financial actions."
    )
    msgs = [{"role":"system","content":sys_msg}, {"role":"user","content":"/no_think\n"+prompt}]
    req  = _ollama_chat(m, msgs, stream=True)
    print(f"\n{BOLD}{PURPLE}Adwi{RESET}  ", end="", flush=True)
    full, in_think = "", False
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line: continue
                try: chunk = json.loads(line)
                except: continue
                tok = chunk.get("message", {}).get("content", "")
                full += tok
                if "<think>" in tok: in_think = True
                if not in_think: print(tok, end="", flush=True)
                if in_think and "</think>" in tok: in_think = False
                if chunk.get("done"): break
    except Exception as e:
        print(f"\n{YELLOW}  Ollama unreachable. Run: start-ai{RESET}")
        return ""
    print()
    return strip_think(redact(full))

def quick_local(prompt, model=MODEL_FAST) -> str:
    """Non-streaming, uses fast model for quick factual answers."""
    msgs = [
        {"role":"system","content":"You are Adwi, a helpful AI assistant. Be concise and direct."},
        {"role":"user","content":"/no_think\n"+prompt},
    ]
    req = _ollama_chat(model, msgs, stream=False, max_tokens=300, ctx=2048)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return strip_think(json.load(resp).get("message",{}).get("content",""))
    except Exception as e:
        return f"ERROR: {e}"

# ── Cloud (Open WebUI / Gemini) ───────────────────────────────────────────────
def call_cloud(prompt, messages=None, model=None) -> str:
    s = load_secrets()
    base = s.get("OPENWEBUI_URL","http://localhost:3000").rstrip("/")
    key  = s.get("OPENWEBUI_API_KEY","")
    if not key or key.startswith("PASTE_"):
        return "Cloud unavailable — OPENWEBUI_API_KEY not set. Falling back to local model."
    m = model or load_routing().get("ADWI_CLOUD_MODEL", CLOUD_DEFAULT)
    if not messages:
        messages = [
            {"role":"system","content":(
                "You are Adwi, Suneel's local AI operating assistant on his M4 Max Mac. "
                "Be direct, practical, beginner-friendly. Never reveal secrets or perform destructive/financial actions."
            )},
            {"role":"user","content":prompt},
        ]
    payload = {"model":m,"messages":messages,"stream":False}
    req = urllib.request.Request(
        base+"/api/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return strip_think(redact(data.get("choices",[{}])[0].get("message",{}).get("content",""))) or "(no response)"
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception: pass
        if e.code == 400:
            # Prompt may be too long or flagged — retry with truncated prompt then fall back
            short = prompt[:3000] + "\n\n[Note: prompt was truncated to fit cloud limits]" if len(prompt) > 3000 else None
            if short and short != prompt:
                cprint(f"  {YELLOW}Cloud 400 — prompt truncated, retrying…{RESET}", "")
                return call_cloud(short, model=model)
            cprint(f"  {YELLOW}Cloud 400 — falling back to local model{RESET}", "")
            stream_local(prompt)
            return ""  # already printed by stream_local — don't double-print via adwi_say
        if e.code == 401:
            return "Cloud error: API key rejected (401). Run: adwi-secrets-edit to update OPENWEBUI_API_KEY."
        if e.code == 429:
            return "Cloud error: rate limited (429). Try again in a minute, or switch to local: /use-local"
        return f"Cloud error HTTP {e.code}: {e.reason}. Detail: {body}"
    except Exception as e:
        return f"Cloud error: {e}"

def ask_adwi(prompt):
    """Main entry point for chat — routes to cloud or local based on setting."""
    r = load_routing()
    if r.get("ADWI_CHAT_BACKEND","openwebui") == "openwebui":
        result = call_cloud(prompt)
        if result:   # empty string means stream_local already printed (400 fallback)
            adwi_say(result)
    else:
        stream_local(prompt)

# ── Vision analysis (local minicpm-v, cloud fallback) ────────────────────────
def analyze_image(path_str: str, save=False):
    p = Path(path_str).expanduser().resolve()
    ok, reason = safe_to_read(p)
    if not ok:
        adwi_say(f"Cannot read image: {reason}"); return
    if not p.exists():
        adwi_say(f"File not found: `{p}`"); return
    if p.suffix.lower() not in IMAGE_EXTS:
        adwi_say(f"Not a supported image format. Supported: {', '.join(sorted(IMAGE_EXTS))}"); return

    mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    b64  = base64.b64encode(p.read_bytes()).decode()
    cprint(f"\n  Analyzing {p.name} with local vision model...", CYAN)

    # Try local minicpm-v first
    msgs = [{"role":"user","content":[
        {"type":"text","text":(
            "Analyze this image carefully:\n"
            "1. Describe everything you see in detail\n"
            "2. Extract ALL text visible (OCR)\n"
            "3. Identify: code, terminal output, UI, diagrams, charts, errors\n"
            "4. Note anything important, actionable, or unusual\n"
            "5. If relevant to a developer/AI setup, suggest next steps"
        )},
        {"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}},
    ]}]
    payload = {"model":MODEL_VISION,"messages":msgs,"stream":False,"options":{"temperature":0.1}}
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json"},
    )
    result = ""
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.load(resp).get("message",{}).get("content","")
        cprint(f"  (local vision — no cloud used)", GRAY)
    except Exception:
        cprint("  Local vision unavailable, falling back to Gemini...", YELLOW)
        result = call_cloud("", messages=[
            {"role":"system","content":"You are a vision AI. Analyze images thoroughly."},
            {"role":"user","content":[
                {"type":"text","text":"Describe this image in detail. Extract all text. Note code, UI, errors."},
                {"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}},
            ]},
        ])

    adwi_say(result)
    if save:
        stamp   = datetime.now().strftime("%Y%m%d-%H%M%S")
        outfile = KNOWLEDGE_DIR / f"{stamp}-image-{p.stem}.md"
        outfile.write_text(f"# Image Analysis: {p.name}\n\nFile: `{p}`\nAnalyzed: {datetime.now()}\n\n---\n\n{result}\n", encoding="utf-8")
        cprint(f"  Saved to knowledge: {outfile.name}", GREEN)
    log_action("image", f"File: {p}\n\n{result}")

# ── Disk & filesystem analysis ────────────────────────────────────────────────

def _safe_path_for_scan(target=None) -> Path:
    """Resolve a scan target to a safe path, defaulting to home."""
    if target:
        p = Path(target).expanduser().resolve()
        ok, reason = safe_to_read(p)
        if not ok:
            cprint(f"  Blocked: {reason}", YELLOW)
            return None
        return p
    return HOME

def cmd_disk_usage(target=None):
    """Show disk usage breakdown using dust."""
    p = _safe_path_for_scan(target) or HOME
    adwi_head(f"Disk usage: {p}")
    out = run_shell(f"dust '{p}' -n 25 -d 3 -r 2>/dev/null || du -sh '{p}'/* 2>/dev/null | sort -rh | head -25", timeout=30)
    print(out)
    # AI summary of what to do
    prompt = (
        f"Suneel's disk usage breakdown for {p}:\n\n{out[:3000]}\n\n"
        "Give a 3-bullet analysis:\n"
        "1. What's taking the most space?\n"
        "2. What looks safe to clean up?\n"
        "3. One specific action Suneel should take first."
    )
    adwi_say(call_cloud(prompt) if _cloud_ok() else quick_local(prompt))
    log_action("disk-usage", out)

def cmd_large_files(target=None, min_mb=200):
    """Find files larger than min_mb using fd."""
    p = _safe_path_for_scan(target) or HOME
    adwi_head(f"Files larger than {min_mb}MB in {p}")
    # fd is much faster than find
    out = run_shell(
        f"fd . '{p}' --type f --size +{min_mb}m "
        f"--exclude '.Trash' --exclude 'node_modules' --exclude '.git' "
        f"-x echo '{{}}' 2>/dev/null | head -40",
        timeout=30,
    )
    if not out.strip():
        out = run_shell(f"find '{p}' -type f -size +{min_mb}M ! -path '*/.Trash/*' ! -path '*/node_modules/*' 2>/dev/null | head -40", timeout=30)

    if not out.strip():
        adwi_say(f"No files larger than {min_mb}MB found in {p}.")
        return
    # Get sizes too
    sized = run_shell(
        f"fd . '{p}' --type f --size +{min_mb}m "
        f"--exclude '.Trash' --exclude 'node_modules' -x du -sh '{{}}' 2>/dev/null | sort -rh | head -30",
        timeout=30,
    ) or out
    print(sized)
    prompt = (
        f"These are Suneel's largest files in {p}:\n\n{sized[:2000]}\n\n"
        "For each one, briefly say what it likely is and whether it's safe to delete or compress. "
        "Be specific. Flag anything that looks like a backup, old cache, or unused download."
    )
    adwi_say(call_cloud(prompt) if _cloud_ok() else quick_local(prompt))
    log_action("large-files", sized)

def cmd_old_files(target=None, days=365):
    """Find files not accessed in N days."""
    p = _safe_path_for_scan(target) or HOME
    adwi_head(f"Files not accessed in {days}+ days in {p}")
    out = run_shell(
        f"find '{p}' -type f -atime +{days} "
        f"! -path '*/.Trash/*' ! -path '*/node_modules/*' ! -path '*/.git/*' "
        f"! -path '*/Library/Caches/*' ! -path '*/Photos Library/*' "
        f"2>/dev/null | head -50",
        timeout=45,
    )
    if not out.strip():
        adwi_say(f"No files found older than {days} days in {p}.")
        return
    # Add sizes
    lines = out.strip().splitlines()[:30]
    sized = "\n".join(run_shell(f"du -sh '{f}' 2>/dev/null || echo '? {f}'") for f in lines[:20])
    print(sized)
    prompt = (
        f"These files in {p} haven't been opened in {days}+ days:\n\n{sized[:2000]}\n\n"
        "Group them by category (old downloads, old projects, old logs, etc.). "
        "Which ones are likely safe to delete? Which should Suneel keep? "
        "Give specific file-by-file or group-by-group advice."
    )
    adwi_say(call_cloud(prompt) if _cloud_ok() else quick_local(prompt))
    log_action("old-files", sized)

def cmd_find_duplicates(target=None):
    """Find duplicate files by MD5 hash."""
    p = _safe_path_for_scan(target) or HOME / "Downloads"
    adwi_head(f"Finding duplicates in {p} (this may take a moment...)")
    # Limit to common user dirs to avoid scanning huge library dirs
    safe_excludes = ["Library", ".Trash", "node_modules", ".git", "Photos Library"]
    exclude_args  = " ".join(f"--exclude '{e}'" for e in safe_excludes)
    files = run_shell(
        f"fd . '{p}' --type f {exclude_args} 2>/dev/null | head -2000",
        timeout=30,
    ).splitlines()

    if not files:
        adwi_say(f"No files to scan in {p}."); return

    cprint(f"  Scanning {len(files)} files for duplicates...", GRAY)
    hashes: dict[str, list[str]] = {}
    for fp in files:
        fp = fp.strip()
        if not fp: continue
        try:
            h = hashlib.md5(Path(fp).read_bytes()).hexdigest()
            hashes.setdefault(h, []).append(fp)
        except Exception:
            pass

    dupes = {h: paths for h, paths in hashes.items() if len(paths) > 1}
    if not dupes:
        adwi_say(f"No duplicates found in {p}."); return

    total_wasted = 0
    report_lines = []
    for h, paths in list(dupes.items())[:20]:
        try:
            sz = Path(paths[0]).stat().st_size
            wasted = sz * (len(paths) - 1)
            total_wasted += wasted
            report_lines.append(f"  {_human_size(sz)} each × {len(paths)} copies:")
            for pp in paths: report_lines.append(f"    {pp}")
        except Exception:
            pass

    report = "\n".join(report_lines)
    print(report)
    print(f"\n  Total wasted space: {_human_size(total_wasted)} ({len(dupes)} duplicate groups)")
    prompt = (
        f"Suneel has these duplicate files in {p}:\n\n{report[:2000]}\n\n"
        f"Total duplicates: {len(dupes)} groups, {_human_size(total_wasted)} wasted.\n\n"
        "Which ones should be deleted? Which are important to keep? "
        "Give specific advice — e.g. 'keep the one in ~/Documents, delete the Downloads copy'."
    )
    adwi_say(call_cloud(prompt) if _cloud_ok() else quick_local(prompt))
    log_action("duplicates", report)

def cmd_organize_suggest(target=None):
    """Scan a folder and get AI-powered organization suggestions."""
    p = _safe_path_for_scan(target) or HOME / "Downloads"
    adwi_head(f"Organization analysis: {p}")
    # Get a metadata snapshot — types, counts, sizes, ages (never content)
    out = run_shell(
        f"fd . '{p}' --max-depth 2 --type f 2>/dev/null | head -200",
        timeout=20,
    )
    if not out.strip():
        adwi_say(f"Nothing to scan in {p}."); return

    files = [l.strip() for l in out.splitlines() if l.strip()]
    # Summarize by extension
    ext_counts: dict[str, int] = {}
    ext_sizes:  dict[str, int] = {}
    for fp in files:
        ext = Path(fp).suffix.lower() or "(no ext)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
        try:
            ext_sizes[ext] = ext_sizes.get(ext, 0) + Path(fp).stat().st_size
        except Exception:
            pass

    summary = "\n".join(
        f"  {ext}: {cnt} files ({_human_size(ext_sizes.get(ext,0))})"
        for ext, cnt in sorted(ext_counts.items(), key=lambda x: -x[1])[:25]
    )
    print(summary)
    # Sample filenames for context (no content)
    sample = "\n".join(Path(f).name for f in files[:40])
    prompt = (
        f"Suneel's folder: {p}\n\nFile type breakdown:\n{summary}\n\n"
        f"Sample filenames:\n{sample}\n\n"
        "Suggest a clear, practical organization plan:\n"
        "1. Recommended subfolder structure\n"
        "2. What types of files to move where\n"
        "3. What looks like it can be deleted or archived\n"
        "4. Any naming convention improvements\n"
        "Keep suggestions specific and actionable."
    )
    adwi_say(call_cloud(prompt) if _cloud_ok() else stream_local(prompt))
    log_action("organize", f"{p}\n{summary}")

def cmd_cleanup_suggest(target=None):
    """AI-powered cleanup recommendations with size breakdown."""
    p = _safe_path_for_scan(target) or HOME
    adwi_head(f"Cleanup analysis: {p}")

    # Get sizes of main folders
    if p == HOME:
        size_out = run_shell(
            f"du -sh '{p}'/*/  2>/dev/null | sort -rh | head -20",
            timeout=20,
        )
    else:
        size_out = run_shell(f"dust '{p}' -n 20 -d 2 -r 2>/dev/null || du -sh '{p}'/* 2>/dev/null | sort -rh | head -20", timeout=20)

    # Common cleanup targets
    caches = run_shell("du -sh ~/Library/Caches 2>/dev/null", timeout=10)
    trash  = run_shell("du -sh ~/.Trash 2>/dev/null", timeout=10)
    downloads_big = run_shell("du -sh ~/Downloads/* 2>/dev/null | sort -rh | head -10", timeout=10)

    report = f"Home folder sizes:\n{size_out}\n\nCaches: {caches}\nTrash: {trash}\n\nLargest Downloads:\n{downloads_big}"
    print(report)

    prompt = (
        f"Suneel wants to free up space. Here's his disk breakdown:\n\n{report[:3000]}\n\n"
        "Give a prioritized cleanup plan:\n"
        "1. Safest to delete right now (trash, obvious caches)\n"
        "2. Review before deleting (large files that might be needed)\n"
        "3. Archive vs delete decisions\n"
        "4. Estimated space you can free\n"
        "Be specific with folder names and sizes."
    )
    adwi_say(call_cloud(prompt) if _cloud_ok() else stream_local(prompt))
    log_action("cleanup", report)

def cmd_file_search(query: str, target=None):
    """Search files and content using ripgrep + fd."""
    base = Path(target).expanduser().resolve() if target else HOME
    ok, reason = safe_to_read(base)
    if not ok:
        adwi_say(f"Search blocked: {reason}"); return

    adwi_head(f"Searching for '{query}' in {base}")
    # 1. Search file names with fd
    name_hits = run_shell(
        f"fd '{re.escape(query)}' '{base}' --type f "
        f"--exclude '.Trash' --exclude 'node_modules' --exclude '.git' "
        f"2>/dev/null | head -20",
        timeout=20,
    )
    # 2. Search file content with ripgrep
    content_hits = run_shell(
        f"rg -l '{re.escape(query)}' '{base}' "
        f"--glob '!.Trash' --glob '!node_modules' --glob '!.git' "
        f"--max-filesize 5M -i 2>/dev/null | head -20",
        timeout=20,
    )
    combined = ""
    if name_hits.strip():
        combined += f"Files matching name:\n{name_hits}\n\n"
    if content_hits.strip():
        combined += f"Files containing text:\n{content_hits}\n"
    if not combined.strip():
        adwi_say(f"Nothing found for '{query}' in {base}."); return

    print(combined)
    log_action("search", combined)

def cmd_read_file(path_str: str):
    """Read a file with safety checks."""
    p = Path(path_str).expanduser().resolve()
    ok, reason = safe_to_read(p)
    if not ok:
        adwi_say(f"Cannot read: {reason}"); return
    if not p.exists():
        adwi_say(f"File not found: `{p}`"); return
    if p.is_dir():
        # List directory instead
        items = sorted(p.iterdir())[:100]
        out = "\n".join(f"  {'📁' if i.is_dir() else '📄'} {i.name}  ({_human_size(i.stat().st_size) if i.is_file() else ''})" for i in items)
        print(f"\n  Contents of {p}:\n{out}\n")
        return

    if p.suffix.lower() in IMAGE_EXTS:
        analyze_image(str(p)); return

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        if len(lines) > 500:
            print(redact("\n".join(lines[:500])))
            cprint(f"\n  ... ({len(lines)-500} more lines, showing first 500)", GRAY)
        else:
            print(redact(content))
    except Exception as e:
        adwi_say(f"Could not read file: {e}")

def cmd_list_folder(path_str: str):
    """List folder contents with sizes."""
    p = Path(path_str).expanduser().resolve()
    ok, reason = safe_to_read(p)
    if not ok:
        adwi_say(f"Blocked: {reason}"); return
    if not p.exists():
        adwi_say(f"Path not found: `{p}`"); return

    adwi_head(f"Contents of {p}")
    items = sorted(p.iterdir()) if p.is_dir() else [p]
    for item in items[:100]:
        try:
            sz  = _human_size(item.stat().st_size) if item.is_file() else ""
            icon = "📁" if item.is_dir() else "📄"
            print(f"  {icon} {item.name:<50} {GRAY}{sz}{RESET}")
        except Exception:
            print(f"  ? {item.name}")

# ── YouTube handling ──────────────────────────────────────────────────────────
def youtube_menu(url: str):
    cprint(f"\n  YouTube detected: {url}\n", CYAN, bold=True)
    print(f"  {BOLD}a{RESET}  Quick summary\n  {BOLD}b{RESET}  Detailed summary\n"
          f"  {BOLD}c{RESET}  Save to notes + Open WebUI Knowledge\n"
          f"  {BOLD}d{RESET}  Extract ideas to implement\n  {BOLD}s{RESET}  Skip\n")
    try:
        choice = input(f"  {CYAN}Choice [a/b/c/d/s]:{RESET} ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print(); return

    if choice == "s" or not choice:
        return
    if choice in ("a","b"):
        run_cmd("youtube", ["summarize-youtube", url], timeout=600)
    elif choice == "c":
        out = run_cmd("save-youtube", ["save-youtube-summary", url], timeout=600, quiet=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        vid_id = re.sub(r"[^a-z0-9-]","-",url.split("?v=")[-1][:40].lower())
        dst = KNOWLEDGE_DIR / f"{stamp}-youtube-{vid_id}.md"
        dst.write_text(f"# YouTube Summary\nURL: {url}\nSaved: {datetime.now()}\n\n---\n\n{out}\n", encoding="utf-8")
        print(out); cprint(f"\n  Saved to knowledge: {dst.name}", GREEN)
    elif choice == "d":
        summary = run_cmd("yt-ideas", ["summarize-youtube", url], timeout=600, quiet=True)
        prompt  = (
            f"Video URL: {url}\n\nSummary:\n{summary[:3000]}\n\n"
            "Extract 3-5 concrete ideas Suneel could implement for his local AI setup. "
            "For each: name it, rate effort (easy/medium/hard), list specific files or commands it would touch."
        )
        result = call_cloud(prompt) if _cloud_ok() else stream_local(prompt)
        adwi_say(result)
        dst = KNOWLEDGE_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-yt-ideas.md"
        dst.write_text(f"# Ideas from: {url}\n\n{result}\n", encoding="utf-8")
        cprint(f"  Ideas saved: {dst.name}", GREEN)

# ── Daily improve ─────────────────────────────────────────────────────────────
def cmd_daily_improve():
    adwi_head("Daily improvement routine")
    R = _repair()
    steps = []

    cprint("  [1/7] Stack status", BOLD)
    status = run_cmd("d-status", ["status-ai"], quiet=True)
    steps.append(f"Status:\n{status[:400]}")

    cprint("  [2/7] Smoke tests", BOLD)
    tests = R.run_smoke_tests()
    test_passed = sum(1 for t in tests if t["ok"])
    test_summary = f"{test_passed}/{len(tests)} tests passed"
    cprint(f"  {test_summary}", GREEN if test_passed == len(tests) else YELLOW)
    for t in tests:
        icon = f"{GREEN}✓{RESET}" if t["ok"] else f"{RED}✗{RESET}"
        cprint(f"    {icon} {t['test']}", "")
    steps.append(f"Smoke tests: {test_summary}")

    cprint("  [3/7] Reviewing recent errors", BOLD)
    errors = []
    for lf in sorted(LOG_DIR.glob("*.md"), reverse=True)[:15]:
        try:
            txt = lf.read_text(encoding="utf-8", errors="replace")
            if "ERROR" in txt: errors.append(f"{lf.name}: {txt[txt.find('ERROR'):][:150]}")
        except Exception: pass
    # Also check repair logs
    repair_dir = R.REPAIR_DIR
    if repair_dir.exists():
        for lf in sorted(repair_dir.glob("*FAILED*.md"), reverse=True)[:3]:
            try: errors.append(f"repair: {lf.name}")
            except Exception: pass
    cprint(f"  Found {len(errors)} error(s) in recent logs", YELLOW if errors else GREEN)
    if errors: steps.append("Recent errors:\n" + "\n".join(errors[:3]))

    cprint("  [4/7] Capability sync", BOLD)
    added = R.update_capabilities_json()
    if added:
        cprint(f"  ✓ Added {added} new commands to capabilities.json", GREEN)
    else:
        cprint(f"  ✓ capabilities.json is up to date", GRAY)

    cprint("  [5/7] AI analysis", BOLD)
    ctx = "\n\n".join(steps)
    if JOURNAL_FILE.exists(): ctx += "\n\nJournal:\n" + JOURNAL_FILE.read_text(encoding="utf-8")[-1500:]
    if ROADMAP_FILE.exists(): ctx += "\n\nRoadmap:\n" + ROADMAP_FILE.read_text(encoding="utf-8")[:1500:]

    analysis = call_cloud(
        f"Daily improvement review for Adwi (Suneel's local AI):\n\n{ctx}\n\n"
        "In under 200 words: (1) what's healthy, (2) what needs fixing, (3) top 2 next actions, (4) one rule to log."
    ) if _cloud_ok() else quick_local(f"Summarize this status briefly:\n{ctx[:1500]}")
    adwi_say(analysis)

    cprint("  [6/7] Updating journal", BOLD)
    log_journal(f"**Daily improve**\n\n{analysis}\n\nErrors: {len(errors)}\nTests: {test_summary}")

    cprint("  [7/7] Refreshing index + syncing knowledge", BOLD)
    run_cmd("index", ["index-ai-notes"], quiet=True)
    for src, name in [(JOURNAL_FILE,"adwi-learning-journal.md"),(MISTAKES_FILE,"adwi-mistakes-and-fixes.md"),(ROADMAP_FILE,"adwi-capability-roadmap.md")]:
        if src.exists():
            try: (KNOWLEDGE_DIR/name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception: pass
    run_cmd("sync", ["sync-openwebui-knowledge"], quiet=True)

    cprint(f"\n  Done — {datetime.now().strftime('%H:%M')} · {test_summary}", GREEN, bold=True)
    log_action("daily-improve", analysis)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _human_size(b: int) -> str:
    for unit in ["B","KB","MB","GB","TB"]:
        if b < 1024: return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"

def _cloud_ok() -> bool:
    s = load_secrets()
    key = s.get("OPENWEBUI_API_KEY","")
    return bool(key and not key.startswith("PASTE_"))

# ── Capabilities ──────────────────────────────────────────────────────────────
def print_capabilities():
    caps = json.loads(CAPS_FILE.read_text(encoding="utf-8")).get("capabilities",[]) if CAPS_FILE.exists() else []
    adwi_head(f"Adwi capabilities ({len(caps)} registered)")
    rc = {"low":GREEN,"medium":YELLOW,"high":RED}
    for c in caps:
        print(f"  {GREEN}✓{RESET}  {BOLD}{c['name']}{RESET}")
        print(f"     {GRAY}{c.get('description','')}{RESET}")
        print()

# ── RAG / Semantic notes search ───────────────────────────────────────────────
def _embed(text: str) -> list:
    """Get embedding vector from Ollama nomic-embed-text."""
    payload = json.dumps({"model": MODEL_EMBED, "prompt": text[:3000]}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/embeddings",
        data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r).get("embedding", [])
    except Exception:
        return []

def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b): return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    na  = sum(x*x for x in a) ** 0.5
    nb  = sum(x*x for x in b) ** 0.5
    return dot / (na*nb) if na and nb else 0.0

def cmd_rag_index(quiet=False) -> None:
    """Index workspace .md/.txt files into a JSON embedding store."""
    RAG_DB_DIR.mkdir(parents=True, exist_ok=True)
    db_file = RAG_DB_DIR / "notes-index.json"
    existing = {}
    if db_file.exists():
        try: existing = {d["file"]: d for d in json.loads(db_file.read_text())["docs"]}
        except Exception: pass

    docs, new_count, seen = [], 0, set()
    for root in [NOTES, ADWI_DIR]:
        if not root.exists(): continue
        for ext in ["*.md", "*.txt"]:
            for f in sorted(root.rglob(ext)):
                key = str(f)
                if key in seen: continue
                seen.add(key)
                ok, _ = safe_to_read(f)
                if not ok: continue
                try:
                    mtime = str(f.stat().st_mtime)
                    if key in existing and existing[key].get("mtime") == mtime:
                        docs.append(existing[key]); continue
                    text = f.read_text(encoding="utf-8", errors="replace")
                    if len(text) < 40: continue
                    emb = _embed(text[:3000])
                    if not emb: continue
                    docs.append({"file": key, "mtime": mtime, "text": text[:700], "embedding": emb})
                    new_count += 1
                    if not quiet: print(f"  {GRAY}indexed: {f.name}{RESET}")
                except Exception: continue

    db_file.write_text(json.dumps({"docs": docs}), encoding="utf-8")
    if not quiet:
        cprint(f"  ✓ RAG index: {new_count} new, {len(docs)-new_count} cached, {len(docs)} total", GREEN)

# ── Web Search (SearXNG) ──────────────────────────────────────────────────────

def _searxng_search(query: str, max_results: int = 8) -> list:
    """Query local SearXNG. Returns [{title, url, content, source}]."""
    import urllib.parse
    params = urllib.parse.urlencode({
        "q": query, "format": "json", "language": "en",
        "engines": "google,duckduckgo,bing", "safesearch": "0",
    })
    try:
        req = urllib.request.Request(
            f"{SEARXNG_URL}/search?{params}", headers={"User-Agent": "Adwi/1.0"}
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        return [
            {"title": i.get("title",""), "url": i.get("url",""),
             "content": i.get("content","")[:400], "source": "searxng"}
            for i in data.get("results", [])[:max_results]
        ]
    except Exception as e:
        return [{"title": "SearXNG unavailable", "url": "", "content": str(e), "source": "searxng"}]


def _tavily_search(query: str, max_results: int = 6) -> list:
    """Query Tavily AI search API. Returns [{title, url, content, source}]."""
    if not TAVILY_API_KEY:
        return []
    payload = json.dumps({
        "api_key": TAVILY_API_KEY,
        "query":   query,
        "search_depth": "basic",
        "max_results":  max_results,
        "include_answer": False,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://api.tavily.com/search", data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Adwi/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return [
            {"title": i.get("title",""), "url": i.get("url",""),
             "content": i.get("content","")[:400], "source": "tavily"}
            for i in data.get("results", [])[:max_results]
        ]
    except Exception as e:
        return [{"title": "Tavily error", "url": "", "content": str(e), "source": "tavily"}]


def _exa_search(query: str, max_results: int = 5) -> list:
    """Query Exa neural search API. Returns [{title, url, content, source}]."""
    if not EXA_API_KEY:
        return []
    # Step 1: search
    payload = json.dumps({
        "query": query, "numResults": max_results,
        "useAutoprompt": True, "type": "neural",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://api.exa.ai/search", data=payload,
            headers={"Content-Type": "application/json",
                     "x-api-key": EXA_API_KEY, "User-Agent": "Adwi/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        results = data.get("results", [])
        if not results:
            return []

        # Step 2: fetch highlights/snippets for the result IDs
        ids = [r["id"] for r in results if r.get("id")]
        contents: dict = {}
        if ids:
            cpayload = json.dumps({
                "ids": ids,
                "text": {"maxCharacters": 400, "includeHtmlTags": False},
            }).encode("utf-8")
            creq = urllib.request.Request(
                "https://api.exa.ai/contents", data=cpayload,
                headers={"Content-Type": "application/json",
                         "x-api-key": EXA_API_KEY},
            )
            with urllib.request.urlopen(creq, timeout=15) as cr:
                cdata = json.loads(cr.read())
            for c in cdata.get("results", []):
                contents[c["id"]] = c.get("text", "")

        return [
            {"title": r.get("title",""), "url": r.get("url",""),
             "content": contents.get(r.get("id",""), r.get("url",""))[:400],
             "source": "exa"}
            for r in results
        ]
    except Exception as e:
        return [{"title": "Exa error", "url": "", "content": str(e), "source": "exa"}]


def _firecrawl_scrape(url: str) -> dict:
    """Scrape a URL via Firecrawl API. Returns {markdown, title, description, success}."""
    if not FIRECRAWL_API_KEY:
        return {"success": False, "error": "FIRECRAWL_API_KEY not set"}
    payload = json.dumps({"url": url, "formats": ["markdown"]}).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://api.firecrawl.dev/v1/scrape", data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "User-Agent":    "Adwi/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        if data.get("success"):
            inner = data.get("data", {})
            meta  = inner.get("metadata", {})
            return {
                "success":     True,
                "markdown":    inner.get("markdown", ""),
                "title":       meta.get("title", ""),
                "description": meta.get("description", ""),
            }
        return {"success": False, "error": data.get("error", "unknown")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_web(query: str, max_results: int = 8) -> tuple[list, str]:
    """
    Multi-source web search with priority cascade.
    Priority: SearXNG (local, always) → Tavily (AI-quality) → Exa (neural).
    Returns (results_list, source_label).
    """
    # Always run SearXNG (local, no quota)
    results = _searxng_search(query, max_results)
    ok      = [r for r in results if r.get("url")]

    # Tavily: add if key present — deduplicate by URL
    if TAVILY_API_KEY:
        seen_urls = {r["url"] for r in ok}
        for r in _tavily_search(query, max_results):
            if r.get("url") and r["url"] not in seen_urls:
                ok.append(r); seen_urls.add(r["url"])

    # Exa: add for research/neural enrichment if key present
    if EXA_API_KEY:
        seen_urls = {r["url"] for r in ok}
        for r in _exa_search(query, 4):
            if r.get("url") and r["url"] not in seen_urls:
                ok.append(r); seen_urls.add(r["url"])

    sources = sorted({r["source"] for r in ok})
    return ok[:max_results + 4], " + ".join(sources)


def cmd_web_search(query: str = "") -> None:
    """Search the web via SearXNG + Tavily + Exa and synthesize results."""
    if not query:
        query = input(f"  {CYAN}Web search:{RESET} ").strip()
    if not query:
        return
    adwi_head(f"Web search: {query[:60]}")
    activity_start(query, "Web Search")

    results, sources = search_web(query)
    real = [r for r in results if r.get("url")]
    if not real:
        cprint("  No results from any source", YELLOW)
        activity_done("no results"); return

    cprint(f"  {GRAY}Sources: {sources}{RESET}", "")
    for i, r in enumerate(real, 1):
        badge = {"tavily": GREEN, "exa": YELLOW, "searxng": CYAN}.get(r["source"], GRAY)
        cprint(f"  {badge}[{r['source'][:3].upper()}]{RESET} {r['title']}", "")
        cprint(f"        {GRAY}{r['url']}{RESET}", "")
        if r["content"]:
            cprint(f"        {r['content'][:110]}", GRAY)

    ctx = "\n\n".join(
        f"[{i}] {r['title']}\nURL: {r['url']}\n{r['content']}"
        for i, r in enumerate(real, 1)
    )
    print()
    stream_local(
        f"Query: {query}\n\nSearch results (from {sources}):\n{ctx}\n\n"
        "Synthesize the key findings. Be specific, cite URLs, flag anything actionable.",
        system="You are Adwi. Summarize web search results factually and concisely.",
    )
    activity_done(f"{len(real)} results via {sources}")
    log_action("web_search", f"Query: {query} | sources: {sources}\n{ctx[:1000]}")


def cmd_exa_search(query: str = "") -> None:
    """Neural/semantic web search via Exa — better for research than keyword search."""
    if not EXA_API_KEY:
        cprint("  EXA_API_KEY not set in config/.env", YELLOW); return
    if not query:
        query = input(f"  {CYAN}Exa neural search:{RESET} ").strip()
    if not query:
        return
    adwi_head(f"Exa neural search: {query[:60]}")
    activity_start(query, "Exa Search")
    results = _exa_search(query, max_results=8)
    real = [r for r in results if r.get("url")]
    if not real:
        cprint("  No Exa results", YELLOW); activity_done("no results"); return
    for i, r in enumerate(real, 1):
        cprint(f"  {YELLOW}[{i}]{RESET} {r['title']}", "")
        cprint(f"       {GRAY}{r['url']}{RESET}", "")
        if r["content"]:
            cprint(f"       {r['content'][:120]}", GRAY)
    ctx = "\n\n".join(f"[{i}] {r['title']}\nURL: {r['url']}\n{r['content']}" for i, r in enumerate(real, 1))
    print()
    stream_local(
        f"Neural search query: {query}\n\nResults:\n{ctx}\n\nSynthesize insights.",
        system="You are Adwi. Summarize these semantically-matched web results.",
    )
    activity_done(f"{len(real)} Exa results")


def cmd_tavily_search(query: str = "") -> None:
    """AI-curated web search via Tavily — high-quality, LLM-optimized results."""
    if not TAVILY_API_KEY:
        cprint("  TAVILY_API_KEY not set in config/.env", YELLOW); return
    if not query:
        query = input(f"  {CYAN}Tavily search:{RESET} ").strip()
    if not query:
        return
    adwi_head(f"Tavily search: {query[:60]}")
    activity_start(query, "Tavily Search")
    results = _tavily_search(query, max_results=8)
    real = [r for r in results if r.get("url")]
    if not real:
        cprint("  No Tavily results", YELLOW); activity_done("no results"); return
    for i, r in enumerate(real, 1):
        cprint(f"  {GREEN}[{i}]{RESET} {r['title']}", "")
        cprint(f"       {GRAY}{r['url']}{RESET}", "")
        if r["content"]:
            cprint(f"       {r['content'][:120]}", GRAY)
    ctx = "\n\n".join(f"[{i}] {r['title']}\nURL: {r['url']}\n{r['content']}" for i, r in enumerate(real, 1))
    print()
    stream_local(
        f"Tavily search: {query}\n\nResults:\n{ctx}\n\nSynthesize the findings.",
        system="You are Adwi. Summarize these AI-curated search results concisely.",
    )
    activity_done(f"{len(real)} Tavily results")


def cmd_firecrawl(url_and_q: str = "") -> None:
    """Scrape any URL to clean markdown via Firecrawl, then summarize."""
    if not FIRECRAWL_API_KEY:
        cprint("  FIRECRAWL_API_KEY not set in config/.env", YELLOW); return
    parts    = url_and_q.split(None, 1)
    url      = parts[0].strip() if parts else ""
    question = parts[1].strip() if len(parts) > 1 else None
    if not url:
        url = input(f"  {CYAN}URL to scrape:{RESET} ").strip()
    if not url:
        return
    if not url.startswith("http"):
        url = "https://" + url
    adwi_head(f"Firecrawl: {url[:70]}")
    activity_start(url, "Firecrawl Scrape")
    cprint(f"  {GRAY}Scraping via Firecrawl…{RESET}", "")
    result = _firecrawl_scrape(url)
    if not result["success"]:
        cprint(f"  ✗ Firecrawl error: {result.get('error')}", RED)
        activity_error(result.get("error", "failed")); return
    md    = result["markdown"]
    title = result.get("title", "")
    cprint(f"  {GREEN}✓{RESET} Scraped {len(md):,} chars — {title}", "")
    truncated = md[:8000]
    if question:
        stream_local(
            f"URL: {url}\nTitle: {title}\n\nPage content (markdown):\n{truncated}\n\nQuestion: {question}",
            system="You are Adwi. Answer using the scraped page content. Quote relevant sections.",
        )
    else:
        stream_local(
            f"Summarize this page for Suneel:\nURL: {url}\nTitle: {title}\n\n{truncated}",
            system="You are Adwi. Give a structured 5-bullet summary. Note any code, commands, or action items.",
        )
    activity_done(f"{len(md):,} chars scraped")
    log_action("firecrawl", f"URL: {url}\n{md[:500]}")


# ── Obsidian Vault Access ─────────────────────────────────────────────────────

def _obsidian_api(method: str, route: str, body: dict | None = None) -> dict:
    """Call the local Obsidian Bridge API. Returns parsed JSON or error dict."""
    url = OBSIDIAN_BRIDGE + route
    try:
        data = json.dumps(body).encode("utf-8") if body else None
        req  = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except urllib.error.URLError:
        return {"error": f"Obsidian Bridge not reachable at {OBSIDIAN_BRIDGE} — run: bin/start-obsidian-bridge"}
    except Exception as e:
        return {"error": str(e)}


def _obsidian_local_search(query: str, max_results: int = 15) -> list:
    """Full-text search vault .md files directly (no bridge needed)."""
    q       = query.lower()
    results = []
    for md in sorted(OBSIDIAN_VAULT.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
            if q in text.lower():
                idx     = text.lower().find(q)
                start   = max(0, idx - 80)
                snippet = text[start : idx + 200].replace("\n", " ").strip()
                results.append({"path": str(md.relative_to(OBSIDIAN_VAULT)), "snippet": snippet})
                if len(results) >= max_results:
                    break
        except Exception:
            continue
    return results


def cmd_obsidian_search(query: str = "") -> None:
    """Full-text search across all Obsidian vault notes."""
    if not query:
        query = input(f"  {CYAN}Vault search:{RESET} ").strip()
    if not query:
        return
    adwi_head(f"Obsidian search: {query[:60]}")
    hits = _obsidian_local_search(query)
    if not hits:
        cprint("  No matching notes in vault", GRAY); return
    for h in hits:
        cprint(f"  {GREEN}{h['path']}{RESET}", "")
        cprint(f"    {GRAY}{h['snippet'][:140]}{RESET}", "")
    cprint(f"\n  {len(hits)} note(s) matched — use /obsidian-read <path> to open", GRAY)


def cmd_obsidian_read(rel_path: str = "") -> None:
    """Read a note from the Obsidian vault by relative path."""
    if not rel_path:
        rel_path = input(f"  {CYAN}Note path (e.g. knowledge/foo.md):{RESET} ").strip()
    if not rel_path:
        return
    adwi_head(f"Obsidian: {rel_path}")
    result = _obsidian_api("GET", f"/read?path={urllib.parse.quote(rel_path)}")
    if "error" in result:
        cprint(f"  ✗ {result['error']}", RED); return
    cprint(f"  {GRAY}Modified: {result.get('modified','?')}{RESET}", "")
    print()
    print(result.get("content", ""))


def cmd_obsidian_write(args: str = "") -> None:
    """Write or append to an Obsidian vault note.
    Usage: /obsidian-write [path] [-- content]
    """
    adwi_head("Obsidian: write note")
    if " -- " in args:
        rel_path, content = args.split(" -- ", 1)
    else:
        rel_path = args.strip() or input(f"  {CYAN}Note path:{RESET} ").strip()
        content  = input(f"  {CYAN}Content (single line):{RESET} ").strip()
    if not rel_path or not content:
        cprint("  Usage: /obsidian-write knowledge/my-note.md -- content here", YELLOW); return
    result = _obsidian_api("POST", "/append", {"path": rel_path.strip(), "content": content})
    if "error" in result:
        cprint(f"  ✗ {result['error']}", RED)
    else:
        cprint(f"  ✓ Appended {result.get('total_bytes', '?')} bytes → {rel_path.strip()}", GREEN)


def cmd_obsidian_daily(content: str = "") -> None:
    """Append a timestamped entry to today's Obsidian daily note."""
    if not content:
        content = input(f"  {CYAN}Entry:{RESET} ").strip()
    if not content:
        return
    ts      = datetime.now().strftime("%H:%M")
    entry   = f"\n## {ts}\n{content}\n"
    result  = _obsidian_api("POST", "/daily-note", {"content": entry})
    if "error" in result:
        cprint(f"  ✗ {result['error']}", RED)
    else:
        cprint(f"  ✓ Added to daily note → {result.get('daily_note', '?')}", GREEN)


# ── import for obsidian URL quoting ──────────────────────────────────────────
import urllib.parse as _urlparse_mod
# Bind to local name used inside _obsidian_api and cmd_obsidian_read
try:
    import urllib.parse
except ImportError:
    pass


def cmd_rag_search(query: str, top_k: int = 5) -> None:
    """Semantic search over local notes, then answer using retrieved context."""
    adwi_head(f"Searching local knowledge: {query[:60]}")
    db_file = RAG_DB_DIR / "notes-index.json"

    if not db_file.exists():
        cprint("  No index yet — building now (this takes ~30s first time)…", GRAY)
        cmd_rag_index(quiet=True)

    try:
        docs = json.loads(db_file.read_text())["docs"]
    except Exception:
        cprint("  Index unreadable. Run: /rag-index", YELLOW); return

    qemb = _embed(query)
    if not qemb:
        cprint("  Embedding model unavailable (is Ollama running?)", YELLOW)
        ask_adwi(query); return

    scored = sorted(
        ((d, _cosine(qemb, d["embedding"])) for d in docs),
        key=lambda x: x[1], reverse=True
    )
    top = [(d,s) for d,s in scored[:top_k] if s >= 0.3]

    if not top:
        cprint("  No strong matches in local notes — answering from model memory.", GRAY)
        ask_adwi(query); return

    ctx_parts = []
    for doc, sim in top:
        cprint(f"  {GREEN}[{sim:.0%}]{RESET} {GRAY}{Path(doc['file']).name}{RESET}", "")
        ctx_parts.append(f"**From {Path(doc['file']).name}:**\n{doc['text']}")

    print()
    stream_local(
        f"User question: {query}\n\nRelevant local knowledge:\n\n" + "\n\n---\n\n".join(ctx_parts) +
        "\n\nAnswer using the provided context. Reference file names when relevant.",
        system=(
            "You are Adwi, Suneel's local AI assistant. Answer based on provided "
            "local knowledge. Be concise and specific. Reference source files by name."
        ),
    )

# ── Browser automation ─────────────────────────────────────────────────────────
def cmd_browse(url_and_q: str) -> None:
    """
    Fetch a URL and summarize or answer a question.
    Priority: Firecrawl (clean markdown) → Playwright (JS) → urllib (raw HTML).
    """
    parts    = url_and_q.split(None, 1)
    url      = parts[0] if parts else ""
    question = parts[1].strip() if len(parts) > 1 else None
    if not url:
        cprint("  Usage: /browse <url> [question]", YELLOW); return
    if not url.startswith("http"):
        url = "https://" + url

    adwi_head(f"Fetching: {url[:80]}")
    text = title = method = ""

    # ── Priority 1: Firecrawl — cleanest markdown output ─────────────────────
    if FIRECRAWL_API_KEY:
        cprint(f"  {GRAY}Fetching via Firecrawl…{RESET}", "")
        fc = _firecrawl_scrape(url)
        if fc["success"] and fc.get("markdown"):
            text   = fc["markdown"][:8000]
            title  = fc.get("title", "")
            method = "Firecrawl"

    # ── Priority 2: Playwright — JS-capable local browser ────────────────────
    if not text:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
            cprint(f"  {GRAY}Fetching via Playwright…{RESET}", "")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page    = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                title   = page.title()
                text    = page.evaluate(
                    "() => { const els = document.querySelectorAll('article,main,p,h1,h2,h3,li');"
                    " return Array.from(els).map(e=>e.innerText).join('\\n').slice(0,8000); }"
                )
                browser.close()
            method = "Playwright"
        except ImportError:
            pass
        except Exception as e:
            cprint(f"  {YELLOW}Playwright: {e}{RESET}", "")

    # ── Priority 3: urllib — raw HTML strip ───────────────────────────────────
    if not text:
        try:
            cprint(f"  {GRAY}Fetching via urllib…{RESET}", "")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="replace")
            text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S|re.I)
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S|re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text)[:8000]
            method = "urllib"
        except Exception as e:
            cprint(f"  Could not fetch: {e}", RED); return

    if not text.strip():
        cprint("  Page appears empty or JS-blocked.", YELLOW); return

    cprint(f"  {GREEN}✓{RESET} {title or url[:60]}  {GRAY}[via {method}]{RESET}", "")
    if question:
        stream_local(
            f"URL: {url}\nTitle: {title}\nContent:\n{text}\n\nQuestion: {question}",
            system="You are Adwi. Answer the question using the webpage content. Quote relevant sections.",
        )
    else:
        stream_local(
            f"Summarize this page for Suneel:\nURL: {url}\nTitle: {title}\n\nContent:\n{text}",
            system="You are Adwi. Give a structured 5-bullet summary. Note code, commands, or action items.",
        )

# ── Code execution sandbox ─────────────────────────────────────────────────────
def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python|py|bash|sh)?\n(.*?)```", text, re.S)
    return m.group(1).strip() if m else text.strip()

def cmd_run_python(raw: str) -> None:
    """Run Python code with user confirmation and 30s timeout."""
    import tempfile
    code = _extract_code(raw)
    if not code:
        cprint("  No code found. Paste code or wrap in ```python blocks.", YELLOW); return

    adwi_head("Run Python")
    print(f"{GRAY}─── code ──────────────────────────────────────────{RESET}")
    for ln in code.splitlines()[:40]:
        print(f"  {ln}")
    if code.count("\n") > 40:
        cprint(f"  … ({code.count(chr(10))+1} lines total)", GRAY)
    print(f"{GRAY}──────────────────────────────────────────────────{RESET}\n")

    ans = input(f"  {YELLOW}Run this? (y/n){RESET} ").strip().lower()
    if ans not in ("y","yes"):
        cprint("  Cancelled.", GRAY); return

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code); tmp = f.name

    try:
        r = subprocess.run(
            ["python3", tmp], capture_output=True, text=True, timeout=30,
            env={**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
        )
        if r.stdout: print(r.stdout)
        if r.stderr: cprint(r.stderr[:1000], YELLOW)
        cprint(f"\n  exit {r.returncode}", GRAY)
        log_action("run-python", f"code:\n{code}\n\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    except subprocess.TimeoutExpired:
        cprint("  Timed out (30s limit).", YELLOW)
    except Exception as e:
        cprint(f"  Error: {e}", RED)
    finally:
        Path(tmp).unlink(missing_ok=True)

def cmd_run_bash(raw: str) -> None:
    """Run a shell command with confirmation. Blocks destructive patterns."""
    cmd = raw.strip()
    if not cmd:
        cprint("  No command given.", YELLOW); return
    if denied(cmd):
        cprint("  Blocked: command matches destructive/financial deny pattern.", RED); return

    adwi_head("Run bash")
    cprint(f"  $ {cmd}", CYAN)
    ans = input(f"\n  {YELLOW}Run this? (y/n){RESET} ").strip().lower()
    if ans not in ("y","yes"):
        cprint("  Cancelled.", GRAY); return

    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
        )
        out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
        print(redact(out))
        cprint(f"\n  exit {r.returncode}", GRAY)
        log_action("run-bash", f"cmd: {cmd}\n\n{redact(out)}")
    except subprocess.TimeoutExpired:
        cprint("  Timed out (60s).", YELLOW)
    except Exception as e:
        cprint(f"  Error: {e}", RED)

# ── GitHub connectivity status ────────────────────────────────────────────────
def cmd_github_connected() -> None:
    """Answer: is Adwi connected to GitHub? Shows auth, remote, last commit."""
    adwi_head("GitHub connection status")
    activity_start("is GitHub / Adwi connected to GitHub?", "GitHub Connection Check")

    # 1. gh CLI auth
    activity_step("running", "gh auth status")
    gh_out = run_shell("/opt/homebrew/bin/gh auth status 2>&1")
    if "Logged in" in gh_out or "✓ Logged in" in gh_out:
        user_m = re.search(r"account\s+(\S+)", gh_out)
        user = user_m.group(1) if user_m else "your account"
        cprint(f"  {GREEN}✓ gh CLI authenticated{RESET} as {BOLD}{user}{RESET}", "")
    elif gh_out.strip():
        cprint(f"  {YELLOW}⚠ gh auth: {gh_out.splitlines()[0][:80]}{RESET}", "")
    else:
        cprint(f"  {GRAY}gh CLI not available or not authenticated{RESET}", "")

    # 2. Git remote
    activity_step("inspecting", "git remote URL")
    remote = run_shell(f"git -C '{BASE}' remote get-url origin 2>/dev/null")
    if remote:
        safe_remote = re.sub(r"https?://[^@]+@", "https://REDACTED@", remote)
        cprint(f"  {GREEN}✓ Remote{RESET}  → {CYAN}{safe_remote}{RESET}", "")
    else:
        cprint(f"  {YELLOW}⚠ No remote set{RESET} — run /backup-enable to configure", "")

    # 3. Branch + ahead/behind
    branch = run_shell(f"git -C '{BASE}' branch --show-current 2>/dev/null")
    ahead  = run_shell(f"git -C '{BASE}' rev-list --count '@{{u}}..HEAD' 2>/dev/null || echo 0").strip()
    if branch:
        cprint(f"  {GREEN}✓ Branch{RESET}  → {branch}  ({ahead} commit(s) not yet pushed)", "")

    # 4. Last commit
    last = run_shell(f"git -C '{BASE}' log --oneline -1 2>/dev/null")
    if last:
        cprint(f"  {GREEN}✓ Last commit{RESET}  → {last}", "")

    # 5. Untracked count
    status = run_shell(f"git -C '{BASE}' status --short 2>/dev/null")
    untracked = [l for l in status.splitlines() if l.startswith("??")]
    modified  = [l for l in status.splitlines() if not l.startswith("??")]
    if untracked:
        cprint(f"\n  {len(untracked)} file(s) not yet committed → /backup-now to push them", YELLOW)
    if modified:
        cprint(f"  {len(modified)} modified file(s) → /backup-now to commit", YELLOW)
    if not untracked and not modified:
        cprint(f"\n  {GREEN}✓ Everything pushed — workspace is fully backed up{RESET}", "")

    activity_done("GitHub connection check complete")


def cmd_github_visibility(target: str = "") -> None:
    """Make the GitHub repo public or private using gh CLI (requires confirmation)."""
    adwi_head("GitHub repo visibility")
    # Determine intent: public or private
    want_public = bool(re.search(r"\bpublic\b", target, re.I)) or \
                  not bool(re.search(r"\bprivate\b", target, re.I))
    visibility = "public" if want_public else "private"

    # Get current repo name from remote
    remote = run_shell(f"git -C '{BASE}' remote get-url origin 2>/dev/null").strip()
    if not remote:
        cprint("  No remote configured. Run /backup-enable first.", YELLOW); return
    repo_name = re.sub(r".*github\.com[:/]", "", remote).rstrip(".git")

    cprint(f"  Repo    : {repo_name}", GRAY)
    cprint(f"  Current : private (assumed — created with --private flag)", GRAY)
    cprint(f"  New     : {BOLD}{visibility}{RESET}", "")
    if want_public:
        cprint(f"\n  {YELLOW}⚠  Making a repo public exposes ALL its history and files.{RESET}", "")
        cprint(f"  Verify secrets/ and .env files are NOT committed before proceeding.", GRAY)

    ans = input(f"\n  {YELLOW}Change '{repo_name}' to {visibility}? (y/n):{RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY); return

    activity_step("running", f"gh repo edit --visibility {visibility}")
    out = run_shell(f"/opt/homebrew/bin/gh repo edit {repo_name} --visibility {visibility} 2>&1")
    if out.strip():
        cprint(f"  {out}", GRAY)
    # Verify
    info = run_shell(f"/opt/homebrew/bin/gh repo view {repo_name} --json visibility -q '.visibility' 2>/dev/null").strip()
    if info.lower() == visibility:
        cprint(f"\n  {GREEN}✓ Repo is now {visibility.upper()}{RESET}", "")
        if want_public:
            cprint(f"  URL: https://github.com/{repo_name}", CYAN)
    else:
        cprint(f"\n  {YELLOW}⚠ Could not confirm — check: gh repo view {repo_name}{RESET}", "")
    _flush_trace()


# ── Git + repository management ────────────────────────────────────────────────
def _find_git_repo(path: str = None) -> Path:
    """Find a git repo: at given path, in cwd, or first repo in workspace."""
    if path:
        p = Path(path).expanduser().resolve()
        if (p / ".git").exists(): return p
        for parent in p.parents:
            if (parent / ".git").exists(): return parent
    for d in sorted(BASE.iterdir()):
        if d.is_dir() and (d / ".git").exists():
            return d
    return BASE

def cmd_git(args: str = "") -> None:
    """Git status / log / diff / review / repos — safe read-only operations."""
    parts = args.split(None, 1)
    sub   = parts[0].lower() if parts else "status"
    path  = parts[1] if len(parts) > 1 else None
    repo  = _find_git_repo(path)

    ok, reason = safe_to_read(repo)
    if not ok:
        cprint(f"  Blocked: {reason}", YELLOW); return

    if sub in ("status", "st", ""):
        branch = run_shell(f"git -C '{repo}' branch --show-current 2>&1")
        if "not a git repository" in branch or "fatal" in branch:
            repos = [d for d in sorted(BASE.iterdir()) if d.is_dir() and (d/".git").exists()]
            if repos:
                adwi_head("Git repos in workspace")
                for d in repos:
                    b = run_shell(f"git -C '{d}' branch --show-current 2>/dev/null")
                    cprint(f"  {GREEN}●{RESET}  {d.name}  {GRAY}[{b}]{RESET}", "")
                cprint(f"\n  Tip: /git status {repos[0].name}  to check a specific repo", GRAY)
            else:
                adwi_say("No git repositories found in your workspace. To connect GitHub, make sure `gh auth login` has been run.")
            return
        adwi_head(f"Git status: {repo.name}")
        remote = run_shell(f"git -C '{repo}' remote get-url origin 2>/dev/null")
        ahead  = run_shell(f"git -C '{repo}' rev-list --count '@{{u}}..HEAD' 2>/dev/null || echo 0")
        last   = run_shell(f"git -C '{repo}' log --oneline -1 2>/dev/null")
        cprint(f"  Branch : {BOLD}{branch}{RESET}", "")
        if remote:
            # Redact any embedded tokens from remote URL
            safe_remote = re.sub(r"https?://[^@]+@", "https://REDACTED@", remote)
            cprint(f"  Remote : {safe_remote}", CYAN)
        cprint(f"  Ahead  : {ahead} commit(s) ahead of remote", "")
        if last:
            cprint(f"  Last   : {last}", GRAY)
        # Show modified/staged but NOT a wall of untracked ??
        status = run_shell(f"git -C '{repo}' status --short 2>&1")
        if status:
            tracked_changes = [l for l in status.splitlines() if not l.startswith("??")]
            untracked       = [l for l in status.splitlines() if l.startswith("??")]
            if tracked_changes:
                cprint(f"\n  Changes:", YELLOW)
                for l in tracked_changes[:15]:
                    cprint(f"    {l}", "")
            if untracked:
                cprint(f"\n  {len(untracked)} untracked file(s) not yet committed", GRAY)
                cprint(f"  Use /backup-now to commit and push them to GitHub", GRAY)
        else:
            cprint(f"\n  {GREEN}✓ Working tree clean{RESET}", "")

    elif sub == "log":
        adwi_head(f"Git log: {repo.name}")
        print(run_shell(f"git -C '{repo}' log --oneline -15 2>&1"))

    elif sub == "diff":
        adwi_head(f"Git diff: {repo.name}")
        out = run_shell(f"git -C '{repo}' diff --stat HEAD 2>&1")
        print(out or "  No changes")

    elif sub in ("review", "pr"):
        adwi_head(f"Code review: {repo.name}")
        diff = run_shell(f"git -C '{repo}' diff HEAD~1..HEAD 2>&1")[:5000]
        if not diff.strip():
            diff = run_shell(f"git -C '{repo}' show --stat HEAD 2>&1")[:2000]
        stream_local(
            f"Review this git diff for Suneel:\n\n{diff}\n\n"
            "List: (1) what changed, (2) potential issues, (3) suggestions. Be concise.",
            system="You are Adwi, a code reviewer. Give practical, specific feedback."
        )

    elif sub == "repos":
        adwi_head("Git repos in workspace")
        for d in sorted(BASE.iterdir()):
            if d.is_dir() and (d / ".git").exists():
                branch = run_shell(f"git -C '{d}' branch --show-current 2>/dev/null")
                dirty  = run_shell(f"git -C '{d}' status --short 2>/dev/null")
                marker = "*" if dirty else " "
                cprint(f"  {marker} {d.name:<30} {GRAY}[{branch}]{RESET}", YELLOW if dirty else CYAN)

    else:
        safe_subs = {"log","status","diff","show","branch","remote","stash","tag","describe"}
        if sub in safe_subs:
            print(run_shell(f"git -C '{repo}' {args} 2>&1"))
        else:
            cprint("  Subcommands: status · log · diff · review · repos", GRAY)

# ── Image generation (LocalAI) ─────────────────────────────────────────────────
def cmd_generate_image(prompt: str) -> None:
    """Generate an image via LocalAI (must be started first)."""
    if not prompt.strip():
        cprint("  Usage: /generate-image <description>", YELLOW); return

    adwi_head(f"Generating: {prompt[:60]}")
    IMG_GEN_DIR.mkdir(parents=True, exist_ok=True)

    payload = json.dumps({
        "model": "stablediffusion",
        "prompt": prompt, "n": 1,
        "size": "512x512", "response_format": "b64_json",
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8080/v1/images/generations",
        data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.load(r)
        b64 = data.get("data", [{}])[0].get("b64_json", "")
        if b64:
            stamp    = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_name = re.sub(r"[^a-zA-Z0-9]+", "-", prompt[:30]).strip("-")
            out_path = IMG_GEN_DIR / f"{stamp}-{safe_name}.png"
            out_path.write_bytes(base64.b64decode(b64))
            cprint(f"  ✓ Saved: {out_path}", GREEN)
            subprocess.Popen(["open", str(out_path)])
            return
        cprint("  LocalAI returned no image data.", YELLOW)
    except Exception:
        adwi_say(
            "LocalAI image generation is not running.\n\n"
            "**To enable (one-time setup):**\n"
            "1. `mkdir -p ~/SuneelWorkSpace/localai-models`\n"
            "2. `local-ai --models-path ~/SuneelWorkSpace/localai-models --address :8080`\n"
            "   LocalAI auto-downloads Stable Diffusion on first request (~4GB).\n\n"
            "Then run: `/generate-image " + prompt + "`"
        )

# ── Benchmark ──────────────────────────────────────────────────────────────────
def cmd_benchmark() -> None:
    """Speed and quality benchmark for local models."""
    import time
    adwi_head("Adwi benchmark")

    def _timed(label, fn):
        t0 = time.time(); result = fn(); elapsed = time.time() - t0
        cprint(f"  {GREEN}✓{RESET}  {label}: {elapsed:.2f}s", "")
        return result, elapsed

    _timed("NLU intent classification (qwen3:0.6b)", lambda: classify_intent("what is taking up my disk space"))
    _timed("Embeddings (nomic-embed-text)", lambda: _embed("quick brown fox"))

    msgs = [
        {"role":"system","content":"You are Adwi, a local AI assistant on Suneel's M4 Max Mac."},
        {"role":"user","content":"/no_think\nName 3 planets in one sentence."},
    ]
    req = _ollama_chat(MODEL_MAIN, msgs, stream=False, max_tokens=60)
    t0  = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data    = json.load(r)
        elapsed = time.time() - t0
        tokens  = data.get("eval_count", 0)
        tps     = tokens / elapsed if elapsed > 0 else 0
        content = strip_think(data.get("message",{}).get("content",""))
        cprint(f"  {GREEN}✓{RESET}  Main model ({MODEL_MAIN}): {elapsed:.1f}s · {tps:.1f} tok/s", "")
        cprint(f"     {GRAY}{content[:120]}{RESET}", "")
    except Exception as e:
        cprint(f"  {RED}✗{RESET}  Main model error: {e}", "")

    print()
    cprint(f"  M4 Max target: ≥ 20 tok/s for {MODEL_MAIN}", GRAY)

# ── MCP server status ──────────────────────────────────────────────────────────
_MCP_SERVICE_PORTS = {
    "qdrant":   ("Qdrant",   6333),
    "comfyui":  ("ComfyUI",  8188),
}

def _mcp_live(name: str) -> bool | None:
    """Return True if a live-service MCP can be pinged, None if not checkable."""
    if name not in _MCP_SERVICE_PORTS:
        return None
    _, port = _MCP_SERVICE_PORTS[name]
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False

def cmd_mcp_status() -> None:
    """Show configured MCP tool servers with live-service check."""
    adwi_head("MCP tool servers")
    if not MCP_CONFIG.exists():
        cprint("  No MCP config at ~/.config/mcp/servers.json", YELLOW)
        cprint("  Run: /mcp-setup  to auto-configure MCP servers", GRAY)
        return
    try:
        cfg     = json.loads(MCP_CONFIG.read_text())
        servers = cfg.get("mcpServers", cfg)
        cprint(f"  Config: {MCP_CONFIG}  ({len(servers)} servers)\n", GRAY)
        for name, srv in servers.items():
            desc  = srv.get("description", "")
            live  = _mcp_live(name)
            if live is True:
                dot = f"{GREEN}●{RESET}"
            elif live is False:
                dot = f"{YELLOW}○{RESET}"
            else:
                dot = f"{CYAN}·{RESET}"
            cprint(f"  {dot}  {BOLD}{name}{RESET}  {GRAY}{desc}{RESET}", "")
        cprint(f"\n  {GRAY}● live  · stdio (starts on demand)  ○ service offline{RESET}", "")
        cprint(f"  {GRAY}Config also in ~/.claude/settings.json (Claude Code){RESET}", "")
    except Exception as e:
        cprint(f"  Config error: {e}", RED)

def cmd_mcp_setup() -> None:
    """Write full 10-server MCP config (idempotent — safe to re-run)."""
    import subprocess as _sp
    MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    gh_token = ""
    try:
        gh_token = _sp.check_output(["gh", "auth", "token"], text=True, stderr=_sp.DEVNULL).strip()
    except Exception:
        pass
    config = {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": ["-y", "@playwright/mcp"],
                "description": "Browser automation — navigate, click, screenshot"
            },
            "fetch": {
                "command": "uvx",
                "args": ["mcp-server-fetch"],
                "description": "Fetch and read web URLs as markdown"
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": gh_token},
                "description": "GitHub repos, issues, PRs for suneeluhcl"
            },
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite", "--db-path",
                         str(BASE / "mcp-servers" / "workspace.db")],
                "description": "SQLite workspace DB — notes, tasks, learnings"
            },
            "memory": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-memory"],
                "description": "Persistent knowledge graph across sessions"
            },
            "sequential-thinking": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
                "description": "Step-by-step reasoning for complex problems"
            },
            "qdrant": {
                "command": "uvx",
                "args": ["mcp-server-qdrant"],
                "env": {
                    "QDRANT_URL": "http://localhost:6333",
                    "COLLECTION_NAME": "adwi-knowledge"
                },
                "description": "Qdrant vector DB — semantic search (needs Docker)"
            },
            "comfyui": {
                "command": "uv",
                "args": ["run", "--with", "mcp", "python3",
                         str(BASE / "mcp-servers" / "comfyui-bridge" / "server.py")],
                "description": "ComfyUI image generation (start ComfyUI on :8188 first)"
            },
            "adwi-sandbox": {
                "command": "uv",
                "args": ["run", "--with", "mcp", "python3",
                         str(BASE / "mcp-servers" / "adwi-sandbox" / "server.py")],
                "description": "Adwi workspace tools — run code, notes, git, files"
            },
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", str(BASE)],
                "description": "Read/write files in workspace"
            },
        }
    }
    MCP_CONFIG.write_text(json.dumps(config, indent=2))
    cprint(f"  ✓ MCP config written: {MCP_CONFIG}", GREEN)
    cprint(f"  ✓ {len(config['mcpServers'])} servers configured", GREEN)
    cprint("  These servers work with: Claude Code, Claude Desktop, Open WebUI (MCP mode)", GRAY)
    cmd_mcp_status()

# ── Gmail (read-only) ─────────────────────────────────────────────────────────
def _gmail():
    """Import and return the gmail_helper module."""
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("gmail_helper", ADWI_DIR / "gmail_helper.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def cmd_gmail_auth() -> None:
    """Run one-time OAuth2 browser flow to authorize Gmail access."""
    adwi_head("Gmail authorization")
    cprint("  This will open your browser for Google OAuth2 sign-in.", CYAN)
    cprint("  Scope: READ-ONLY — Adwi cannot send, delete, or modify emails.", GREEN)
    ans = input(f"  {YELLOW}Proceed? (y/n){RESET} ").strip().lower()
    if ans not in ("y","yes"):
        cprint("  Cancelled.", GRAY); return
    try:
        gh = _gmail()
        gh.get_service()
        cprint("  ✓ Gmail authorized. Token saved to secrets/gmail-token.json", GREEN)
        cprint("  Run: /gmail  to see your inbox", GRAY)
    except Exception as e:
        cprint(f"  Auth failed: {e}", RED)
        cprint("  Make sure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are in secrets.local.env", GRAY)

def cmd_gmail(query: str = "", n: int = 10) -> None:
    """Show recent emails, optionally filtered by a search query."""
    adwi_head("Gmail" + (f" — {query}" if query else " — inbox"))
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized yet. Run: /gmail-auth", YELLOW); return
    cprint(f"  {GREEN}●{RESET} Gmail connected (read-only)", "")
    try:
        gh     = _gmail()
        counts = gh.get_label_counts()
        inbox  = counts.get("INBOX", {})
        cprint(f"  Inbox: {inbox.get('total',0):,} total · {inbox.get('unread',0)} unread", GRAY)
        print()
        emails = gh.list_emails(max_results=n, query=query)
        if not emails:
            cprint("  No emails found.", GRAY); return
        for i, em in enumerate(emails, 1):
            sender = em['from'].split('<')[0].strip()[:30]
            cprint(f"  {i:>2}. {BOLD}{em['subject'][:55]}{RESET}", "")
            cprint(f"      {GRAY}From: {sender:<30}  {em['date'][:16]}{RESET}", "")
            cprint(f"      {DIM}{em['snippet'][:90]}{RESET}", "")
            print()
        print(f"  {GRAY}Use /gmail-read <number> to read a full email{RESET}")
        # Store IDs for /gmail-read
        _GMAIL_IDS.clear()
        _GMAIL_IDS.extend(em["id"] for em in emails)
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)
        if "credentials" in str(e).lower() or "token" in str(e).lower():
            cprint("  Try: /gmail-auth  to re-authorize", GRAY)

_GMAIL_IDS: list = []   # ephemeral id list for /gmail-read <n>

def cmd_gmail_read(ref: str) -> None:
    """Read a full email by its list number (from /gmail) or raw message ID."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return
    try:
        gh = _gmail()
        if ref.isdigit():
            idx = int(ref) - 1
            if 0 <= idx < len(_GMAIL_IDS):
                msg_id = _GMAIL_IDS[idx]
            else:
                cprint(f"  No email #{ref} — run /gmail first to list them", YELLOW); return
        else:
            msg_id = ref
        em = gh.read_email(msg_id)
        adwi_head(f"Email: {em['subject']}")
        cprint(f"  From: {em['from']}", CYAN)
        cprint(f"  Date: {em['date']}", GRAY)
        print()
        print(em["body"][:3000])
        if len(em["body"]) > 3000:
            cprint(f"\n  … (truncated — full email is longer)", GRAY)
    except Exception as e:
        cprint(f"  Error reading email: {e}", RED)

def cmd_gmail_summary(query: str = "") -> None:
    """Fetch recent emails and ask Adwi to summarize them."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return
    adwi_head("Gmail summary")
    try:
        gh     = _gmail()
        emails = gh.list_emails(max_results=15, query=query or "is:unread")
        if not emails:
            cprint("  No emails found.", GRAY); return
        digest = "\n\n".join(
            f"Subject: {e['subject']}\nFrom: {e['from']}\nDate: {e['date']}\nSnippet: {e['snippet']}"
            for e in emails
        )
        stream_local(
            f"Summarize these emails for Suneel:\n\n{digest}\n\n"
            "Group by topic/sender. Flag anything urgent or time-sensitive. Be concise.",
            system=(
                "You are Adwi, Suneel's assistant. Summarize emails clearly. "
                "Flag urgent items. Never suggest replying or taking action."
            )
        )
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)

# ── Self-repair / coding-agent commands ──────────────────────────────────────
def _repair():
    """Lazy-load repair.py module (same directory as adwi_cli.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("repair", ADWI_DIR / "repair.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def cmd_fix_error(error_text: str) -> None:
    """Parse a pasted error, identify root cause, patch file, test, log."""
    R = _repair()
    adwi_head("Fix error — self-repair mode")
    activity_start(error_text[:120] if error_text.strip() else "fix error", "Fix Error / Self-Repair")

    if not error_text.strip():
        error_text = input(f"  {CYAN}Paste the error (or describe it):{RESET}\n  ").strip()
    if not error_text:
        cprint("  No error provided.", YELLOW); return

    # 1. Classify
    activity_step("classifying", "identifying error category")
    category, hints = R.classify_error(error_text)
    cprint(f"  Category  : {BOLD}{category}{RESET}", "")
    cprint(f"  Hints     : {GRAY}{' · '.join(hints[:2])}{RESET}", "")

    # 2. Quick syntax check
    activity_step("testing", "syntax check on adwi_cli.py")
    syn_ok, syn_out = R.syntax_check(R.CLI_FILE)
    activity_inspecting(str(R.CLI_FILE))
    if syn_ok and category == "adwi_python":
        cprint(f"  adwi_cli.py syntax is {GREEN}OK{RESET} — error may already be fixed or runtime-only.", "")

    # 3. Gather relevant context files
    files = R.CATEGORY_CONTEXT.get(category, [R.CLI_FILE])
    for f in files:
        activity_inspecting(str(f))

    # 4. Confirm before patching
    cprint(f"\n  [2] Confirm before patching", BOLD)
    cprint(f"  Adwi will inspect relevant files and attempt a safe patch.", GRAY)
    cprint(f"  Backups are saved to: notes/adwi-repair-logs/backups/", GRAY)
    ans = input(f"\n  {YELLOW}Proceed with auto-fix attempt? (y/n):{RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled. No files modified.", GRAY)
        _flush_trace(); return

    # 5. Attempt fix loop
    activity_step("patching", f"AI patch attempt (max 2 retries) for category={category}")
    result = R.fix_error_loop(error_text, category, files, SECRETS_DIR)

    print()
    for step in result["steps"][-8:]:
        cprint(f"  {GRAY}{step}{RESET}", "")

    if result["success"]:
        cprint(f"\n  ✓ Fix applied: {result['patch_applied']}", GREEN, bold=True)
        activity_changed(str(files[0]) if files else str(R.CLI_FILE))

        activity_step("testing", "smoke tests after patch")
        tests = R.run_smoke_tests()
        for t in tests:
            icon = f"{GREEN}✓{RESET}" if t["ok"] else f"{RED}✗{RESET}"
            cprint(f"  {icon} {t['test']}: {t['output'][:80]}", "")

        log_mistake(
            asked=error_text[:200],
            tried=f"Auto-fix via /fix-error, category={category}",
            error=error_text[:300],
            fix=result["patch_applied"],
            rule=f"Classify as '{category}', patch {R.CLI_FILE.name}"
        )
        run_cmd("sync", ["sync-openwebui-knowledge"], quiet=True, timeout=120)
        activity_done(f"Fix applied — {result['patch_applied']}", result['log_path'])
    else:
        cprint(f"\n  ✗ Auto-fix failed: {result['final_error']}", RED, bold=True)
        cprint(f"  {GRAY}Manual hints:{RESET}", "")
        for h in hints:
            cprint(f"    • {h}", GRAY)
        activity_error(f"Auto-fix failed: {result['final_error']}", result['log_path'])
        if result.get("backup"):
            cprint(f"  Backup: {result['backup']}", GRAY)
        _flush_trace()


def cmd_repair_adwi() -> None:
    """Self-check Adwi: syntax, smoke tests, file existence, routing config."""
    R = _repair()
    adwi_head("Repair Adwi — self-diagnostic")
    passed = 0; total = 0

    def _check(label, ok, detail=""):
        nonlocal passed, total
        total += 1
        icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        cprint(f"  {icon} {label}", "")
        if detail and not ok:
            cprint(f"     {GRAY}{detail[:120]}{RESET}", "")
        if ok: passed += 1

    # File existence checks
    cprint(f"\n  [1/4] File checks", BOLD)
    for path in [CLI_FILE, BIN/"adwi", ROUTING_FILE]:
        _check(str(path.relative_to(HOME)), path.exists())

    # Syntax check
    cprint(f"\n  [2/4] Syntax check", BOLD)
    ok, out = R.syntax_check(CLI_FILE)
    _check("python3 -m py_compile adwi_cli.py", ok, out)

    # Routing config check
    cprint(f"\n  [3/4] Routing config", BOLD)
    try:
        r = load_routing()
        model = r.get("ADWI_CLOUD_MODEL","")
        _check(f"cloud model: {model}", bool(model) and "3.5" not in model,
               "model name looks wrong — check model-routing.env" if "3.5" in model else "")
        _check(f"backend: {r.get('ADWI_CHAT_BACKEND','?')}", True)
    except Exception as e:
        _check("routing config", False, str(e))

    # Smoke tests
    cprint(f"\n  [4/4] Smoke tests", BOLD)
    tests = R.run_smoke_tests()
    for t in tests:
        _check(t["test"], t["ok"], t["output"][:100])

    # Summary
    print()
    color = GREEN if passed == total else (YELLOW if passed > total//2 else RED)
    cprint(f"  {passed}/{total} checks passed", color, bold=True)

    if passed < total:
        cprint(f"\n  Run /fix-error <error text> to auto-patch issues.", YELLOW)
        cprint(f"  Or run /self-heal for the full system repair.", GRAY)

    log_action("repair-adwi", f"{passed}/{total} checks passed")


def cmd_patch_adwi(request: str) -> None:
    """
    Apply a user-requested improvement to adwi_cli.py.
    Backs up, patches, tests; rolls back on failure.
    """
    R = _repair()
    adwi_head("Patch Adwi — self-improvement")

    if not request.strip():
        request = input(f"  {CYAN}Describe the improvement:{RESET} ").strip()
    if not request:
        cprint("  No request provided.", YELLOW); return

    cprint(f"  Request: {request}", GRAY)

    # Build context — send last ~200 lines of handle() and the new-commands section
    try:
        src = CLI_FILE.read_text(encoding="utf-8")
    except Exception as e:
        cprint(f"  Cannot read adwi_cli.py: {e}", RED); return

    # Slice around handle() for the most relevant code
    handle_idx = src.find("def handle(line")
    if handle_idx == -1: handle_idx = max(0, len(src) - 6000)
    snippet = src[max(0, handle_idx - 500):handle_idx + 5000]

    prompt = (
        f"Suneel requests this improvement to adwi_cli.py:\n\n"
        f"\"{request}\"\n\n"
        f"Current relevant code:\n```python\n{snippet[:5000]}\n```\n\n"
        "Write a minimal patch that adds/changes the minimum needed.\n"
        "Output ONLY this block:\n\n"
        "<<<PATCH_START>>>\n"
        "FILE: adwi_cli.py\n"
        "REASON: <one line>\n"
        "OLD:\n```python\n<exact current text to replace>\n```\n"
        "NEW:\n```python\n<new replacement text>\n```\n"
        "<<<PATCH_END>>>\n\n"
        "Rules:\n"
        "- OLD must be an exact substring of adwi_cli.py as shown.\n"
        "- Be minimal. Don't refactor unrelated code.\n"
        "- If this improvement is too large to safely auto-apply, output: TOO_COMPLEX\n"
    )

    cprint(f"\n  [1] Requesting patch from AI...", BOLD)
    ai_out = (R.cloud_ask(prompt, SECRETS_DIR) if _cloud_ok() else "") or R.ollama_ask(prompt)

    if "TOO_COMPLEX" in ai_out:
        cprint("  AI says this improvement is too complex to auto-apply safely.", YELLOW)
        cprint("  Suggestion: break it into smaller requests with /patch-adwi.", GRAY)
        return

    patch = R.parse_patch(ai_out)
    if not patch:
        cprint("  Could not parse AI response as a patch.", RED)
        adwi_say(ai_out[:600] if ai_out else "AI returned no output.")
        return

    cprint(f"  Reason   : {patch.get('reason','')}", GRAY)
    cprint(f"  OLD code : {patch['old'][:80]}...", GRAY)

    # Confirm with user
    ans = input(f"\n  {YELLOW}Apply this patch? (y/n):{RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY); return

    cprint(f"\n  [2] Applying patch...", BOLD)
    target = CLI_FILE  # only adwi_cli.py is patchable via this command
    ok, msg, bk = R.apply_patch(target, patch["old"], patch["new"])
    cprint(f"  {GREEN if ok else RED}{msg}{RESET}", "")
    if not ok:
        return

    cprint(f"\n  [3] Syntax check...", BOLD)
    syn_ok, syn_out = R.syntax_check(target)
    if syn_ok:
        cprint(f"  ✓ Syntax OK", GREEN)
        # Update capability registry for any new /commands
        added = R.update_capabilities_json()
        if added:
            cprint(f"  ✓ Added {added} new commands to capabilities.json", GREEN)
        log_journal(f"**Patch applied**\n\nRequest: {request}\n\nPatch: {patch.get('reason','')}")
        run_cmd("sync", ["sync-openwebui-knowledge"], quiet=True, timeout=120)
        cprint(f"\n  ✓ Done. Backup: {bk.name}", GREEN, bold=True)
    else:
        cprint(f"  ✗ Syntax failed: {syn_out}", RED)
        cprint(f"  Restoring backup...", YELLOW)
        R.restore_file(bk, target)
        cprint(f"  ✓ Backup restored — patch rolled back.", GREEN)


def cmd_run_safe(action: str) -> None:
    """Run an allowlisted local helper command."""
    R = _repair()
    if not action.strip():
        adwi_head("Safe command allowlist")
        for key in sorted(R.SAFE_CMDS.keys()):
            cmd = R.SAFE_CMDS[key]
            cprint(f"  {CYAN}·{RESET} {key:<40} {GRAY}{' '.join(cmd) if cmd else '(requires arg)'}{RESET}", "")
        return

    adwi_head(f"Run safe: {action}")
    ok, out = R.run_safe_cmd(action)
    print(out)
    if not ok:
        cprint(f"\n  ✗ Command failed.", RED)
    else:
        cprint(f"\n  ✓ Done.", GREEN)
    log_action(f"run-safe-{action.split()[0]}", out)


def cmd_inspect_code(path_str: str) -> None:
    """Read and explain a source/config file. Respects all safety checks."""
    if not path_str.strip():
        path_str = input(f"  {CYAN}File path:{RESET} ").strip()
    if not path_str:
        cprint("  No path provided.", YELLOW); return

    path = Path(path_str).expanduser()
    if not path.is_absolute():
        # Try workspace-relative first
        candidate = BASE / path_str
        if candidate.exists():
            path = candidate

    ok, reason = safe_to_read(path)
    if not ok:
        cprint(f"  Access denied: {reason}", RED); return
    if not path.exists():
        cprint(f"  File not found: {path}", RED); return

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        cprint(f"  Cannot read: {e}", RED); return

    adwi_head(f"Code inspect: {path.name}")
    lines = content.splitlines()
    cprint(f"  {len(lines)} lines · {len(content)} chars · {path}", GRAY)
    print()

    # Show first 60 lines
    for i, ln in enumerate(lines[:60], 1):
        # Redact any token-looking values
        ln = re.sub(r"(key|token|secret|password)\s*=\s*['\"][^'\"]{8,}['\"]", r"\1=REDACTED", ln, flags=re.I)
        print(f"  {GRAY}{i:4}{RESET}  {ln}")
    if len(lines) > 60:
        cprint(f"\n  ... ({len(lines)-60} more lines) ...", GRAY)

    # AI summary
    print()
    snippet_for_ai = content[:4000]
    summary = call_cloud(
        f"Briefly explain what this file does in 3-5 bullet points:\n\nFile: {path.name}\n\n```\n{snippet_for_ai}\n```"
    ) if _cloud_ok() else quick_local(
        f"What does this file do? File: {path.name}\n\n{snippet_for_ai[:2000]}"
    )
    adwi_say(summary)


def cmd_test_adwi() -> None:
    """Run Adwi smoke tests: compile, help, model-status, status, capabilities."""
    R = _repair()
    adwi_head("Adwi smoke tests")

    tests = R.run_smoke_tests()

    passed = sum(1 for t in tests if t["ok"])
    for t in tests:
        icon = f"{GREEN}✓{RESET}" if t["ok"] else f"{RED}✗{RESET}"
        cprint(f"  {icon}  {t['test']}", "")
        if not t["ok"]:
            cprint(f"     {GRAY}{t['output'][:200]}{RESET}", "")

    print()
    color = GREEN if passed == len(tests) else (YELLOW if passed >= len(tests)//2 else RED)
    cprint(f"  {passed}/{len(tests)} tests passed", color, bold=True)

    if passed == len(tests):
        cprint(f"  All tests passing. Adwi is healthy.", GREEN)
    else:
        cprint(f"  Some tests failed. Run /fix-error <error> or /repair-adwi.", YELLOW)

    log_action("test-adwi", f"{passed}/{len(tests)} passed\n" + "\n".join(
        f"{'PASS' if t['ok'] else 'FAIL'}: {t['test']}" for t in tests
    ))


def cmd_learn_from_last_error() -> None:
    """Review the most recent repair log and record a learning in mistakes journal."""
    R = _repair()
    adwi_head("Learn from last error")

    repair_dir = R.REPAIR_DIR
    if not repair_dir.exists() or not list(repair_dir.glob("*.md")):
        cprint("  No repair logs found yet.", YELLOW)
        cprint("  Run /fix-error <error> first to generate a repair log.", GRAY)
        return

    # Find most recent log
    logs = sorted(repair_dir.glob("*.md"), reverse=True)[:5]
    cprint(f"  Found {len(logs)} recent repair log(s)", GRAY)

    combined = ""
    for log in logs[:2]:
        try:
            combined += f"\n=== {log.name} ===\n{log.read_text(encoding='utf-8')[:1500]}\n"
        except Exception:
            pass

    if not combined:
        cprint("  Could not read repair logs.", RED); return

    # Ask AI to extract learnings
    prompt = (
        f"Review these Adwi repair logs and extract one concise learning entry.\n\n"
        f"{combined}\n\n"
        "Output exactly this format (fill in the blanks):\n\n"
        "## Learning\n\n"
        "**Error:** <one sentence>\n\n"
        "**Cause:** <one sentence>\n\n"
        "**Fix:** <one sentence>\n\n"
        "**Prevention rule:** <one sentence>\n\n"
        "**Test to add:** <one sentence or 'none'>\n"
    )

    cprint(f"\n  Analyzing repair logs...", BOLD)
    learning = call_cloud(prompt) if _cloud_ok() else quick_local(prompt)

    # Append to mistakes file
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {stamp}\n\n{learning.strip()}\n\n---\n"
    with MISTAKES_FILE.open("a", encoding="utf-8") as f:
        f.write(entry)

    # Sync to knowledge
    try:
        (KNOWLEDGE_DIR / "adwi-mistakes-and-fixes.md").write_text(
            MISTAKES_FILE.read_text(encoding="utf-8"), encoding="utf-8"
        )
    except Exception:
        pass

    adwi_say(learning)
    cprint(f"\n  ✓ Saved to {MISTAKES_FILE.name}", GREEN)
    run_cmd("sync", ["sync-openwebui-knowledge"], quiet=True, timeout=120)


def cmd_capabilities_detailed() -> None:
    """Show all capabilities from capabilities.json with full detail."""
    R = _repair()
    # Auto-sync JSON with implemented commands first
    R.update_capabilities_json()

    if not CAPS_FILE.exists():
        cprint("  No capabilities.json found.", YELLOW); return

    try:
        data = json.loads(CAPS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        cprint(f"  Error reading capabilities.json: {e}", RED); return

    caps = data.get("capabilities", [])
    adwi_head(f"Adwi capabilities ({len(caps)} registered · updated {data.get('updated','?')})")

    rc = {"low": GREEN, "medium": YELLOW, "high": RED}
    for c in caps:
        risk    = c.get("risk", "low")
        secrets = "yes" if c.get("uses_secrets") else "no"
        color   = rc.get(risk, GREEN)
        cmd     = c.get("command", "?")
        print(f"  {color}●{RESET}  {BOLD}{cmd:<30}{RESET}  {c.get('description','')[:60]}")
        logs    = c.get("logs","")
        touched = ", ".join(c.get("files_touched",[]))
        test    = c.get("test_command","")
        if logs or touched or test:
            meta = " · ".join(filter(None, [
                f"logs: {logs}" if logs else "",
                f"files: {touched}" if touched else "",
                f"test: {test}" if test else "",
                f"secrets: {secrets}",
            ]))
            cprint(f"     {GRAY}{meta}{RESET}", "")
    print()
    cprint(f"  File: {CAPS_FILE}", GRAY)


def cmd_capability_audit() -> None:
    """Compare capabilities.json against implemented commands. Report gaps."""
    R = _repair()
    adwi_head("Capability audit")

    implemented = set(R.scan_implemented_commands())
    cprint(f"  Found {len(implemented)} implemented commands in adwi_cli.py", GRAY)

    try:
        data = json.loads(CAPS_FILE.read_text(encoding="utf-8")) if CAPS_FILE.exists() else {"capabilities": []}
    except Exception:
        data = {"capabilities": []}

    registered = {}
    for c in data.get("capabilities", []):
        cmd = c.get("command", "").split()[0]
        if cmd:
            registered[cmd] = c.get("description", "")

    # Working: in both
    working = [(cmd, registered.get(cmd, "")) for cmd in implemented if cmd in registered]
    # Implemented but not in JSON
    missing_from_json = [cmd for cmd in implemented if cmd not in registered]
    # In JSON but not in code
    stale = [cmd for cmd in registered if cmd not in implemented]

    cprint(f"\n  {GREEN}✓ Working ({len(working)} capabilities):{RESET}", "")
    for cmd, desc in sorted(working)[:20]:
        cprint(f"    {GRAY}{cmd:<28}{RESET} {desc[:50]}", "")
    if len(working) > 20:
        cprint(f"    ... and {len(working)-20} more", GRAY)

    if missing_from_json:
        cprint(f"\n  {YELLOW}⚠ Implemented but missing from capabilities.json ({len(missing_from_json)}):{RESET}", "")
        for cmd in sorted(missing_from_json):
            cprint(f"    {YELLOW}{cmd}{RESET}", "")
        # Auto-add them
        added = R.update_capabilities_json()
        if added:
            cprint(f"\n  ✓ Auto-added {added} to capabilities.json", GREEN)

    if stale:
        cprint(f"\n  {RED}✗ Stale (in JSON but not implemented) ({len(stale)}):{RESET}", "")
        for cmd in sorted(stale):
            cprint(f"    {RED}{cmd}{RESET}  {registered[cmd][:50]}", "")

    # Suggested next additions
    cprint(f"\n  {CYAN}Recommended next additions:{RESET}", "")
    suggestions = [
        ("/ping         — check if Ollama + services are alive"),
        ("/doctor       — deep health check with auto-fix suggestions"),
        ("/summarize    — summarize any pasted text using cloud AI"),
        ("/context      — show what Adwi remembers about current session"),
    ]
    for s in suggestions:
        cprint(f"    {GRAY}{s}{RESET}", "")

    log_action("capability-audit",
               f"implemented={len(implemented)}, working={len(working)}, "
               f"missing={len(missing_from_json)}, stale={len(stale)}")


# ── Phase 2 — Evals and training data ────────────────────────────────────────
def cmd_eval_routing() -> None:
    """Run NLU routing tests from adwi/evals/routing-tests.jsonl."""
    eval_file = ADWI_DIR / "evals" / "routing-tests.jsonl"
    adwi_head("Routing eval")
    if not eval_file.exists():
        cprint("  No routing-tests.jsonl found.", YELLOW)
        cprint(f"  Expected: {eval_file}", GRAY); return

    tests = []
    for line in eval_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try: tests.append(json.loads(line))
            except Exception: pass

    cprint(f"  {len(tests)} test cases", GRAY)
    passed = 0; failed = []; skipped = 0

    for t in tests:
        user_input = t.get("input", "")
        expected   = t.get("expected_intent", "")
        expected_cmd = t.get("expected_command", "")
        if not user_input:
            skipped += 1; continue

        # Run classifier
        intent_data = classify_intent(user_input)
        got_intent  = intent_data.get("intent", "")

        # Map intent to command (simple mapping)
        INTENT_CMD_MAP = {
            "status": "/status", "self_heal": "/self-heal", "sync": "/sync-knowledge",
            "capabilities": "/capabilities", "daily_improve": "/daily-improve",
            "youtube": "/youtube", "fix_error": "/fix-error", "image": "/image",
            "rag_search": "/rag", "browse": "/browse", "disk_usage": "/disk",
            "large_files": "/large-files", "run_code": "/run-python",
            "git_status": "/git", "gmail": "/gmail", "what_next": "/what-next",
            "generate_image": "/generate-image", "backup": "/backup-now",
        }
        got_cmd = INTENT_CMD_MAP.get(got_intent, f"/{got_intent}")

        ok = (got_intent == expected or got_cmd == expected_cmd)
        if ok:
            passed += 1
        else:
            failed.append({"id": t.get("id","?"), "input": user_input[:50],
                          "expected": expected, "got": got_intent})

    print()
    color = GREEN if passed == len(tests) else (YELLOW if passed >= len(tests)//2 else RED)
    cprint(f"  {passed}/{len(tests)} passed  ({skipped} skipped)", color, bold=True)

    if failed:
        cprint(f"\n  {RED}Failed:{RESET}", "")
        for f in failed[:10]:
            cprint(f"    [{f['id']}] '{f['input']}'  expected={f['expected']}  got={f['got']}", RED)

    # Save results
    result_file = ADWI_DIR / "evals" / f"routing-results-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    result_file.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(), "total": len(tests),
        "passed": passed, "failed": len(failed), "skipped": skipped,
        "failures": failed,
    }, indent=2), encoding="utf-8")
    cprint(f"\n  Results: {result_file.name}", GRAY)
    log_action("eval-routing", f"{passed}/{len(tests)} passed")


def cmd_eval_adwi() -> None:
    """Run full Adwi eval suite: routing + smoke tests + repair check."""
    R = _repair()
    adwi_head("Full Adwi eval suite")

    # 1. Smoke tests
    cprint(f"\n  [1/3] Smoke tests", BOLD)
    tests = R.run_smoke_tests()
    smoke_pass = sum(1 for t in tests if t["ok"])
    for t in tests:
        icon = f"{GREEN}✓{RESET}" if t["ok"] else f"{RED}✗{RESET}"
        cprint(f"  {icon} {t['test']}", "")
    cprint(f"  {smoke_pass}/{len(tests)} smoke tests passed", GREEN if smoke_pass==len(tests) else RED)

    # 2. Routing eval
    cprint(f"\n  [2/3] Routing tests", BOLD)
    cmd_eval_routing()

    # 3. Capability audit
    cprint(f"\n  [3/3] Capability audit", BOLD)
    added = R.update_capabilities_json()
    cprint(f"  Capabilities auto-synced (+{added} new)", GREEN)

    cprint(f"\n  Eval complete — {datetime.now().strftime('%H:%M')}", GREEN, bold=True)
    log_action("eval-adwi", f"smoke={smoke_pass}/{len(tests)}")


def cmd_export_training_example(conversation: str = "") -> None:
    """Append a high-quality interaction to training-data/adwi_interactions.jsonl."""
    data_file = ADWI_DIR / "training-data" / "adwi_interactions.jsonl"
    adwi_head("Export training example")
    if not conversation.strip():
        cprint("  Paste the conversation (user → assistant) below.", GRAY)
        cprint("  Format: USER: <text>\\n\\nASSISTANT: <text>", GRAY)
        conversation = input(f"  {CYAN}>{RESET} ").strip()
    if not conversation:
        cprint("  Nothing to export.", YELLOW); return

    # Simple parse
    user_part = re.search(r"(?i)USER:\s*(.+?)(?=ASSISTANT:|$)", conversation, re.S)
    asst_part = re.search(r"(?i)ASSISTANT:\s*(.+?)$", conversation, re.S)
    user_msg = user_part.group(1).strip() if user_part else conversation
    asst_msg = asst_part.group(1).strip() if asst_part else ""

    # Redact secrets
    asst_msg = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "REDACTED", asst_msg)
    asst_msg = re.sub(r"eyJ[A-Za-z0-9_-]{20,}", "JWT-REDACTED", asst_msg)

    entry = {
        "id": f"t{data_file.stat().st_size // 100 + 1:03d}" if data_file.exists() else "t001",
        "messages": [
            {"role": "user",      "content": user_msg},
            {"role": "assistant", "content": asst_msg},
        ],
        "quality": "user-approved",
        "source": "adwi_export",
        "redacted": True,
    }
    with data_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    count = sum(1 for line in data_file.read_text(encoding="utf-8").splitlines() if line.strip())
    cprint(f"  ✓ Example saved. Total training examples: {count}", GREEN)
    cprint(f"  File: {data_file}", GRAY)


def cmd_training_plan() -> None:
    """Explain current training data status and fine-tuning readiness."""
    adwi_head("Training plan")
    data_file = ADWI_DIR / "training-data" / "adwi_interactions.jsonl"
    count = 0
    if data_file.exists():
        count = sum(1 for line in data_file.read_text(encoding="utf-8").splitlines() if line.strip())

    cprint(f"\n  Current training examples: {count}", CYAN if count else YELLOW)
    cprint(f"  File: {data_file}", GRAY)

    thresholds = [
        (0,    "No data — using RAG/memory for self-improvement (correct path for now)"),
        (50,   "Early stage — too few for reliable fine-tuning"),
        (200,  "Minimum viable — could test LoRA on small model"),
        (1000, "Adequate for narrow intent-routing fine-tune"),
        (5000, "Ready for meaningful fine-tune of 7B–30B model"),
    ]
    label = thresholds[0][1]
    for threshold, msg in thresholds:
        if count >= threshold:
            label = msg

    cprint(f"\n  Status: {label}", GRAY)
    cprint(f"\n  {BOLD}Self-improvement strategy (current phase):{RESET}", "")
    strategy = [
        "✓  RAG/Knowledge updates — working (64 docs indexed)",
        "✓  Mistake journal — active (adwi-mistakes-and-fixes.md)",
        "✓  Capability registry — active (capabilities.json)",
        "✓  Daily evals — /daily-improve runs tests + journal",
        "✓  Routing evals — /eval-routing tests 30 NLU cases",
        "○  Training data export — /export-training-example (use to grow dataset)",
        "○  Fine-tuning — NOT yet recommended (need 1000+ quality examples)",
        "○  Unsloth LoRA — add to roadmap when data threshold reached",
    ]
    for s in strategy:
        cprint(f"    {s}", GRAY if s.startswith("○") else GREEN)

    cprint(f"\n  Grow training data with: /export-training-example", CYAN)
    cprint(f"  Target: 1000 examples before attempting fine-tuning.", GRAY)


# ── Phase 3 — System inspection ───────────────────────────────────────────────
def _check_port(port: int, timeout: float = 1.5) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False

def cmd_inspect_system(save: bool = True) -> str:
    """Full read-only inventory of the local AI system. Saves report to notes/."""
    adwi_head("System inspection")
    lines = [f"# Adwi System Inspection\n\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]

    def section(title): lines.append(f"\n## {title}"); cprint(f"  {title}...", GRAY)
    def row(k, v): lines.append(f"- **{k}:** {v}")
    def ok_row(k, ok, detail=""):
        icon = "✓" if ok else "✗"
        lines.append(f"- {icon} **{k}:** {detail}")
        cprint(f"    {GREEN+'✓' if ok else RED+'✗'}{RESET} {k}: {detail[:60]}", "")

    # macOS
    section("System")
    row("OS", run_shell("sw_vers -productVersion 2>/dev/null"))
    row("Architecture", run_shell("uname -m 2>/dev/null"))
    row("Hostname", run_shell("hostname -s 2>/dev/null"))
    cpu = run_shell("sysctl -n machdep.cpu.brand_string 2>/dev/null")
    row("CPU", cpu[:80])
    ram = run_shell("sysctl -n hw.memsize 2>/dev/null")
    try: row("RAM", f"{int(ram)//1024//1024//1024}GB")
    except: row("RAM", ram[:20])
    disk = run_shell("df -h / 2>/dev/null | tail -1")
    row("Disk /", disk[:80])
    row("PATH", os.environ.get("PATH","")[:120])

    # Homebrew
    section("Homebrew")
    brew_v = run_shell("brew --version 2>/dev/null | head -1")
    ok_row("brew", bool(brew_v and "Homebrew" in brew_v), brew_v[:40])
    for pkg in ["git", "gh", "node", "python3", "docker", "ollama", "uv", "ffmpeg"]:
        v = run_shell(f"{pkg} --version 2>/dev/null | head -1")
        ok_row(pkg, bool(v and "not found" not in v), v[:50])

    # Python
    section("Python")
    row("python3", run_shell("python3 --version 2>/dev/null"))
    row("pip3", run_shell("pip3 --version 2>/dev/null | head -1"))
    row("uv", run_shell("uv --version 2>/dev/null"))
    row("uvx", run_shell("uvx --version 2>/dev/null"))

    # Node/npm
    section("Node / npm / npx")
    row("node", run_shell("node --version 2>/dev/null"))
    row("npm", run_shell("npm --version 2>/dev/null"))
    row("npx", run_shell("npx --version 2>/dev/null"))

    # Docker
    section("Docker")
    docker_v = run_shell("docker --version 2>/dev/null")
    ok_row("docker", bool(docker_v and "Docker" in docker_v), docker_v[:60])
    containers = run_shell("docker ps --format '{{.Names}} ({{.Status}})' 2>/dev/null")
    if containers:
        for c in containers.splitlines():
            lines.append(f"  - {c}")
    else:
        lines.append("  - No running containers")

    # AI Services
    section("AI Services")
    services = [
        ("Ollama",     11434), ("Open WebUI", 3000),
        ("n8n",        5678),  ("SearXNG",    8888),
        ("Safe API",   5055),  ("Qdrant",     6333),
        ("LocalAI",    8080),  ("ComfyUI",    8188),
    ]
    for name, port in services:
        up = _check_port(port)
        ok_row(f"{name} :{port}", up, "online" if up else "offline")

    # Ollama models
    section("Ollama Models")
    models_out = run_shell("ollama list 2>/dev/null")
    for ln in models_out.splitlines()[1:]:
        if ln.strip(): lines.append(f"  - {ln.strip()}")

    # Adwi files
    section("Adwi Files")
    for f in [CLI_FILE, BIN/"adwi", ROUTING_FILE, CAPS_FILE, ADWI_DIR/"repair.py", ADWI_DIR/"backup.py"]:
        exists = f.exists()
        size = f"{f.stat().st_size//1024}KB" if exists else "—"
        ok_row(str(f.relative_to(HOME)), exists, size)

    # Model routing
    section("Model Routing")
    try:
        r = load_routing()
        row("backend", r.get("ADWI_CHAT_BACKEND","?"))
        row("cloud model", r.get("ADWI_CLOUD_MODEL","?"))
        row("local model", r.get("ADWI_LOCAL_MODEL","?"))
    except Exception as e:
        lines.append(f"- Error reading routing: {e}")

    # MCP servers
    section("MCP Servers")
    if MCP_CONFIG.exists():
        try:
            mcp = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
            servers = mcp.get("mcpServers", {})
            row("Configured servers", len(servers))
            for name in servers:
                lines.append(f"  - {name}")
        except Exception:
            lines.append("  - Error reading MCP config")

    # bin/ scripts
    section("Bin Scripts")
    if BIN.exists():
        scripts = sorted(BIN.iterdir())
        for s in scripts:
            if s.is_file():
                ok_row(s.name, os.access(s, os.X_OK), "executable" if os.access(s, os.X_OK) else "not executable")

    # Secrets (names only — never values)
    section("Secrets (names only)")
    try:
        env_file = SECRETS_DIR / "secrets.local.env"
        if env_file.exists():
            for ln in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in ln and not ln.startswith("#"):
                    key = ln.split("=", 1)[0].strip()
                    if key:
                        lines.append(f"  - {key}: [REDACTED]")
        else:
            lines.append("  - secrets.local.env not found")
    except Exception:
        lines.append("  - Cannot read secrets directory")

    # Git backup status
    section("Git Backup")
    try:
        B = _backup()
        gs = B.get_git_status()
        ok_row("git repo", gs["is_repo"], gs.get("branch",""))
        if gs["is_repo"]:
            row("remote", gs.get("remote_url","none"))
            row("last commit", gs.get("last_commit","none")[:80])
            row("pending files", len(gs.get("pending_files",[])))
    except Exception as e:
        lines.append(f"  - Error: {e}")

    # Action log summary
    section("Action Log Summary")
    log_count = len(list(LOG_DIR.glob("*.md"))) if LOG_DIR.exists() else 0
    row("Total action logs", log_count)
    repair_dir = NOTES / "adwi-repair-logs"
    repair_count = len(list(repair_dir.glob("*.md"))) if repair_dir.exists() else 0
    row("Repair logs", repair_count)

    # RAG index
    section("RAG Index")
    rag_file = ADWI_DIR / "rag-db" / "notes-index.json"
    if rag_file.exists():
        try:
            rag = json.loads(rag_file.read_text(encoding="utf-8"))
            row("Documents indexed", len(rag.get("docs",[])))
        except Exception:
            row("Index", "error reading")
    else:
        row("Index", "not built — run /rag-index")

    # Assemble report
    report = "\n".join(lines)

    # Save
    if save:
        out_dir = NOTES / "system-inspections"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_file = out_dir / f"{stamp}-adwi-system-inspection.md"
        out_file.write_text(report, encoding="utf-8")
        cprint(f"\n  Report saved: {out_file.name}", GRAY)
        log_action("inspect-system", f"saved to {out_file.name}")

    return report


def cmd_doctor() -> None:
    """Inspect system, then AI-diagnose issues and suggest exact Adwi fixes."""
    adwi_head("Doctor — system health analysis")
    cprint("  Running full system inspection...", GRAY)
    report = cmd_inspect_system(save=True)

    cprint(f"\n  Analyzing with AI...", BOLD)
    prompt = (
        f"You are Adwi's doctor. Review this system inspection report and produce:\n\n"
        f"1. ✓ What is healthy\n"
        f"2. ✗ What is missing or broken\n"
        f"3. ⚠ What is stale or suboptimal\n"
        f"4. 🔧 Exact Adwi built-in commands to fix each issue\n"
        f"5. 📋 Top 3 recommended next improvements\n\n"
        f"Be specific — name the exact /command to run for each fix.\n"
        f"Do NOT suggest manual terminal commands if an Adwi command exists.\n\n"
        f"Report:\n{report[:6000]}"
    )
    diagnosis = call_cloud(prompt) if _cloud_ok() else stream_local(prompt)
    adwi_say(diagnosis)
    log_action("doctor", diagnosis[:500])


def cmd_trusted_roots() -> None:
    """Show current trusted read roots."""
    adwi_head("Trusted read roots")
    if not ROOTS_FILE.exists():
        cprint("  No allowed-read-roots.txt found.", YELLOW); return
    roots = [r for r in ROOTS_FILE.read_text(encoding="utf-8").splitlines() if r.strip()]
    cprint(f"  {len(roots)} trusted paths:\n", GRAY)
    for r in roots:
        exists = Path(r).exists()
        icon = f"{GREEN}✓{RESET}" if exists else f"{YELLOW}?{RESET}"
        cprint(f"  {icon}  {r}", "")


# ── Phase 4 — Idea extraction and implementation ──────────────────────────────
def cmd_extract_ideas(src: str = "") -> None:
    """Extract implementable ideas from a URL, file, or pasted text."""
    adwi_head("Extract ideas")
    if not src.strip():
        src = input(f"  {CYAN}Source (URL, file path, or paste text):{RESET}\n  ").strip()
    if not src:
        cprint("  Nothing provided.", YELLOW); return

    content = ""
    if src.startswith("http"):
        cprint(f"  Fetching {src[:60]}...", GRAY)
        content = run_shell(f"curl -sL --max-time 15 '{src}' 2>/dev/null | head -c 8000") or ""
        if not content.strip():
            content = src  # fallback: pass URL to AI
    elif Path(src).expanduser().exists():
        p = Path(src).expanduser()
        ok, reason = safe_to_read(p)
        if not ok:
            cprint(f"  Access denied: {reason}", RED); return
        content = p.read_text(encoding="utf-8", errors="replace")[:6000]
    else:
        content = src  # treat as inline text

    prompt = (
        f"Extract actionable ideas from this source that could improve my local AI setup (Adwi on M4 Max Mac).\n\n"
        f"Source:\n{content[:5000]}\n\n"
        f"For each idea output:\n"
        f"## Idea N: <title>\n"
        f"**What:** <one sentence>\n"
        f"**Why it helps Adwi:** <one sentence>\n"
        f"**Effort:** low/medium/high\n"
        f"**Adwi command to implement:** <existing command or '/patch-adwi <description>'>\n\n"
        f"Focus on things that realistically apply to my setup. Skip theoretical ideas."
    )
    cprint(f"\n  Extracting ideas...", BOLD)
    ideas = call_cloud(prompt) if _cloud_ok() else stream_local(prompt)
    adwi_say(ideas)

    # Save to notes
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ideas_dir = NOTES / "task-plans"
    ideas_dir.mkdir(exist_ok=True)
    out = ideas_dir / f"{stamp}-extracted-ideas.md"
    out.write_text(f"# Extracted Ideas\n\nSource: {src[:100]}\nDate: {datetime.now()}\n\n{ideas}", encoding="utf-8")
    cprint(f"\n  Ideas saved: {out.name}", GRAY)
    log_action("extract-ideas", ideas[:300])


def cmd_implement_idea(src: str = "") -> None:
    """Summarize an idea, build a safe implementation plan, then apply with confirmation."""
    adwi_head("Implement idea")
    if not src.strip():
        src = input(f"  {CYAN}Idea source (URL, file, or describe the idea):{RESET}\n  ").strip()
    if not src:
        cprint("  Nothing provided.", YELLOW); return

    # Get idea content
    content = src
    if src.startswith("http"):
        content = run_shell(f"curl -sL --max-time 15 '{src}' 2>/dev/null | head -c 5000") or src

    # Build plan
    cprint(f"\n  [1] Building implementation plan...", BOLD)
    plan_prompt = (
        f"Suneel wants to implement this idea in his local AI setup (Adwi on M4 Max Mac).\n\n"
        f"Idea:\n{content[:4000]}\n\n"
        f"Create a concrete implementation plan:\n"
        f"## Summary\n<2 sentences>\n\n"
        f"## Does this apply to my setup?\n<yes/no + reason>\n\n"
        f"## Implementation steps\n"
        f"<numbered list using only Adwi commands or safe file changes>\n\n"
        f"## What files would change\n<list specific files>\n\n"
        f"## Risk level\n<low/medium/high + reason>\n\n"
        f"## Estimated effort\n<time estimate>\n\n"
        f"Only propose changes inside /Users/MAC/SuneelWorkSpace. No sudo. No secrets."
    )
    plan = call_cloud(plan_prompt) if _cloud_ok() else stream_local(plan_prompt)
    adwi_say(plan)

    # Save plan
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    plans_dir = NOTES / "task-plans"
    plans_dir.mkdir(exist_ok=True)
    plan_file = plans_dir / f"{stamp}-implement-plan.md"
    plan_file.write_text(f"# Implementation Plan\n\nIdea: {src[:100]}\nDate: {datetime.now()}\n\n{plan}", encoding="utf-8")
    cprint(f"\n  Plan saved: {plan_file.name}", GRAY)

    # Offer to proceed
    ans = input(f"\n  {YELLOW}Proceed with this plan? (y/n):{RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Plan saved. Review and use /patch-adwi when ready.", GRAY); return

    # Delegate to patch-adwi for safe execution
    cprint(f"\n  [2] Delegating to /patch-adwi...", BOLD)
    summary = plan.split("\n")[0][:200]
    cmd_patch_adwi(f"Implement this plan from implement-idea: {summary}")


# ── Phase 5 — Tool roadmap ────────────────────────────────────────────────────
def cmd_tool_roadmap() -> None:
    """Show Phase 5 tool stack roadmap with install status."""
    adwi_head("Tool stack roadmap")
    TOOLS = [
        ("LangGraph / LangChain", "Agent workflows, NLU routing, self-repair graphs",
         "planned", "pip install langgraph langchain"),
        ("LlamaIndex",            "Advanced document/RAG indexing",
         "planned", "pip install llama-index"),
        ("Qdrant",                "Local vector memory DB",
         "active",  "docker run suneel-qdrant (running on :6333)"),
        ("ChromaDB",              "Simpler local vector DB for experiments",
         "planned", "pip install chromadb"),
        ("SQLite memory DB",      "Structured local memory / eval results",
         "active",  "mcp-servers/workspace.db"),
        ("Memory MCP",            "Persistent knowledge graph",
         "active",  "npx @modelcontextprotocol/server-memory"),
        ("Sequential Thinking MCP","Structured reasoning for complex tasks",
         "active",  "npx @modelcontextprotocol/server-sequential-thinking"),
        ("Fetch MCP",             "Web content retrieval",
         "active",  "uvx mcp-server-fetch"),
        ("Playwright MCP",        "Browser automation/testing",
         "active",  "npx @playwright/mcp"),
        ("GitHub MCP",            "Repo/issues/PR/code search",
         "active",  "npx @modelcontextprotocol/server-github (token set)"),
        ("Filesystem MCP",        "Controlled filesystem tools",
         "active",  "npx @modelcontextprotocol/server-filesystem"),
        ("Langfuse",              "LLM observability/tracing/eval",
         "planned", "docker pull langfuse/langfuse OR pip install langfuse"),
        ("Local eval system",     "Routing/RAG/repair regression tests",
         "active",  "/eval-routing (30 cases), /eval-adwi"),
        ("Unsloth + LoRA/QLoRA",  "Future fine-tuning (1000+ examples needed first)",
         "planned", "pip install unsloth — NOT YET, need more training data"),
        ("Adwi code sandbox",     "Safe code execution (isolated)",
         "active",  "mcp-servers/adwi-sandbox (8 tools)"),
        ("ComfyUI",               "Local image generation",
         "planned", "git clone https://github.com/comfyanonymous/ComfyUI"),
        ("Open WebUI Knowledge",  "Automatic knowledge sync to browser UI",
         "active",  "bin/sync-openwebui-knowledge + watcher running"),
    ]
    STATUS_COLORS = {"active": GREEN, "planned": YELLOW, "partial": CYAN}
    print()
    for name, desc, status, install in TOOLS:
        color = STATUS_COLORS.get(status, GRAY)
        dot = "●" if status == "active" else "○"
        cprint(f"  {color}{dot}{RESET}  {BOLD}{name}{RESET}", "")
        cprint(f"     {GRAY}{desc}{RESET}", "")
        if status != "active":
            cprint(f"     {GRAY}Install: {install[:80]}{RESET}", "")
    print()
    cprint(f"  ● = active  ○ = planned  (use /patch-adwi to install any planned tool)", GRAY)
    if ROADMAP_FILE.exists():
        cprint(f"  Full roadmap: {ROADMAP_FILE}", GRAY)


# ── Phase 6 — GitHub backup ───────────────────────────────────────────────────
def _backup():
    """Lazy-load backup.py module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("backup", ADWI_DIR / "backup.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_backup_status() -> None:
    """Show workspace git / backup status."""
    B = _backup()
    adwi_head("Backup status")
    gs = B.get_git_status()

    if not gs["is_repo"]:
        cprint(f"  {YELLOW}Not a git repository{RESET}", "")
        cprint(f"  Run /backup-enable to initialize git and set up auto-backup.", GRAY)
        return

    ok = lambda v: f"{GREEN}✓{RESET}" if v else f"{RED}✗{RESET}"
    cprint(f"  {ok(True)} Git repo initialized", "")
    cprint(f"  {ok(bool(gs['branch']))} Branch: {gs['branch'] or '?'}", "")
    cprint(f"  {ok(bool(gs['remote_url']))} Remote: {gs['remote_url'] or 'none'}", "")
    cprint(f"  {ok(bool(gs['last_commit']))} Last commit: {gs['last_commit'][:60] or 'none'}", "")
    cprint(f"  {ok(gs['ahead'] == 0)} Ahead of remote: {gs['ahead']} commit(s)", "")
    pending = gs.get("pending_files", [])
    cprint(f"  {'·' if not pending else YELLOW+'·'+RESET}  Pending changes: {len(pending)} file(s)", "")
    for p in pending[:5]:
        cprint(f"     {GRAY}{p}{RESET}", "")
    if len(pending) > 5:
        cprint(f"     {GRAY}... and {len(pending)-5} more{RESET}", "")

    la_status = B.get_launchagent_status()
    la_ok = la_status == "installed"
    cprint(f"\n  {ok(la_ok)} Auto-backup LaunchAgent: {la_status}", "")

    # Secret scan check
    gi = BASE / ".gitignore"
    missing = B.check_gitignore_covers_secrets()
    cprint(f"  {ok(not missing)} .gitignore covers secrets: {'yes' if not missing else 'missing: '+', '.join(missing[:3])}", "")


def cmd_backup_now(message: str = "") -> None:
    """Run a full backup: secret scan → stage safe files → commit → push."""
    B = _backup()
    adwi_head("Backup now")
    activity_start(message or "backup workspace to GitHub", "GitHub Backup")

    cprint(f"  This will commit and push safe Adwi files to GitHub.", GRAY)
    cprint(f"  Secrets, credentials, and runtime data are excluded.", GRAY)
    cprint(f"  Secret scan runs before every commit.", GRAY)
    ans = input(f"\n  {YELLOW}Proceed with backup? (y/n):{RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY); _flush_trace(); return

    activity_step("running", "init git repo + workspace files")
    ok_init, init_msg = B.init_git_repo()
    cprint(f"  {'✓' if ok_init else '✗'} {init_msg}", GREEN if ok_init else RED)

    activity_step("staging", "safe allowlisted files only")
    n, staged = B.stage_safe_files()
    cprint(f"  ✓ Staged {n} path(s)", GREEN)

    activity_step("scanning", "secret scan on staged diff")
    secrets = B.scan_staged_for_secrets()
    if secrets:
        B._git(["reset", "HEAD"])
        cprint(f"  {RED}✗ Secret scan FAILED — aborting.{RESET}", "")
        for s in secrets:
            cprint(f"     {YELLOW}Found: {s['pattern']} in {s['file']}{RESET}", "")
        activity_error("Secret scan blocked the commit — no files modified")
        _flush_trace(); return

    activity_step("committing", "signing off and pushing to GitHub")
    result = B.do_backup(message or f"adwi backup {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if result["success"]:
        cprint(f"\n  {GREEN}✓ {result['message']}{RESET}", "", bold=True)
        if not result.get("pushed"):
            cprint(f"\n  {YELLOW}No remote configured.{RESET}", "")
            cprint(f"    gh repo create suneel-local-ai-adwi --private --source=. --push", CYAN)
    else:
        cprint(f"\n  {RED}✗ Backup failed: {result['message']}{RESET}", "")

    log_path = B.write_backup_log(result)
    log_action("backup-now", result.get("message",""))
    if result["success"]:
        activity_done(result["message"], log_path)
    else:
        activity_error(result["message"], log_path)
        _flush_trace()


def cmd_backup_enable() -> None:
    """Initialize git repo + LaunchAgent for automatic backup every 30 minutes."""
    B = _backup()
    adwi_head("Enable auto-backup")
    cprint(f"  This will:", GRAY)
    cprint(f"    1. Initialize git in {BASE}", GRAY)
    cprint(f"    2. Write .gitignore, README.md, BACKUP_MANIFEST.md", GRAY)
    cprint(f"    3. Install LaunchAgent (runs backup every 30 min)", GRAY)
    cprint(f"    4. Perform initial backup", GRAY)
    cprint(f"\n  Secrets, runtime data, and model files will be excluded.", GRAY)
    ans = input(f"\n  {YELLOW}Enable auto-backup? (y/n):{RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY); return

    cprint(f"\n  [1/4] Initializing git repo...", BOLD)
    ok, msg = B.init_git_repo()
    cprint(f"  {'✓' if ok else '✗'} {msg}", GREEN if ok else RED)

    cprint(f"\n  [2/4] Writing workspace files...", BOLD)
    written = B.write_workspace_files()
    for w in written:
        cprint(f"  ✓ {w}", GREEN)

    cprint(f"\n  [3/4] Installing LaunchAgent...", BOLD)
    la_ok, la_msg = B.create_launchagent()
    cprint(f"  {'✓' if la_ok else '✗'} {la_msg}", GREEN if la_ok else YELLOW)

    cprint(f"\n  [4/4] Initial backup...", BOLD)
    n, staged = B.stage_safe_files()
    secrets = B.scan_staged_for_secrets()
    if secrets:
        B._git(["reset", "HEAD"])
        cprint(f"  {RED}✗ Secret scan failed — fix .gitignore and run /backup-now{RESET}", "")
    else:
        result = B.do_backup("initial adwi setup backup")
        cprint(f"  {'✓' if result['success'] else '✗'} {result['message']}", GREEN if result["success"] else YELLOW)
        B.write_backup_log(result)

    cprint(f"\n  {GREEN}Auto-backup enabled.{RESET} Runs every 30 min.", "", bold=True)
    cprint(f"  To push to GitHub: gh repo create suneel-local-ai-adwi --private --source=. --push", CYAN)
    cprint(f"  Disable anytime: /backup-disable", GRAY)


def cmd_backup_disable() -> None:
    """Disable the auto-backup LaunchAgent."""
    B = _backup()
    adwi_head("Disable auto-backup")
    ok, msg = B.remove_launchagent()
    cprint(f"  {'✓' if ok else '✗'} {msg}", GREEN if ok else YELLOW)


def cmd_backup_log() -> None:
    """Show recent backup logs."""
    B = _backup()
    adwi_head("Backup logs")
    log_dir = B.BACKUP_LOG_DIR
    if not log_dir.exists() or not list(log_dir.glob("*.md")):
        cprint("  No backup logs yet. Run /backup-now first.", YELLOW); return
    logs = sorted(log_dir.glob("*.md"), reverse=True)[:10]
    cprint(f"  {len(logs)} recent logs:\n", GRAY)
    for log in logs:
        try:
            content = log.read_text(encoding="utf-8")
            status = "SUCCESS" if "SUCCESS" in content else "FAILED"
            commit_line = next((l for l in content.splitlines() if l.startswith("##") and "Commit" not in l), "")
            color = GREEN if status == "SUCCESS" else RED
            cprint(f"  {color}{'✓' if status == 'SUCCESS' else '✗'}{RESET}  {log.stem}  {commit_line[:50]}", "")
        except Exception:
            cprint(f"  · {log.name}", GRAY)


def cmd_backup_audit() -> None:
    """Show exactly what is included/excluded from GitHub backup."""
    B = _backup()
    adwi_head("Backup audit")
    cprint(f"  Workspace: {BASE}\n", GRAY)

    cprint(f"  {GREEN}INCLUDED in backup:{RESET}", "")
    included = [
        "adwi/*.py, *.env, *.txt, *.json, Modelfile",
        "adwi/evals/, adwi/training-data/",
        "bin/adwi, bin/mcp-status, bin/adwi-git-backup",
        "mcp-servers/adwi-sandbox/server.py, comfyui-bridge/server.py",
        "notes/ADWI-START-HERE.md, START-HERE-SUNEEL-LOCAL-AI.md",
        "notes/adwi-learning-journal.md, adwi-mistakes-and-fixes.md",
        "notes/adwi-capability-roadmap.md",
        "notes/adwi-repair-logs/*.md (reports, not backups/)",
        "notes/system-inspections/",
        "notes/git-backup-logs/",
        "local-ai-stack/docker-compose.yml",
        ".gitignore, README.md, BACKUP_MANIFEST.md",
    ]
    for item in included:
        cprint(f"    {GREEN}·{RESET} {item}", "")

    cprint(f"\n  {RED}EXCLUDED (never committed):{RESET}", "")
    excluded = [
        "secrets/ — API keys, tokens, credentials",
        "**/.env, **/secrets.local.env — env files with secrets",
        "**/*token*, **/*secret*, **/*key* — credential files",
        "local-ai-stack/open-webui-data/ — runtime database",
        "local-ai-stack/n8n-data/ — n8n runtime data",
        "mcp-servers/qdrant-data/ — vector DB runtime data",
        "notes/adwi-action-logs/ — high-volume logs",
        "notes/adwi-repair-logs/backups/ — large file backups",
        "notes/clipboard-command-logs/ — clipboard history",
        "*.gguf, *.safetensors, *.bin — model files",
        "__pycache__/, node_modules/, .venv/ — generated artifacts",
        ".DS_Store — macOS metadata",
    ]
    for item in excluded:
        cprint(f"    {RED}·{RESET} {item}", "")

    # Check gitignore status
    gi = BASE / ".gitignore"
    missing = B.check_gitignore_covers_secrets()
    cprint(f"\n  .gitignore: {'exists ✓' if gi.exists() else 'MISSING — run /backup-enable'}", GREEN if gi.exists() else RED)
    if missing:
        cprint(f"  {YELLOW}Missing gitignore entries: {', '.join(missing)}{RESET}", "")

    # Check secret scan patterns
    cprint(f"\n  Secret scan patterns ({len(B.SECRET_PATTERNS)}):", GRAY)
    for _, label in B.SECRET_PATTERNS:
        cprint(f"    · {label}", GRAY)

    # Secret scan on currently staged files
    gs = B.get_git_status()
    if gs.get("is_repo"):
        cprint(f"\n  Running secret scan on staged files...", GRAY)
        findings = B.scan_staged_for_secrets()
        if findings:
            cprint(f"  {RED}✗ Potential secrets found in staged files:{RESET}", "")
            for f in findings:
                cprint(f"    {YELLOW}{f['file']}: {f['pattern']}{RESET}", "")
        else:
            cprint(f"  {GREEN}✓ No secrets detected in staged files{RESET}", "")


# ── Memory Layer commands ─────────────────────────────────────────────────────

def _memory_mod():
    """Lazy-load adwi/memory.py so adwi_cli.py stays independent of it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("adwi_memory", ADWI_DIR / "memory.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_memory_scan() -> None:
    """Index terminal history, git commits, and notes into the memory ledger."""
    adwi_head("Memory scan — indexing workflow into semantic ledger")
    activity_start("scan terminal + git + notes for memories", "Memory Scan")
    try:
        mod = _memory_mod()
        mem = mod.AdwiMemory()
        activity_step("scanning", "terminal history (~400 recent commands)")
        t = mem.scan_terminal()
        activity_step("scanning", "git commit log (last 60)")
        g = mem.scan_git_commits()
        activity_step("scanning", "notes/ markdown files")
        n = mem.scan_notes()
        s = mem.stats()
        mem.close()
        msg = f"+{t} terminal  +{g} git  +{n} notes — ledger total: {s['total']}"
        activity_done(msg)
        cprint(f"  ✓ {msg}", GREEN)
        cprint(f"  DB: {mod.DB_PATH}", GRAY)
    except Exception as e:
        activity_error(str(e))
        cprint(f"  ✗ Memory scan failed: {e}", RED)


def cmd_memory_recall(query: str = "") -> None:
    """Semantic search over memory ledger AND Obsidian vault markdown files."""
    if not query:
        query = input(f"  {CYAN}Recall query:{RESET} ").strip()
    if not query:
        return
    adwi_head(f"Memory recall: {query[:60]}")
    activity_start(f"recall: {query[:60]}", "Memory Recall")
    total = 0

    # ── Layer 1: memory.db ledger ─────────────────────────────────────────────
    try:
        mod  = _memory_mod()
        mem  = mod.AdwiMemory()
        hits = mem.recall(query)
        if not hits:
            hits = mem.recall_keyword(query)
        mem.close()
        if hits:
            cprint(f"\n  {CYAN}── Memory Ledger ──{RESET}", "")
            for h in hits:
                score = f"{h['score']:.2f}" if h["score"] > 0 else " kw"
                cprint(f"  [{score}] {h['source']:8s} {h['ts'][:10]}  {h['content'][:120]}", CYAN)
            total += len(hits)
    except Exception as e:
        cprint(f"  ⚠ ledger error: {e}", YELLOW)

    # ── Layer 2: knowledge.db Q&A pairs ──────────────────────────────────────
    try:
        import sqlite3, math
        kdb = ADWI_DIR / "knowledge.db"
        if kdb.exists():
            qemb = _embed(query)
            if qemb:
                def _cos(a, b):
                    d = sum(x*y for x,y in zip(a,b))
                    return d / (math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(x*x for x in b)) + 1e-9)
                con  = sqlite3.connect(str(kdb))
                rows = con.execute(
                    "SELECT question, answer, file_path, embedding FROM qa_pairs "
                    "WHERE embedding IS NOT NULL LIMIT 2000"
                ).fetchall()
                con.close()
                scored = sorted(
                    [(row, _cos(qemb, json.loads(row[3]))) for row in rows],
                    key=lambda x: x[1], reverse=True,
                )
                top = [(r, s) for r, s in scored[:5] if s >= 0.35]
                if top:
                    cprint(f"\n  {GREEN}── Knowledge DB Q&A ──{RESET}", "")
                    for (q_text, a_text, fp, _), score in top:
                        cprint(f"  [{score:.2f}] {Path(fp).name:<30} {q_text[:90]}", GREEN)
                        cprint(f"         {GRAY}{a_text[:150]}{RESET}", "")
                    total += len(top)
    except Exception as e:
        cprint(f"  ⚠ knowledge.db: {e}", YELLOW)

    # ── Layer 3: Obsidian vault .md files (direct file scan) ─────────────────
    vault_hits = _obsidian_local_search(query, max_results=8)
    if vault_hits:
        cprint(f"\n  {YELLOW}── Obsidian Vault ──{RESET}", "")
        for h in vault_hits:
            cprint(f"  {YELLOW}vault:{RESET} {h['path']}", "")
            cprint(f"    {GRAY}{h['snippet'][:140]}{RESET}", "")
        total += len(vault_hits)

    if total == 0:
        cprint("  No matching memories found in ledger, knowledge DB, or vault", GRAY)
        cprint("  Run /memory-scan first to index your workflow", GRAY)
        activity_done("no matches")
        return

    activity_done(f"{total} results across ledger + knowledge DB + vault")


def cmd_memory_stats() -> None:
    """Show memory ledger stats."""
    adwi_head("Memory ledger")
    try:
        mod = _memory_mod()
        mem = mod.AdwiMemory()
        s   = mem.stats()
        mem.close()
        cprint(f"  Total:       {s['total']} memories", GREEN)
        cprint(f"  Embeddings:  {s['with_embeddings']}", GRAY)
        for src, cnt in sorted(s.get("by_source", {}).items()):
            cprint(f"    {src:12s} {cnt}", GRAY)
        cprint(f"  DB:          {mod.DB_PATH}", GRAY)
    except Exception as e:
        cprint(f"  ✗ {e}", RED)


def cmd_memory_context(query: str = "") -> None:
    """Show the memory context block that would be injected into a prompt."""
    if not query:
        query = input(f"  {CYAN}Query for context injection:{RESET} ").strip()
    if not query:
        return
    try:
        mod = _memory_mod()
        mem = mod.AdwiMemory()
        ctx = mem.format_context(query)
        mem.close()
        if ctx:
            print(f"\n{GRAY}{ctx}{RESET}\n")
        else:
            cprint("  No relevant context found — run /memory-scan to build the ledger", GRAY)
    except Exception as e:
        cprint(f"  ✗ {e}", RED)


# ── Semantic router command ────────────────────────────────────────────────────

def cmd_route(query: str = "") -> None:
    """Classify a query and route it to Aider/Playwright/Ollama."""
    if not query:
        query = input(f"  {CYAN}Route query:{RESET} ").strip()
    if not query:
        return
    route_bin = BIN / "adwi-route"
    if not route_bin.exists():
        cprint("  adwi-route not found at bin/adwi-route", YELLOW)
        return
    import subprocess as _sp
    _sp.run(["python3", str(route_bin), query], cwd=str(BASE))


# ── Nightly improvement commands ──────────────────────────────────────────────

def cmd_nightly_status() -> None:
    """Show LaunchAgent status and when it last ran."""
    adwi_head("Nightly improvement status")
    import subprocess as _sp

    # LaunchAgent
    r = _sp.run(["launchctl", "list", "com.suneel.adwi-nightly"],
                capture_output=True, text=True)
    if "Label" in r.stdout:
        cprint(f"  {GREEN}✓ LaunchAgent loaded{RESET} — runs daily at 2:00 AM", "")
        for ln in r.stdout.splitlines():
            if "PID" in ln or "LastExit" in ln:
                cprint(f"    {ln.strip()}", GRAY)
    else:
        cprint(f"  {YELLOW}⚠ LaunchAgent not loaded{RESET}", "")
        cprint(f"    Run: launchctl load ~/Library/LaunchAgents/com.suneel.adwi-nightly.plist", GRAY)

    # Most recent log
    log_dir = NOTES / "nightly-improvement-logs"
    if log_dir.exists():
        logs = sorted(log_dir.glob("nightly-*.md"))
        if logs:
            last = logs[-1]
            cprint(f"\n  {BOLD}Last run:{RESET} {last.name}", "")
            cprint(f"  Use /nightly-log to read the full report.", GRAY)
        else:
            cprint(f"\n  No nightly logs yet — first run at 2 AM tonight.", GRAY)
    else:
        cprint(f"\n  No logs yet.", GRAY)

    # Pending improvements
    pending = NOTES / "adwi-pending-improvements.md"
    if pending.exists():
        lines = pending.read_text(encoding="utf-8").splitlines()
        count = sum(1 for l in lines if l.startswith("## "))
        cprint(f"\n  {BOLD}Pending improvements:{RESET} {count} sessions logged", "")
        cprint(f"  File: notes/adwi-pending-improvements.md", GRAY)


def cmd_nightly_log(n: int = 0) -> None:
    """Show the most recent nightly improvement report (or the nth most recent)."""
    adwi_head("Nightly improvement log")
    log_dir = NOTES / "nightly-improvement-logs"
    if not log_dir.exists() or not list(log_dir.glob("nightly-*.md")):
        cprint("  No nightly logs yet — runs at 2 AM.", GRAY)
        return
    logs = sorted(log_dir.glob("nightly-*.md"))
    idx = -(n + 1)
    try:
        target = logs[idx]
    except IndexError:
        target = logs[-1]
    cprint(f"  {GRAY}{target}{RESET}", "")
    cprint("", "")
    content = target.read_text(encoding="utf-8")
    # Show up to 120 lines
    for line in content.splitlines()[:120]:
        cprint(f"  {line}", "")
    if len(content.splitlines()) > 120:
        cprint(f"\n  {GRAY}... ({len(content.splitlines())-120} more lines) — open the file to read all{RESET}", "")


def cmd_nightly_run() -> None:
    """Manually trigger the nightly improvement loop (with confirmation)."""
    adwi_head("Run nightly improvement now")
    cprint("  This will run all 6 steps immediately:", GRAY)
    cprint("    1. Services health check", GRAY)
    cprint("    2. Review repair logs + journal", GRAY)
    cprint("    3. AI skill discovery (adwi:latest)", GRAY)
    cprint("    4. Routing evals + syntax check", GRAY)
    cprint("    5. Capability sync", GRAY)
    cprint("    6. Git commit + push", GRAY)
    cprint(f"\n  Report → notes/nightly-improvement-logs/", GRAY)
    ans = input(f"\n  {YELLOW}Run nightly improvement now? (y/n):{RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY)
        return
    import subprocess as _sp
    cprint(f"\n  {CYAN}Starting... (this takes 2-5 min){RESET}", "")
    r = _sp.run(
        ["python3", str(ADWI_DIR / "nightly.py")],
        cwd=str(BASE), timeout=600
    )
    cprint(f"\n  {'✓ Done' if r.returncode == 0 else '⚠ Finished with errors'}. Use /nightly-log to see the report.", GREEN if r.returncode == 0 else YELLOW)


# ── Aliases for preserved commands (/gemini, /owui) ──────────────────────────
def _alias_gemini(prompt: str = "") -> None:
    """Alias: /gemini — explicitly use Gemini cloud for a prompt."""
    adwi_head("Gemini cloud")
    if not prompt.strip():
        prompt = input(f"  {CYAN}Prompt for Gemini:{RESET} ").strip()
    if prompt:
        adwi_say(call_cloud(prompt) if _cloud_ok() else "Cloud unavailable — check API key with /secrets-status")

def _alias_owui(prompt: str = "") -> None:
    """Alias: /owui — send to Open WebUI cloud route."""
    _alias_gemini(prompt)


# ── NLU dispatcher — the heart of natural language mode ──────────────────────
def dispatch_natural(text: str):
    """
    Classify the user's message and run the right action automatically.
    No slash commands needed — just talk naturally.
    """
    # Show a subtle "thinking" indicator for intent classification
    print(f"  {GRAY}…{RESET}", end="\r", flush=True)
    intent_data = classify_intent(text)
    intent = intent_data.get("intent", "chat")
    target = intent_data.get("target")

    # Clear the thinking indicator
    print("    ", end="\r", flush=True)

    # Activity stream — show what was understood (skip for pure chat)
    _ACTION_LABELS = {
        "disk_usage": "Disk Usage Analysis", "large_files": "Find Large Files",
        "old_files": "Find Old Files", "duplicates": "Find Duplicate Files",
        "organize": "Organize Suggestions", "cleanup": "Cleanup Suggestions",
        "file_read": "Read File", "file_search": "File Search",
        "file_list": "List Folder", "youtube": "YouTube Summary",
        "image": "Image Analysis", "status": "Stack Status Check",
        "self_heal": "Self-Heal", "what_next": "What to Build Next",
        "daily_improve": "Daily Improvement Routine", "sync": "Sync Knowledge",
        "model_status": "Model Status", "use_local": "Switch to Local Model",
        "use_cloud": "Switch to Cloud Model", "capabilities": "Capabilities List",
        "rag_search": "Semantic Notes Search", "browse": "Browse URL",
        "github_visibility": "GitHub Repo Visibility",
        "github_connected": "GitHub Connection Check",
        "git_status": "Git Status", "generate_image": "Generate Image",
        "run_code": "Run Python Code", "benchmark": "Benchmark",
        "gmail": "Gmail", "fix_error": "Fix Error / Self-Repair",
        "backup": "GitHub Backup",
        "memory_scan": "Memory Scan", "memory_recall": "Memory Recall",
        "memory_stats": "Memory Stats", "route": "Semantic Router",
        "web_search": "Web Search", "obsidian_search": "Obsidian Vault Search",
        "exa_search": "Exa Neural Search", "firecrawl": "Firecrawl Scrape",
    }
    if intent != "chat" and intent in _ACTION_LABELS:
        activity_start(text, _ACTION_LABELS[intent])

    # Dispatch
    if intent == "disk_usage":
        cmd_disk_usage(target)
    elif intent == "large_files":
        # Extract size threshold from text if mentioned
        m = re.search(r"(\d+)\s*(gb|mb|g|m)\b", text, re.I)
        min_mb = int(m.group(1)) * (1024 if m.group(2).lower() in ("gb","g") else 1) if m else 200
        cmd_large_files(target, min_mb=min_mb)
    elif intent == "old_files":
        m = re.search(r"(\d+)\s*(year|month|day)", text, re.I)
        days = int(m.group(1)) * (365 if "year" in m.group(2) else 30 if "month" in m.group(2) else 1) if m else 365
        cmd_old_files(target, days=days)
    elif intent == "duplicates":
        cmd_find_duplicates(target)
    elif intent == "organize":
        cmd_organize_suggest(target)
    elif intent == "cleanup":
        cmd_cleanup_suggest(target)
    elif intent == "file_read":
        if target:
            cmd_read_file(target)
        else:
            # Ask which file
            path_str = input(f"  {CYAN}Which file to read?{RESET} ").strip()
            if path_str: cmd_read_file(path_str)
    elif intent == "file_search":
        q = target or text
        cmd_file_search(q)
    elif intent == "file_list":
        cmd_list_folder(target or str(HOME))
    elif intent == "youtube":
        if target:
            youtube_menu(target)
        else:
            ask_adwi(text)
    elif intent == "image":
        if target:
            analyze_image(target)
        else:
            path_str = input(f"  {CYAN}Image path?{RESET} ").strip()
            if path_str: analyze_image(path_str)
    elif intent == "status":
        run_cmd("status", ["status-ai"])
    elif intent == "self_heal":
        run_cmd("self-heal", ["adwi-self-heal"], timeout=1200)
    elif intent == "what_next":
        cmd_what_next()
    elif intent == "daily_improve":
        cmd_daily_improve()
    elif intent == "sync":
        run_cmd("sync", ["sync-openwebui-knowledge"], timeout=1200)
    elif intent == "model_status":
        r = load_routing()
        adwi_say(
            f"**Model routing:**\n"
            f"- Backend: `{r.get('ADWI_CHAT_BACKEND')}`\n"
            f"- Cloud model: `{r.get('ADWI_CLOUD_MODEL')}`\n"
            f"- Local model: `{r.get('ADWI_LOCAL_MODEL')}`\n"
            f"- Fast NLU model: `{MODEL_FAST}`\n"
            f"- Vision model: `{MODEL_VISION}`"
        )
    elif intent == "use_local":
        r = load_routing(); r["ADWI_CHAT_BACKEND"] = "local"; save_routing(r)
        cprint(f"  ✓ Switched to local model ({r.get('ADWI_LOCAL_MODEL')}, streaming)", GREEN)
    elif intent == "use_cloud":
        r = load_routing(); r["ADWI_CHAT_BACKEND"] = "openwebui"; save_routing(r)
        cprint(f"  ✓ Switched to cloud ({r.get('ADWI_CLOUD_MODEL')})", GREEN)
    elif intent == "capabilities":
        print_capabilities()
    elif intent == "rag_search":
        q = target or text
        cmd_rag_search(q)
    elif intent == "web_search":
        q = target or re.sub(r"^(search the web for|web search|google|search online for|look up online|find online)\s*", "", text, flags=re.I).strip()
        cmd_web_search(q or text)
    elif intent == "obsidian_search":
        q = target or re.sub(r"^(obsidian|vault|my notes?|open|read|show)\s*", "", text, flags=re.I).strip()
        cmd_obsidian_search(q or text)
    elif intent == "browse":
        url = target or text
        cmd_browse(url)
    elif intent == "github_visibility":
        cmd_github_visibility(text)
    elif intent == "github_connected":
        cmd_github_connected()
    elif intent == "git_status":
        cmd_git("status")
    elif intent == "generate_image":
        # Extract the description (strip the verb trigger)
        desc = re.sub(r"^(generate|create|draw|make|design)\s*(an?\s*)?(image|picture|photo|illustration|artwork)\s*(of|showing|with)?\s*", "", text, flags=re.I).strip()
        cmd_generate_image(desc or text)
    elif intent == "run_code":
        code = _extract_code(text)
        cmd_run_python(code or text)
    elif intent == "benchmark":
        cmd_benchmark()
    elif intent == "memory_scan":
        cmd_memory_scan()
    elif intent == "memory_recall":
        q = target or re.sub(r"^(remember|recall|what do you know about)\s*", "", text, flags=re.I).strip()
        cmd_memory_recall(q)
    elif intent == "memory_stats":
        cmd_memory_stats()
    elif intent == "route":
        q = target or re.sub(r"^(route|which tool).{0,30}?\s", "", text, flags=re.I).strip()
        cmd_route(q)
    elif intent == "gmail":
        # Only treat the text as a search query if it looks like one (not a general question)
        is_question = bool(re.search(r"\b(is|are|how many|do i have|connected|working|latest|newest|recent)\b", text, re.I))
        from_match  = re.search(r"\bfrom\s+(\w[\w\s]{0,30}?)(?:\s+about|\s+today|\s+yesterday|[?.]|$)", text, re.I)
        about_match = re.search(r"\babout\s+(.+?)(?:\s+from|\s+today|\s+yesterday|[?.]|$)", text, re.I)
        if from_match:
            cmd_gmail(query=f"from:{from_match.group(1).strip()}")
        elif about_match and not is_question:
            cmd_gmail(query=about_match.group(1).strip())
        elif "unread" in text.lower():
            cmd_gmail(query="is:unread")
        elif "today" in text.lower():
            cmd_gmail(query="newer_than:1d")
        elif "yesterday" in text.lower():
            cmd_gmail(query="after:yesterday before:today")
        else:
            cmd_gmail()
    else:
        ask_adwi(text)

    # Flush any open trace to disk (no-op if already flushed or never started)
    _flush_trace()

def cmd_what_next():
    adwi_head("What should you build next?")
    ctx = ""
    if ROADMAP_FILE.exists(): ctx += ROADMAP_FILE.read_text(encoding="utf-8")[:3000]
    if JOURNAL_FILE.exists():  ctx += "\n\nRecent journal:\n" + JOURNAL_FILE.read_text(encoding="utf-8")[-1500:]
    result = call_cloud(
        f"Suneel asks: What should I build next for Adwi?\n\n{ctx}\n\n"
        "Top 1 recommendation with 3 concrete first steps. Be specific."
    ) if _cloud_ok() else stream_local(f"Review this roadmap and suggest what to build next:\n{ctx[:2000]}")
    adwi_say(result)
    log_action("what-next", result)

# ── Slash command handler (for users who prefer explicit commands) ─────────────
def handle(line: str) -> bool:
    line = line.strip()
    if not line: return True
    low = line.lower()

    # Exit
    if line in ["/exit","/quit","/bye","exit","quit"]:
        print(f"\n{CYAN}Adwi:{RESET} Bye, Suneel. 👋\n"); return False

    # Clear screen
    if line.lower() in ("clear", "/clear", "cls", "/cls"):
        import subprocess as _sp; _sp.run("clear", shell=True); return True

    # Explicit slash commands (shortcuts for power users)
    if line == "/help": print(HELP); return True

    # Model routing
    if line == "/model-status": dispatch_natural("what model are you using"); return True
    if line == "/use-cloud": r=load_routing();r["ADWI_CHAT_BACKEND"]="openwebui";save_routing(r);cprint(f"  ✓ Cloud ({r.get('ADWI_CLOUD_MODEL')})",GREEN)
    elif line == "/use-local": r=load_routing();r["ADWI_CHAT_BACKEND"]="local";save_routing(r);cprint(f"  ✓ Local ({r.get('ADWI_LOCAL_MODEL')}, streaming)",GREEN)
    elif line.startswith("/set-cloud-model "):
        m=line[17:].strip();r=load_routing();r["ADWI_CLOUD_MODEL"]=m;r["ADWI_CHAT_BACKEND"]="openwebui";save_routing(r);cprint(f"  ✓ Cloud model → {m}",GREEN)
    elif line == "/models": _list_models()
    elif line == "/capabilities" or line == "/capability-status": print_capabilities()
    elif line == "/daily-improve": cmd_daily_improve()
    elif line == "/roadmap":
        if ROADMAP_FILE.exists(): print(ROADMAP_FILE.read_text(encoding="utf-8"))
    elif line == "/journal":
        if JOURNAL_FILE.exists(): print("\n".join(JOURNAL_FILE.read_text(encoding="utf-8").splitlines()[-60:]))
    elif line == "/mistakes":
        if MISTAKES_FILE.exists(): print("\n".join(MISTAKES_FILE.read_text(encoding="utf-8").splitlines()[-60:]))
    elif line.startswith("/disk"): cmd_disk_usage(line[5:].strip() or None)
    elif line.startswith("/large-files"): cmd_large_files(line[12:].strip() or None)
    elif line.startswith("/old-files"): cmd_old_files(line[10:].strip() or None)
    elif line.startswith("/duplicates"): cmd_find_duplicates(line[11:].strip() or None)
    elif line.startswith("/organize"): cmd_organize_suggest(line[9:].strip() or None)
    elif line.startswith("/cleanup"): cmd_cleanup_suggest(line[8:].strip() or None)
    elif line.startswith("/image "): analyze_image(line[7:].strip())
    elif line.startswith("/image-save "): analyze_image(line[12:].strip(), save=True)
    elif line.startswith("/screenshot-analyze "): analyze_image(line[20:].strip())
    elif line.startswith("/read "): cmd_read_file(line[6:].strip())
    elif line.startswith("/list "): cmd_list_folder(line[6:].strip())
    elif line.startswith("/search "): cmd_file_search(line[8:].strip())
    elif line.startswith("/url "): run_cmd("url", ["summarize-url", line[5:].strip()], timeout=600)
    elif line.startswith("/youtube "): run_cmd("youtube", ["summarize-youtube", line[9:].strip()], timeout=600)
    elif line.startswith("/save-youtube "): run_cmd("save-youtube", ["save-youtube-summary", line[14:].strip()], timeout=600)
    elif line.startswith("/reason "):
        adwi_head("Cloud reasoning")
        adwi_say(call_cloud(
            f"Complex reasoning request from Suneel:\n\n{line[8:].strip()}\n\n"
            "Think step by step. Flag risks. Be specific."
        ) if _cloud_ok() else stream_local(line[8:].strip()))
    elif line.startswith("/review-plan "):
        ctx = ROADMAP_FILE.read_text(encoding="utf-8")[:2000] if ROADMAP_FILE.exists() else ""
        adwi_say(call_cloud(f"Review this plan:\n\n{line[13:].strip()}\n\nContext:\n{ctx}") if _cloud_ok() else stream_local(line[13:].strip()))
    elif line == "/what-next": cmd_what_next()
    elif line.startswith("/add-root "):
        folder=line[10:].strip(); p=Path(folder).expanduser().resolve()
        if not p.is_dir(): adwi_say(f"Not a directory: `{p}`")
        elif is_hard_blocked(p): adwi_say("Blocked: that path is security-sensitive.")
        else:
            existing=ROOTS_FILE.read_text().splitlines()
            if str(p) not in existing:
                with ROOTS_FILE.open("a") as f: f.write(str(p)+"\n")
            cprint(f"  ✓ Added: {p}", GREEN)
    elif line == "/status" or low == "check my setup": run_cmd("status",["status-ai"])
    elif line == "/self-heal" or low == "fix my setup": run_cmd("self-heal",["adwi-self-heal"],timeout=1200)
    elif line == "/sync-knowledge" or low == "sync my knowledge": run_cmd("sync",["sync-openwebui-knowledge"],timeout=1200)
    elif line == "/watcher-status": run_cmd("watcher",["status-openwebui-knowledge-watcher"])
    elif line == "/secrets-status": run_cmd("secrets",["adwi-secrets-status"])
    elif line.startswith("/cloud "): adwi_say(call_cloud(line[7:].strip()))
    elif line.startswith("/local "): stream_local(line[7:].strip())
    # ── New Phase 2 commands ──
    elif line == "/rag-index": cmd_rag_index()
    elif line.startswith("/rag "): cmd_rag_search(line[5:].strip())
    elif line == "/rag": cmd_rag_search(input(f"  {CYAN}Search query:{RESET} ").strip())
    elif line.startswith("/browse "): cmd_browse(line[8:].strip())
    elif line.startswith("/web-search "): cmd_web_search(line[12:].strip())
    elif line == "/web-search": cmd_web_search()
    elif line.startswith("/exa "): cmd_exa_search(line[5:].strip())
    elif line == "/exa": cmd_exa_search()
    elif line.startswith("/exa-search "): cmd_exa_search(line[12:].strip())
    elif line == "/exa-search": cmd_exa_search()
    elif line.startswith("/tavily "): cmd_tavily_search(line[8:].strip())
    elif line == "/tavily": cmd_tavily_search()
    elif line.startswith("/firecrawl "): cmd_firecrawl(line[11:].strip())
    elif line == "/firecrawl": cmd_firecrawl()
    elif line.startswith("/obsidian-search "): cmd_obsidian_search(line[17:].strip())
    elif line == "/obsidian-search": cmd_obsidian_search()
    elif line.startswith("/obsidian-read "): cmd_obsidian_read(line[15:].strip())
    elif line == "/obsidian-read": cmd_obsidian_read()
    elif line.startswith("/obsidian-write "): cmd_obsidian_write(line[16:].strip())
    elif line == "/obsidian-write": cmd_obsidian_write()
    elif line.startswith("/obsidian-daily "): cmd_obsidian_daily(line[16:].strip())
    elif line == "/obsidian-daily": cmd_obsidian_daily()
    elif line.startswith("/run-python"): cmd_run_python(line[11:].strip())
    elif line.startswith("/run-bash "): cmd_run_bash(line[10:].strip())
    elif line in ("/github-status", "/github", "/gh-status"): cmd_github_connected()
    elif line in ("/github-public", "/repo-public"): cmd_github_visibility("public")
    elif line in ("/github-private", "/repo-private"): cmd_github_visibility("private")
    elif line.startswith("/git"): cmd_git(line[4:].strip())
    elif line.startswith("/generate-image "): cmd_generate_image(line[16:].strip())
    elif line == "/generate-image": cmd_generate_image(input(f"  {CYAN}Image prompt:{RESET} ").strip())
    elif line == "/benchmark": cmd_benchmark()
    elif line == "/mcp": cmd_mcp_status()
    elif line == "/mcp-setup": cmd_mcp_setup()
    elif line == "/gmail-auth": cmd_gmail_auth()
    elif line == "/gmail" or line == "/inbox": cmd_gmail()
    elif line.startswith("/gmail "): cmd_gmail(query=line[7:].strip())
    elif line.startswith("/gmail-read "): cmd_gmail_read(line[12:].strip())
    elif line == "/gmail-summary": cmd_gmail_summary()
    elif line.startswith("/gmail-summary "): cmd_gmail_summary(query=line[15:].strip())
    # ── Self-repair commands (confirm before patching) ──
    elif line.startswith("/fix-error"): cmd_fix_error(line[10:].strip())
    elif line == "/repair-adwi": cmd_repair_adwi()
    elif line.startswith("/patch-adwi"): cmd_patch_adwi(line[11:].strip())
    elif line.startswith("/run-safe"): cmd_run_safe(line[9:].strip())
    elif line.startswith("/inspect-code "): cmd_inspect_code(line[14:].strip())
    elif line == "/inspect-code": cmd_inspect_code(input(f"  {CYAN}File path:{RESET} ").strip())
    elif line == "/test-adwi": cmd_test_adwi()
    elif line == "/learn-from-last-error": cmd_learn_from_last_error()
    elif line == "/capabilities" or line == "/capability-status": cmd_capabilities_detailed()
    elif line == "/capability-audit": cmd_capability_audit()
    # ── Phase 2 — Evals + training ──
    elif line == "/eval-routing": cmd_eval_routing()
    elif line == "/eval-adwi": cmd_eval_adwi()
    elif line.startswith("/export-training-example"): cmd_export_training_example(line[24:].strip())
    elif line == "/training-plan": cmd_training_plan()
    # ── Phase 3 — System inspection ──
    elif line == "/inspect-system": cmd_inspect_system()
    elif line == "/doctor": cmd_doctor()
    elif line == "/trusted-roots": cmd_trusted_roots()
    elif line.startswith("/trust-root "):
        folder=line[12:].strip(); p=Path(folder).expanduser().resolve()
        if not p.is_dir(): adwi_say(f"Not a directory: `{p}`")
        elif is_hard_blocked(p): adwi_say("Blocked: that path is security-sensitive.")
        else:
            existing = ROOTS_FILE.read_text().splitlines() if ROOTS_FILE.exists() else []
            if str(p) not in existing:
                with ROOTS_FILE.open("a") as f: f.write(str(p)+"\n")
                log_action("trust-root", f"Added: {p}")
            cprint(f"  ✓ Trusted: {p}", GREEN)
    # ── Phase 4 — Ideas + implementation ──
    elif line.startswith("/extract-ideas"): cmd_extract_ideas(line[14:].strip())
    elif line.startswith("/implement-idea"): cmd_implement_idea(line[15:].strip())
    # ── Phase 5 — Tool roadmap ──
    elif line == "/tool-roadmap": cmd_tool_roadmap()
    # ── Phase 6 — GitHub backup ──
    elif line == "/backup-status": cmd_backup_status()
    elif line.startswith("/backup-now"): cmd_backup_now(line[11:].strip())
    elif line == "/backup-enable": cmd_backup_enable()
    elif line == "/backup-disable": cmd_backup_disable()
    elif line == "/backup-log": cmd_backup_log()
    elif line == "/backup-audit": cmd_backup_audit()
    # ── Activity trace ──
    elif line == "/trace-log":
        cmd_trace_log()
    elif line.startswith("/trace-log "):
        arg = line[11:].strip()
        cmd_trace_log(int(arg) if arg.isdigit() else 0)
    # ── Memory Layer ──
    elif line == "/memory-scan": cmd_memory_scan()
    elif line == "/memory-stats": cmd_memory_stats()
    elif line.startswith("/memory-recall "): cmd_memory_recall(line[15:].strip())
    elif line == "/memory-recall": cmd_memory_recall()
    elif line.startswith("/memory-context "): cmd_memory_context(line[16:].strip())
    elif line == "/memory-context": cmd_memory_context()
    # ── Semantic router ──
    elif line.startswith("/route "): cmd_route(line[7:].strip())
    elif line == "/route": cmd_route()
    # ── Nightly improvement ──
    elif line == "/nightly-status": cmd_nightly_status()
    elif line.startswith("/nightly-log"):
        arg = line[12:].strip()
        cmd_nightly_log(int(arg) if arg.isdigit() else 0)
    elif line == "/nightly-run": cmd_nightly_run()
    # ── Aliases ──
    elif line.startswith("/gemini"): _alias_gemini(line[7:].strip())
    elif line.startswith("/owui"):   _alias_owui(line[5:].strip())
    else:
        # Natural language — let the intent classifier handle it
        dispatch_natural(line)

    return True

def _list_models():
    adwi_head("Installed Ollama models")
    out = run_shell("ollama list 2>/dev/null")
    print(out)

# ── Prompt session ────────────────────────────────────────────────────────────
def make_session():
    kb = KeyBindings()
    @kb.add("enter")
    @kb.add("c-s")
    def submit(e): e.current_buffer.validate_and_handle()
    @kb.add("escape","enter")    # Option+Enter / Alt+Enter on Mac
    def newline(e): e.current_buffer.insert_text("\n")
    @kb.add("c-d")
    def ctrl_d(e):
        if e.current_buffer.text.strip(): e.current_buffer.validate_and_handle()
        else: raise EOFError
    style = Style.from_dict({"prompt":"#00bcd4 bold","bottom-toolbar":"bg:#111 #555"})
    toolbar = "  Enter=send  ·  Option+Enter=newline  ·  /help  ·  /exit  "
    return PromptSession(
        history=FileHistory(str(HISTORY_FILE)), key_bindings=kb, style=style,
        multiline=True, prompt_continuation=lambda *a: "  … ",
        bottom_toolbar=HTML(f"<b>{toolbar}</b>"), mouse_support=False,
    )

# ── Help ──────────────────────────────────────────────────────────────────────
HELP = f"""
{BOLD}{PURPLE}Adwi — just talk naturally. Slash commands are optional shortcuts.{RESET}

You can say things like:
  "what's taking up all my space?"
  "find files bigger than 1GB in my Downloads"
  "what haven't I opened in over a year?"
  "are there duplicate photos?"
  "help me organize my Desktop"
  "what can I safely delete?"
  "read my notes/profile.md"
  "look at this screenshot: ~/Desktop/error.png"
  "is everything running?"
  "what should I build next?"
  "summarize this video: <youtube url>"
  "search my notes about RAG"
  "browse https://news.ycombinator.com"
  "git status of my workspace"
  "generate an image of a mountain at sunset"
  "run this python code: print('hello')"
  "benchmark Adwi"
  "switch to local model"

{BOLD}Optional slash commands:{RESET}
  /disk [path]               Disk usage analysis
  /large-files [path]        Find large files
  /old-files [path]          Find files not opened in 1+ year
  /duplicates [path]         Find duplicate files
  /organize [path]           AI organization suggestions
  /cleanup [path]            What to safely delete
  /read <path>               Read a file
  /list <path>               List folder contents
  /search <term>             Search files and content
  /image <path>              Analyze image (local vision)
  /url <url>                 Summarize webpage
  /youtube <url>             Summarize YouTube video
  /browse <url> [question]   Fetch + summarize a webpage (JS-capable)
  /rag <query>               Semantic search over local notes
  /rag-index                 Rebuild the RAG notes index
  /git [status|log|diff|review|repos]   Git operations
  /run-python [code]         Run Python with confirmation
  /run-bash <cmd>            Run shell command with confirmation
  /generate-image <prompt>   Generate an image (LocalAI)
  /benchmark                 Benchmark local model speed
  /mcp                       Show MCP tool server status
  /mcp-setup                 Configure MCP tool servers
  /reason <task>             Deep cloud reasoning
  /daily-improve             Daily improvement routine (tests + journal + sync)
  /what-next                 What to build next
  /capabilities              List all capabilities with detail
  /capability-audit          Compare JSON registry vs implemented commands

{BOLD}Self-repair (confirm before patch):{RESET}
  /fix-error [error]         Paste error → classify → inspect → patch → test
  /repair-adwi               Self-check: syntax, routing, smoke tests (10 checks)
  /patch-adwi [request]      AI patches itself safely (backup + confirm + rollback)
  /test-adwi                 Smoke tests: compile, /model-status, /status, /capabilities
  /run-safe [action]         Run allowlisted local helper command
  /inspect-code [file]       Read + AI-explain source/config file
  /learn-from-last-error     Review repair logs → update mistakes journal

{BOLD}System + Evals:{RESET}
  /inspect-system            Full read-only system inventory (saves report)
  /doctor                    Inspect + AI health analysis + exact fixes
  /trusted-roots             Show allowed read paths
  /trust-root <path>         Add a trusted read root
  /eval-routing              Run 30 NLU routing test cases
  /eval-adwi                 Full eval: smoke + routing + capability audit
  /export-training-example   Save a high-quality interaction to training data
  /training-plan             Show fine-tuning readiness status

{BOLD}Ideas + Tools:{RESET}
  /extract-ideas [src]       Extract implementable ideas from URL/file/text
  /implement-idea [src]      Build plan + implement idea with confirmation
  /tool-roadmap              Show Phase 5 tool stack (active vs planned)

{BOLD}Activity Stream + Traces:{RESET}
  /trace-log [n]             Read most recent activity trace (or nth most recent)
  (traces auto-saved to notes/adwi-trace-logs/ after every action)

{BOLD}Nightly Improvement (2 AM auto-run):{RESET}
  /nightly-status            LaunchAgent status, last run, pending improvements
  /nightly-log [n]           Read most recent (or nth) nightly report
  /nightly-run               Trigger nightly loop right now (with confirm)

{BOLD}GitHub Backup:{RESET}
  /backup-status             Git status, remote, last commit, LaunchAgent
  /backup-now [message]      Secret scan → commit → push (requires confirm)
  /backup-enable             Init git + LaunchAgent (30-min auto-backup)
  /backup-disable            Stop auto-backup
  /backup-log                Recent backup logs
  /backup-audit              What is included/excluded + secret scan

{BOLD}Core:{RESET}
  /use-local /use-cloud      Switch models
  /model-status              Active model routing
  /gemini [prompt]           Explicitly use Gemini cloud
  /owui [prompt]             Alias for /gemini
  /status                    Stack health check
  /self-heal                 Auto-repair setup
  /sync-knowledge            Sync Open WebUI Knowledge
  /journal /mistakes /roadmap    View memory files
  /help                      This help
  /exit                      Quit

{BOLD}Input:{RESET} Enter=send · Option+Enter=newline · Ctrl+S=send · ↑↓=history
""".strip()

# ── Banner ────────────────────────────────────────────────────────────────────
def print_banner():
    r = load_routing()
    backend = r.get("ADWI_CHAT_BACKEND","openwebui")
    active  = r.get("ADWI_CLOUD_MODEL") if backend=="openwebui" else r.get("ADWI_LOCAL_MODEL")
    print()
    print(f"{BOLD}{PURPLE}  ╔═══════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{PURPLE}  ║      A D W I  —  Local AI Operating System   ║{RESET}")
    print(f"{BOLD}{PURPLE}  ╚═══════════════════════════════════════════════╝{RESET}")
    print(f"  {GRAY}Reasoning  :{RESET} {WHITE}{MODEL_MAIN} · 131K ctx · streaming{RESET}")
    print(f"  {GRAY}NLU        :{RESET} {WHITE}{MODEL_FAST} · intent classification{RESET}")
    print(f"  {GRAY}Vision     :{RESET} {WHITE}{MODEL_VISION} · local, no cloud needed{RESET}")
    print(f"  {GRAY}Cloud      :{RESET} {WHITE}{r.get('ADWI_CLOUD_MODEL')} (fallback){RESET}")
    print(f"  {GRAY}Active mode:{RESET} {WHITE}{backend}{RESET}")
    print(f"  {GRAY}Filesystem :{RESET} {WHITE}/Users/MAC (full home access){RESET}")
    rag_ready = (ADWI_DIR / "rag-db" / "notes-index.json").exists()
    mcp_ready = MCP_CONFIG.exists()
    mcp_count = 0
    if mcp_ready:
        try:
            mcp_count = len(json.loads(MCP_CONFIG.read_text()).get("mcpServers", {}))
        except Exception:
            mcp_count = 0
    print(f"  {GRAY}RAG index  :{RESET} {(GREEN+'ready') if rag_ready else (YELLOW+'run /rag-index')}{RESET}")
    mcp_label = f"{GREEN}{mcp_count} servers{RESET}" if mcp_count else (GREEN+"configured" if mcp_ready else YELLOW+"run /mcp-setup")
    print(f"  {GRAY}MCP tools  :{RESET} {mcp_label}{RESET}")
    print()
    print(f"  {DIM}Just talk naturally. No commands to memorize.{RESET}")
    print(f"  {DIM}/help for optional shortcuts · /exit to quit{RESET}")
    print()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) > 1:
        flag = sys.argv[1]
        if flag in ["--help","-h"]: print(HELP); return
        if flag == "--ask": ask_adwi(" ".join(sys.argv[2:])); return
        if flag == "--daily-improve": cmd_daily_improve(); return
        if flag == "--classify":
            r = classify_intent(" ".join(sys.argv[2:]))
            print(json.dumps(r, indent=2)); return

    print_banner()

    if PROMPT_TOOLKIT:
        session = make_session()
        while True:
            try:
                text = session.prompt(HTML("<prompt>Suneel</prompt>  <b>›</b>  "))
            except KeyboardInterrupt:
                print(f"\n{GRAY}  Ctrl+C — type /exit to quit{RESET}"); continue
            except EOFError:
                print(f"\n{CYAN}Adwi:{RESET} Bye, Suneel.\n"); break
            text = text.strip()
            if not text: continue
            if not handle(text): break
            print()
    else:
        print(f"{YELLOW}  Install prompt_toolkit: pip3 install prompt_toolkit{RESET}\n")
        while True:
            try:    line = input("Suneel > ")
            except: print("\nBye."); break
            if line.strip():
                if not handle(line): break
                print()

if __name__ == "__main__":
    main()
