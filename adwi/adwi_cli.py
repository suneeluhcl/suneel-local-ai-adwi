#!/usr/bin/env python3
"""
Adwi — Suneel's Local AI Operating Assistant
Natural language interface: just talk, Adwi figures out what to do.
Models: adwi:latest (30.5B reasoning) + llama3.1:8b (NLU) + minicpm-v (local vision)
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
from datetime import datetime, timedelta
from pathlib import Path

# Inject adwi venv so instructor/markitdown/faster-whisper are available
_VENV_SITE = Path.home() / "SuneelWorkSpace" / "adwi" / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _VENV_SITE.exists() and str(_VENV_SITE) not in sys.path:
    sys.path.insert(0, str(_VENV_SITE))

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.styles import Style
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document as _PTDocument
    PROMPT_TOOLKIT = True
except ImportError:
    PROMPT_TOOLKIT = False
    Completer = object   # stub so class body parses cleanly without prompt_toolkit

# Optional: instructor for structured LLM outputs
try:
    import instructor
    from openai import OpenAI as _OpenAI
    _INSTRUCTOR_CLIENT = instructor.from_openai(
        _OpenAI(base_url="http://127.0.0.1:11434/v1", api_key="ollama"),
        mode=instructor.Mode.JSON,
    )
    INSTRUCTOR_OK = True
except Exception:
    INSTRUCTOR_OK = False

# Optional: OpenTelemetry tracing → Arize Phoenix (:4318)
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor as _BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as _OTLPExporter
    _tp = _TracerProvider()
    _tp.add_span_processor(_BatchSpanProcessor(
        _OTLPExporter(endpoint="http://127.0.0.1:4317", insecure=True)
    ))
    _otel_trace.set_tracer_provider(_tp)
    _tracer = _otel_trace.get_tracer("adwi")
    OTEL_OK = True
except Exception:
    _tracer = None
    OTEL_OK = False


def _otel_span(name: str, attrs: dict | None = None):
    """Context manager — no-op when Phoenix is unavailable."""
    if _tracer:
        span = _tracer.start_span(name)
        if attrs:
            for k, v in attrs.items():
                span.set_attribute(k, str(v))
        return _otel_trace.use_span(span, end_on_exit=True)
    import contextlib
    return contextlib.nullcontext()

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
MODEL_FAST    = "llama3.1:8b"          # 4.9GB — structured NLU classification
MODEL_VISION  = "minicpm-v:latest"     # 5.5GB — local vision
MODEL_EMBED   = "nomic-embed-text"     # embeddings
CLOUD_DEFAULT = "models/gemini-2.5-flash"
MODEL_NLU_FALLBACK = "qwen3:0.6b"     # ultra-fast fallback if llama3.1:8b is cold

# ── Session conversation history (multi-turn context for ask_adwi) ────────────
_SESSION_HISTORY: list = []        # list of {role, content} for prior chat turns
_SESSION_MAX_TURNS: int = 20       # max turns to keep (1 turn = 1 user + 1 assistant msg)

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
# Pillar B — remote access
HA_URL            = os.environ.get("HOME_ASSISTANT_URL",  "http://127.0.0.1:8123")
HA_TOKEN          = os.environ.get("HOME_ASSISTANT_TOKEN", "")
TAILSCALE_IP      = os.environ.get("TAILSCALE_IP",         "")

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

# ── Phase 3: Three-tier risk classification for all CLI commands ───────────────
_RISK_BLOCKED_RE = re.compile(
    r"rm\s+-rf|git\s+push\s+--force|DROP\s+TABLE|/etc/|/private/|/System/"
    r"|~/\.ssh|~/\.aws|secrets/|format\s+disk|diskutil\s+erase",
    re.I,
)
_RISK_REVIEW_RE = re.compile(
    r"git\s+commit\b|git\s+push\b|docker\s+compose\s+(down|rm)\b|brew\s+uninstall"
    r"|pip\s+uninstall|rm\s+-r(?!f)|chmod\b|chown\b|pkill\b|launchctl\s+(un)?load",
    re.I,
)

def _classify_cli_risk(cmd: str) -> str:
    """Phase 3 gate: BLOCKED | REVIEW-REQUIRED | SAFE."""
    if denied(cmd) or _RISK_BLOCKED_RE.search(cmd):
        return "BLOCKED"
    if _RISK_REVIEW_RE.search(cmd):
        return "REVIEW-REQUIRED"
    return "SAFE"

def _rich_permission_gate(action_label: str, cmd: str, why: str) -> bool:
    """Phase 2 interactive permission gate used across all CLI commands."""
    W = 64
    print(f"\n  ╭{'─' * W}╮")
    print(f"  │  \033[1m\033[33mAction Required\033[0m{'':<{W - 17}}│")
    print(f"  │{'─' * W}│")
    print(f"  │  \033[1mWhy:\033[0m{'':<{W - 6}}│")
    import textwrap as _tw
    for line in _tw.wrap(why, width=W - 4):
        print(f"  │  \033[90m{line:<{W-4}}\033[0m│")
    print(f"  │{'─' * W}│")
    print(f"  │  \033[1mAction [{action_label}]:\033[0m{'':<{W - len(f'Action [{action_label}]:') - 2}}│")
    for line in (cmd if isinstance(cmd, list) else [cmd]):
        print(f"  │  \033[36m{('$ ' + line)[:W-4]:<{W-4}}\033[0m│")
    print(f"  ╰{'─' * W}╯")
    print(f"\n  \033[33mAllow Adwi to execute this action? (y/n):\033[0m ", end="", flush=True)
    try:
        ans = input().strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False

# ── Phase 4: Live self-heal for approved CLI commands ─────────────────────────
def _cli_live_heal(error_output: str) -> bool:
    """
    Phase 4: intercept a runtime error from an approved command.
    Invokes aider non-interactively, runs tests, returns True if healed.
    """
    import traceback as _tb
    import textwrap as _tw

    # Identify files to patch
    workspace = Path.home() / "SuneelWorkSpace"
    adwi_dir  = workspace / "adwi"
    files: list[Path] = []
    for m in re.finditer(r'File "([^"]+\.py)"', error_output):
        p = Path(m.group(1))
        try:
            p.resolve().relative_to(workspace.resolve())
            if p.exists() and "test_" not in p.name:
                files.append(p)
        except ValueError:
            pass
    files = list(dict.fromkeys(files))[:4]

    print(f"\n  \033[33m⚕  Runtime error intercepted — attempting live self-heal …\033[0m")
    if not files:
        print(f"  \033[90mNo workspace source files in traceback — showing error instead.\033[0m")
        cprint(error_output[:800], YELLOW)
        return False

    print(f"  \033[90mTargeting: {', '.join(f.name for f in files)}\033[0m")

    aider_bin = Path.home() / ".local" / "bin" / "aider"
    if not aider_bin.exists():
        print(f"  \033[33maider not found — showing error.\033[0m")
        cprint(error_output[:800], YELLOW)
        return False

    prompt_txt = (
        f"[Adwi live self-heal] Runtime error from approved command:\n\n"
        f"```\n{error_output[:2000]}\n```\n\n"
        "Fix the minimum lines needed. Do not add features or change passing behaviour."
    )
    aider_cmd = [
        str(aider_bin),
        "--model", "ollama/adwi:latest",
        "--no-git", "--yes-always", "--no-pretty", "--no-stream",
        "--message", prompt_txt,
    ] + [str(f) for f in files]

    env = {
        **os.environ,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "OLLAMA_API_BASE": "http://127.0.0.1:11434",
    }
    print(f"  \033[90mInvoking aider …\033[0m")
    try:
        r = subprocess.run(
            aider_cmd, capture_output=True, text=True, timeout=300,
            cwd=str(workspace), env=env,
        )
        if r.returncode != 0:
            print(f"  \033[33mAider returned non-zero — patch may be incomplete.\033[0m")
    except subprocess.TimeoutExpired:
        print(f"  \033[33mAider timed out.\033[0m")
        return False
    except Exception as e:
        print(f"  \033[33mAider error: {e}\033[0m")
        return False

    # Verify with tests
    print(f"  \033[32mAider complete — verifying …\033[0m")
    evals = adwi_dir / "evals"
    if evals.exists() and any(evals.glob("test_*.py")):
        test_cmd = ["python3", "-m", "pytest", str(evals), "-x", "--tb=short", "-q"]
    else:
        test_cmd = ["python3", "-m", "py_compile", str(adwi_dir / "adwi_cli.py")]
    try:
        tr = subprocess.run(test_cmd, capture_output=True, text=True, timeout=90,
                           cwd=str(workspace), env=env)
        if tr.returncode == 0:
            print(f"  \033[32m✓ Verification passed — heal confirmed.\033[0m")
            return True
        else:
            print(f"  \033[33mVerification still failing after patch.\033[0m")
            cprint((tr.stdout + tr.stderr)[:400], YELLOW)
            return False
    except Exception as e:
        print(f"  \033[33mVerification error: {e}\033[0m")
        return False

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
    # ── Large files — BEFORE disk_usage (Bug 2: superset-ordering fix) ───────────
    # "biggest/largest/heaviest files" must win over disk_usage's broader pattern
    (re.compile(r"\b(big(gest)?|large(st)?|heavy|huge)\b.{0,30}\bfiles?\b", re.I), "large_files"),
    (re.compile(r"\bfiles?\b.{0,20}(over|bigger than|larger than|more than)\s*\d", re.I), "large_files"),
    (re.compile(r"\b(top \d+|find).{0,20}(big(gest)?|large(st)?|heavy).{0,20}files?\b", re.I), "large_files"),
    # NHR-001: additional synonyms — beat file_search on "fat/oversized files"
    (re.compile(r"\b(fat|oversize|oversized|bulky|enormous|massive|hefty)\b.{0,30}\bfiles?\b", re.I), "large_files"),
    # FIX-LF-001: space consumer / room / size-threshold patterns
    (re.compile(r"\b(top|bulk|biggest|heaviest)\b.{0,20}\bspace\s+(consumer|user|hog)s?\b", re.I), "large_files"),
    (re.compile(r"\bfiles?\b.{0,30}(take\s+up|taking\s+up|using)\b.{0,20}(the\s+)?most\s+(room|space|storage)\b", re.I), "large_files"),
    (re.compile(r"\b(which|what)\b.{0,10}files?\b.{0,30}(use|take|using|taking).{0,10}(the\s+)?most\s+(space|room)\b", re.I), "large_files"),
    (re.compile(r"\bfiles?\b.{0,20}exceed(ing)?\b.{0,10}\d+\s*(gb|mb|gigabyte|megabyte)\b", re.I), "large_files"),

    # ── Disk / space (narrowed to disk/space/storage objects only) ───────────────
    # FIX-SPRINT-005: advisory "what generates/causes disk usage" → skip disk_usage (LLM handles as chat)
    # these must precede the disk_usage patterns below
    (re.compile(r"\b(?:what|how)\b.{0,15}\b(?:generates?|causes?|creates?|contributes?\s+to|fills?)\b.{0,25}\b(?:disk|storage)\b", re.I), "chat"),
    (re.compile(r"\bhow\s+does\b.{0,20}\b(?:disk|storage)\b", re.I), "chat"),
    (re.compile(r"(biggest|largest|heaviest|most space|taking up|using up|eating up).{0,40}(disk|storage|space)\b", re.I), "disk_usage"),
    (re.compile(r"(disk|storage|space).{0,40}(usage|breakdown|overview|used|free|full|analysis)", re.I), "disk_usage"),
    # FIX-SPRINT-005b: "what's using disk" is action; "what" alone without "'s" → too broad
    (re.compile(r"\bwhat.s\b.{0,30}(space|room|storage|disk)", re.I), "disk_usage"),
    (re.compile(r"\bhow\s+much\b.{0,30}(space|room|storage|disk)", re.I), "disk_usage"),
    (re.compile(r"\bcheck\b.{0,10}\b(my\s+)?(disk|storage|space)\b", re.I), "disk_usage"),
    (re.compile(r"(free up|clean up).{0,20}(space|disk|storage|room)", re.I), "cleanup"),

    # FIX-SPRINT-004: "purge old X", "remove leftover X" → cleanup BEFORE old_files steals them
    # "purge old downloads", "remove leftover installers" are delete-intent (cleanup), not list-intent (old_files)
    (re.compile(r"\b(?:purge|delete|clear|clean)\b.{0,5}\bold\b.{0,25}\b(?:downloads?|cache|temp|installers?|packages?|junk|logs?|files?)\b", re.I), "cleanup"),
    (re.compile(r"\bremove\b.{0,10}\b(?:leftover|old|stale|unused)\b.{0,20}\b(?:installers?|packages?|downloads?|cache|temp)\b", re.I), "cleanup"),
    # ── Old files ────────────────────────────────────────────────────────────────
    (re.compile(r"(old|haven.t (used|opened|touched)|stale|unused|not (used|opened|accessed)).{0,30}(file|folder|doc)", re.I), "old_files"),
    (re.compile(r"files?.{0,20}(not|never).{0,20}(used|opened).{0,20}(year|month|day)", re.I), "old_files"),
    # File-first ordering: "files I haven't opened/used in a year"
    (re.compile(r"\bfiles?\b.{0,30}(haven.t|not).{0,5}(opened|used|accessed|touched)\b", re.I), "old_files"),
    # FIX-OLD-001: archaic/abandoned/leftover synonyms
    (re.compile(r"\b(archaic|abandoned|obsolete|leftover|outdated|legacy)\b.{0,30}(files?|data|stuff)?\b", re.I), "old_files"),
    (re.compile(r"\bhaven.t.{0,10}(used|opened|accessed|touched)\b.{0,30}(this\s+year|in\s+(a|one|two|several)\s+year)\b", re.I), "old_files"),

    # ── Duplicates ───────────────────────────────────────────────────────────────
    (re.compile(r"(duplicate|identical|same file|copy|copies|redundant)", re.I), "duplicates"),
    # NHR-001: additional synonyms — beat file_search on "find cloned/deduped files"
    (re.compile(r"\b(clone|cloned|dedup|deduplicat|same.content|bit.for.bit|identical.content)\b.{0,20}files?\b", re.I), "duplicates"),
    # FIX-DUP-001: "repeated" / "appear more than once" / "dedupe" / typos
    (re.compile(r"\b(repeated|appear.{0,10}more\s+than\s+once)\b.{0,30}(files?|photos?|images?)?\b", re.I), "duplicates"),
    (re.compile(r"\bdedupe\b.{0,30}(workspace|folder|files?|photos?)?\b", re.I), "duplicates"),
    (re.compile(r"\bdup(l?i?k|l?ic|l?ik)at", re.I), "duplicates"),

    # FIX-CLEAN-004: "clean up downloads/cache/trash" → cleanup BEFORE organize steals "clean up…folder"
    (re.compile(r"\bclean\s*up\b.{0,40}(my\s+)?(downloads?|desktop|cache|temp|trash|junk)\b", re.I), "cleanup"),
    (re.compile(r"\bremove\b.{0,20}\b(unneeded|unnecessary|useless|unwanted|redundant)\b", re.I), "cleanup"),
    (re.compile(r"\b(suggest|find|show)\b.{0,20}\bthings?\b.{0,25}\b(i\s+(can|could|should)\s+)?(remove|delete|trash|get\s+rid\s+of)\b", re.I), "cleanup"),
    # FIX-NOTES-001: "find/search notes about X" → obsidian_search BEFORE rag_search swallows it
    (re.compile(r"\b(find|search)\s+(for\s+)?notes?\b.{0,20}\b(about|on|regarding)\b", re.I), "obsidian_search"),
    (re.compile(r"\bsearch\s+(for\s+)?notes?\s+for\b", re.I), "obsidian_search"),
    # ── Organize ─────────────────────────────────────────────────────────────────
    (re.compile(r"(organiz|tidy|restructure|better structure|sort out|clean up).{0,30}(folder|file|download|desktop|document|workspace|project)", re.I), "organize"),
    # FIX-SPRINT-ORG: "help organize my workspace", "how to structure my project folders"
    (re.compile(r"\b(?:help|how\s+to|how\s+do\s+I|best\s+way\s+to)\b.{0,10}\b(?:organize|structure|arrange|tidy)\b.{0,30}\b(?:files?|folders?|workspace|project|notes?)\b", re.I), "organize"),
    # FIX-ORG-002: sort/arrange/structure synonyms — BEFORE file_search
    (re.compile(r"\b(sort|arrange|bring\s+order\s+to)\b.{0,30}(my\s+)?(files?|folders?|downloads?)\b", re.I), "organize"),
    (re.compile(r"\b(suggest|recommend)\b.{0,20}(a\s+)?(folder|file|project)\s*(structure|hierarchy|layout|organization)\b", re.I), "organize"),
    (re.compile(r"\bfile\s+organization\b", re.I), "organize"),
    (re.compile(r"\b(help\s+me\s+)?(organize|structure|arrange)\b.{0,20}(my\s+)?notes?\s*folder\b", re.I), "organize"),
    (re.compile(r"\b(oragnaize|organzie|oragnize)\b", re.I), "organize"),

    # ── Cleanup suggestions ──────────────────────────────────────────────────────
    (re.compile(r"(what|which).{0,20}(can|should|could|to).{0,20}(delete|remove|trash|clear|get rid)", re.I), "cleanup"),
    (re.compile(r"(safe to delete|safely delete|safely remove)", re.I), "cleanup"),
    # NHR-001: "find junk/clutter/garbage files" — beat generic file_search
    (re.compile(r"\b(junk|garbage|clutter|cruft)\b.{0,20}files?\b", re.I), "cleanup"),

    # ── RAG / knowledge search — BEFORE file_search (notes-specific guard) ───────
    (re.compile(r"(search|find|look up|recall|what do i know).{0,30}(my notes|my knowledge|local knowledge|knowledge base|from notes)", re.I), "rag_search"),
    (re.compile(r"(in my notes|from my notes|check my notes).{0,30}(about|for|on)", re.I), "rag_search"),

    # ── File operations ──────────────────────────────────────────────────────────
    # file_search before file_list; both before file_read
    (re.compile(r"\b(safe|can i|suggest|what can i)\b.{0,20}(delet|remov|trash|wipe)\b", re.I), "cleanup"),
    (re.compile(r"\b(safe.deletion|deletion.candidate|safe.to.delete|safe.to.remove)\b", re.I), "cleanup"),
    (re.compile(r"\bfree up\b.{0,20}(space|storage|disk|drive)\b", re.I), "cleanup"),
    (re.compile(r"\b(prune|purge|wipe|clear)\b.{0,20}(files?|folder|cache|temp|log)\b", re.I), "cleanup"),
    # FIX-CLEANUP-003: deletion-suggestion / throw-away / clear-out patterns
    # FIX-STRESS-004a: require explicit file/stuff target so "throw away the draft" → gmail_cancel_draft
    (re.compile(r"\b(throw|toss)\s*away\b.{0,30}\b(files?|stuff|things?|data)\b", re.I), "cleanup"),
    (re.compile(r"\b(deletion|removal)\s+(suggestions?|candidates?|ideas?|list)\b", re.I), "cleanup"),
    (re.compile(r"\b(find|show|list)\b.{0,20}\b(deletable|removable|unneeded|unnecessary)\s+(files?|things?|stuff)\b", re.I), "cleanup"),
    (re.compile(r"\bwhat\b.{0,15}\b(to|can|should)\s+(throw|trash|nuke|discard)\b", re.I), "cleanup"),
    (re.compile(r"\b(clear|clean)\s*out\b", re.I), "cleanup"),
    (re.compile(r"\b(cleaup|cleanup\s+suggestion|cleanup\s+idea)\b", re.I), "cleanup"),
    # FIX-S3-007: "clean old cache files", "remove leftover installers", "files I no longer need"
    (re.compile(r"\bclean\b.{0,15}\bold\b.{0,20}\b(cache|log|temp|junk|file)\b", re.I), "cleanup"),
    (re.compile(r"\b(remove|delete|get rid of)\b.{0,20}\b(leftover|stale|old|outdated)\b.{0,20}\b(installer|cache|file|data)\b", re.I), "cleanup"),
    (re.compile(r"\bfiles?\b.{0,15}\b(i\s+)?(no\s+longer\s+need|don.t\s+need|don.t\s+use)\b", re.I), "cleanup"),
    (re.compile(r"\bhelp\b.{0,15}\bclean\s+up\b.{0,20}\b(my\s+)?(drive|disk|mac|machine|computer|system)\b", re.I), "cleanup"),
    (re.compile(r"\b(find|search for|locate|look for)\b.{0,20}\bfiles?\b", re.I), "file_search"),
    (re.compile(r"\bfind (all |every )?.{0,10}\.(py|js|ts|yaml|yml|json|txt|md|sh|toml)\b", re.I), "file_search"),
    (re.compile(r"\bls\b", re.I), "file_list"),
    (re.compile(r"\blist\s+(files?|dir(ectory)?|folder|content)\b", re.I), "file_list"),
    (re.compile(r"\bwhat\s+files?\b.{0,20}(are in|in|inside)\b", re.I), "file_list"),
    (re.compile(r"\bread\b.{0,25}\.(py|js|ts|md|yaml|yml|json|txt|sh|toml|cfg|gitignore)\b", re.I), "file_read"),
    (re.compile(r"\bread\b.{0,20}(the file\b|file contents?\b|contents? of)\b", re.I), "file_read"),
    (re.compile(r"\b(show|display|cat)\b.{0,20}(contents? of|the file\b)\b", re.I), "file_read"),
    # FIX-FR-001: "cat memory.py", "read the config file"
    (re.compile(r"\bcat\b.{0,25}\.(py|js|ts|md|yaml|yml|json|txt|sh|toml|cfg)\b", re.I), "file_read"),
    (re.compile(r"\bread\b.{0,30}\b(the\s+)?(main|config|configuration|settings?)\s+(python\s+)?(file|script)\b", re.I), "file_read"),
    # FIX-S3-002: "show the nightly.py source", "show me adwi/__init__.py" → file_read not inspect_code
    (re.compile(r"\b(show|display|print)\b.{0,10}\b\w+\.(py|js|ts|sh|md)\b", re.I), "file_read"),
    (re.compile(r"\b(show|display)\b.{0,15}\b(adwi/|src/|logs?/)\b", re.I), "file_read"),

    # ── Doctor — BEFORE status (Bug 3 companion: deep check beats shallow) ───────
    (re.compile(r"\b(run doctor|doctor mode)\b", re.I), "doctor"),
    (re.compile(r"\b(full|deep|thorough|complete)\b.{0,15}\b(health.?check|diagnostic)\b", re.I), "doctor"),
    (re.compile(r"\brun\b.{0,15}\b(full\s+)?(diagnostic|health.?check)\b", re.I), "doctor"),

    # ── Self-heal — BEFORE status (Bug 3: service-error superset fix) ────────────
    # Pattern A: verb-first  — "fix/repair/broken/not working ... service"
    (re.compile(r"(fix|repair|restart|broken|not working|isn.t working|crashed|down).{0,20}(setup|stack|service|ollama|docker)", re.I), "self_heal"),
    # Pattern B: subject-first — "docker/ollama/adwi ... not working/broken"
    (re.compile(r"(adwi|setup|stack|docker|ollama|service).{0,20}(not working|isn.t working|broken|crashed|crashing|failing)", re.I), "self_heal"),
    # NHR-004: generic repair — "something is broken", "fix yourself", "self-heal"
    (re.compile(r"(something|things|everything).{0,20}(broken|not working|failing|crashed)", re.I), "self_heal"),
    (re.compile(r"\b(repair|fix|heal)\b.{0,15}\b(yourself|itself|adwi|setup|system|stack)(\s|$)", re.I), "self_heal"),
    (re.compile(r"\bself.?heal\b", re.I), "self_heal"),
    # FIX-HEAL-001: "service is down fix it" and "repair my local AI" patterns
    (re.compile(r"\b(services?|containers?|docker|ollama|stack)\b.{0,15}\bdown\b.{0,20}\b(fix|repair|restart)\b", re.I), "self_heal"),
    (re.compile(r"\bnothing\b.{0,20}(working|running|connecting)\b.{0,20}(fix|repair|help)\b", re.I), "self_heal"),
    (re.compile(r"\b(repair|fix)\b.{0,15}\b(broken\s+containers?|local\s+ai|local\s+stack|my\s+local\s+ai)\b", re.I), "self_heal"),
    (re.compile(r"\badwi\b.{0,5}(self\s+repair|self.?fix)\b", re.I), "self_heal"),

    # FIX-SPRINT-001a: "how fast is X" must fire as benchmark BEFORE status grabs "is adwi responding"
    (re.compile(r"\bhow\s+fast\b.{0,25}\b(adwi|ollama|llama\d*|qwen\d*|mistral|phi|gemma|llm|model|local\s+ai)\b", re.I), "benchmark"),
    # ── Status (Bug 1: word boundaries stop substring false positives) ────────────
    # FIX-STATUS-002: "anything down", "is X available" patterns
    (re.compile(r"\b(anything|something)\b.{0,15}\b(down|broken|offline|unavailable|not\s+responding)\b", re.I), "status"),
    (re.compile(r"\b(is|are)\b.{0,20}\b(ollama|docker|adwi|n8n|redis|api|server|services?|stack|everything)\b.{0,15}\b(available|up|running|reachable|responding|down|offline|unavailable)\b", re.I), "status"),
    (re.compile(r"(check|verify).{0,20}(setup|stack|services|system)", re.I), "status"),

    # FIX-SPRINT-006: "implement the suggested improvement" → implement_idea BEFORE what_next's
    # (suggest|recommend).{0,20}(improvement) pattern fires on "suggested improvement"
    (re.compile(r"\b(?:implement|build|code\s+up|develop)\b.{0,20}\b(?:the\s+)?(?:suggested|recommended|proposed)\b", re.I), "implement_idea"),
    # ── What next ────────────────────────────────────────────────────────────────
    (re.compile(r"(what|what.s).{0,20}(next|build|improve|add|create).{0,20}(adwi|setup|ai|local)", re.I), "what_next"),
    (re.compile(r"(suggest|recommend).{0,20}(next|improvement|feature|capability)", re.I), "what_next"),
    # NHR-007: broader patterns — "adwi improvement ideas", "next feature for adwi"
    (re.compile(r"\b(adwi|local.?ai|my.?ai).{0,30}(improvement|enhancement|feature|idea|roadmap)\b", re.I), "what_next"),
    (re.compile(r"\bnext.{0,20}(feature|capability|improvement).{0,20}(adwi|ai|local|stack)\b", re.I), "what_next"),

    # FIX-WHAT-002: advisory improvement questions → what_next BEFORE daily_improve
    (re.compile(r"\b(how|what)\b.{0,15}\b(should|can|could|would)\b.{0,20}(improv|refactor|enhanc|optimiz).{0,20}\badwi\b", re.I), "what_next"),
    (re.compile(r"\bwhat\b.{0,15}\b(code\s+changes?|improvements?|refactors?)\b.{0,20}\b(adwi|better|make)\b", re.I), "what_next"),
    (re.compile(r"\bgenerate\b.{0,20}\b(todo|to.?do|task)\s+(list|items?)\b.{0,20}\badwi\b", re.I), "what_next"),
    # ── Daily improve — NHR-006: no regex existed; LLM was routing to status/chat ─
    (re.compile(r"\b(daily.?improv|daily.?enhanc|daily.?routine)\b", re.I), "daily_improve"),
    (re.compile(r"\brun.{0,10}daily.{0,10}(improve|maintenance|self.?improve)\b", re.I), "daily_improve"),

    # ── Gmail Phase 15 early guards — MUST precede web_search and git_status ────
    # "what changed in the last reply/thread" must beat git_status "what changed"
    (re.compile(r"\bwhat\s+changed\b.{0,30}\b(?:reply|thread|email|message|conversation)\b", re.I), "gmail_thread_intel"),
    # FIX-STAGE3-001: "open/read/show the latest message" → gmail_read, not thread_intel
    # negative lookahead: "open the latest email from X" falls through to gmail_open
    (re.compile(r"\b(?:open|read|show)\b.{0,10}\blatest\s+(?:message|email|mail)\b(?!\s+from\b)", re.I), "gmail_read"),
    # "latest reply/message/delta" are email-specific, safe before web_search
    (re.compile(r"\blatest\s+(?:reply|message|delta)\b", re.I), "gmail_thread_intel"),
    # "latest update in this thread/email" must beat web_search "latest ... update"
    (re.compile(r"\blatest\s+update\b.{0,30}\b(?:thread|email|conversation|message)\b", re.I), "gmail_thread_intel"),

    # ── Gmail Phase 17 early guard — "save tasks to daily note" must precede obsidian_daily ──
    (re.compile(r"\b(?:save|add|put|write|export)\b.{0,30}\b(?:tasks?|items?|checklist|action\s+items?|todos?)\b.{0,50}\bdaily\s+note\b", re.I), "gmail_tasks_save"),

    # ── Browse — URL/domain visit patterns BEFORE web_search ─────────────────────
    (re.compile(r"\b(visit|browse\s+to|navigate\s+to)\b.{0,50}(https?://|\.(com|io|org|dev|net|ai|co|app))\b", re.I), "browse"),
    (re.compile(r"\bfetch\b.{0,40}(https?://|content\s+of\s+https?://)", re.I), "browse"),
    (re.compile(r"\b(open|go\s+to)\b.{0,20}(the\s+)?(homepage|website)\b.{0,40}https?://", re.I), "browse"),
    (re.compile(r"\bdownload\b.{0,30}(from\s+the\s+web|a\s+file\s+from\s+https?://)", re.I), "browse"),

    # ── Web search ───────────────────────────────────────────────────────────────
    (re.compile(r"(search the web|web search|google|search online|look up online|find online|search internet).{0,50}", re.I), "web_search"),
    (re.compile(r"(what('s| is) (the latest|new in|current).{0,30}(release|version|update|news|changelog))", re.I), "web_search"),
    # FIX-WEB-001: "look up X guide/version/performance" patterns — BEFORE model_status
    (re.compile(r"\blook\s+up\b.{0,40}(version|guide|tutorial|how[\s-]to|docs?|documentation|performance|benchmark|comparison|ranking|list)\b", re.I), "web_search"),
    (re.compile(r"\bfind\b.{0,20}(the\s+)?(current|latest)\b.{0,20}\bversion\b.{0,30}\b(llama|ollama|qwen|mistral|phi|gemma|python|node)\b", re.I), "web_search"),
    # FIX-WEB-002: "search for the latest X" / "search for information about X"
    (re.compile(r"\bsearch\s+(for\s+)?(the\s+)?(latest|current|recent|newest)\b", re.I), "web_search"),
    (re.compile(r"\bsearch\s+for\b.{0,30}\b(information|info|details?|news|updates?|tutorial|guide|docs?)\b", re.I), "web_search"),

    # ── Obsidian daily — BEFORE obsidian_search (Bug 4: daily-note guard) ────────
    (re.compile(r"\b(daily.?note|today.{0,5}note|obsidian.{0,5}daily)\b", re.I), "obsidian_daily"),
    (re.compile(r"\bopen\b.{0,15}\btoday.{0,5}\bnote\b", re.I), "obsidian_daily"),
    # FIX-OBS-002: entry/log/journal synonyms + "dailly" typo
    (re.compile(r"\b(show|read|open)\b.{0,15}\bmy\s+daily\s+(log|note|journal|entry|notes?)\b", re.I), "obsidian_daily"),
    (re.compile(r"\btoday.{0,5}\b(obsidian\s+)?(entry|journal|log)\b", re.I), "obsidian_daily"),
    (re.compile(r"\bda[il]{2,4}y\s+(note|entry|journal|log)\b", re.I), "obsidian_daily"),

    # ── Obsidian vault ───────────────────────────────────────────────────────────
    (re.compile(r"(obsidian|vault|my notes?).{0,20}(search|find|look up|what do i have)", re.I), "obsidian_search"),
    (re.compile(r"(open|read|show).{0,10}(obsidian|vault|note).{0,30}", re.I), "obsidian_search"),
    # Verb-first ordering: "search my obsidian vault / notes for ..."
    (re.compile(r"\bsearch\b.{0,20}\b(obsidian|vault)\b", re.I), "obsidian_search"),

    # ── YouTube — NHR-002: non-URL phrasing (URL form handled by extract_youtube_url) ─
    (re.compile(r"\byoutube\b.{0,40}(summar|transcri|watch|clip|video|channel|tutorial)\b", re.I), "youtube"),
    (re.compile(r"(summar|transcri|explain).{0,20}\byoutube\b", re.I), "youtube"),
    (re.compile(r"\b(yt\s+video|youtu\.be|youtube\.com)\b", re.I), "youtube"),

    # ── Browse / fetch URL ───────────────────────────────────────────────────────
    (re.compile(r"(browse|visit|open|fetch|go to|check out|navigate to).{0,15}(https?://|website|site|webpage|url|\.(com|io|org|dev|net))", re.I), "browse"),

    # ── Nightly maintenance ──────────────────────────────────────────────────────
    # FIX-NIGHT-001: "generate a summary of logs" / bare "nightly" / "last thing that ran"
    (re.compile(r"\bgenerate\b.{0,20}\b(summary|report|digest)\b.{0,20}\b(logs?|nightly|daily|adwi)\b", re.I), "nightly_status"),
    (re.compile(r"\bgenerate\b.{0,15}\bmy\s+daily\s+report\b", re.I), "nightly_status"),
    (re.compile(r"^nightly\s*$", re.I), "nightly_status"),
    (re.compile(r"\bwhat.{0,10}last.{0,10}(ran|run|executed|triggered).{0,20}\b(nightly|maintenance|cron)\b", re.I), "nightly_status"),
    (re.compile(r"\b(nightly|night.?run)\b.{0,20}(status|log|report|last run|results?)\b", re.I), "nightly_status"),
    (re.compile(r"\b(when.{0,10}(did.{0,10})?nightly|last.{0,10}nightly|show.{0,10}nightly)\b", re.I), "nightly_status"),
    (re.compile(r"\bnightly.{0,10}log\b", re.I), "nightly_status"),
    (re.compile(r"\b(run nightly|trigger nightly|nightly maintenance|run.{0,10}daily maintenance)\b", re.I), "nightly_run"),

    # ── Model status / switching ─────────────────────────────────────────────────
    (re.compile(r"\b(what|which)\b.{0,15}\bmodel\b.{0,20}\b(am i|are you|is active|running|using|current|loaded)\b", re.I), "model_status"),
    (re.compile(r"\bmodel\b.{0,15}\b(status|active|current|running|loaded|info)\b", re.I), "model_status"),
    (re.compile(r"\b(show|display)\b.{0,15}\bmodel\b.{0,20}\b(status|info|version)\b", re.I), "model_status"),
    # FIX-S3-005: "what models are available", "what llm is running", "what version of llama"
    (re.compile(r"\bwhat\s+(models?|llms?|ollama\s+models?)\s+(are\s+)?(available|loaded|running|installed)\b", re.I), "model_status"),
    (re.compile(r"\bwhat\s+(llm|model|ai)\s+(is\s+)?(running|loaded|active|current|being\s+used)\b", re.I), "model_status"),
    (re.compile(r"\bwhat\s+version\s+of\s+(llama|ollama|qwen|mistral|phi|gemma)\b", re.I), "model_status"),
    (re.compile(r"\b(switch|use|change)\b.{0,15}(to\s+)?(local model|local llm|local ai)\b", re.I), "use_local"),
    (re.compile(r"\buse\b.{0,10}\b(qwen|llama|mistral|phi|gemma)\b", re.I), "use_local"),
    (re.compile(r"\b(switch|change|use)\b.{0,15}(to\s+)?(cloud model|cloud api|cloud llm|gemini|openai)\b", re.I), "use_cloud"),
    (re.compile(r"\bswitch to cloud\b", re.I), "use_cloud"),

    # ── Voice I/O ────────────────────────────────────────────────────────────────
    (re.compile(r"\b(voice input|voice mode|voice.{0,10}recording|start.{0,10}voice|listen.{0,10}voice)\b", re.I), "voice_in"),
    (re.compile(r"\bstart.{0,15}(recording|listening)\b", re.I), "voice_in"),
    (re.compile(r"\b(text.to.speech|tts\b|speak.{0,15}this|say.{0,20}(aloud|out loud)|read.{0,10}aloud|read.{0,10}this.{0,10}out)\b", re.I), "voice_out"),

    # ── Backup status / log ──────────────────────────────────────────────────────
    (re.compile(r"\b(backup.{0,10}(status|health|check|recent|current)|last.{0,10}backup|when.{0,15}(was.{0,5})?backup)\b", re.I), "backup_status"),
    (re.compile(r"\bbackup.{0,15}(log|history|logs)\b", re.I), "backup_log"),

    # ── Patch adwi — NHR-003: code changes via aider ─────────────────────────────
    (re.compile(r"\b(run|use|apply).{0,10}\baider\b", re.I), "patch_adwi"),
    (re.compile(r"\b(self.?patch|auto.?patch)\b.{0,20}(adwi|code|codebase)", re.I), "patch_adwi"),
    (re.compile(r"\bpatch\b.{0,15}\badwi\b", re.I), "patch_adwi"),
    # FIX-S3-009: typo "patcch adwi" + "apply adwi improvements" imperative
    (re.compile(r"\bpat[ct]ch\b.{0,15}\badwi\b", re.I), "patch_adwi"),
    (re.compile(r"\bapply\b.{0,20}\badwi\b.{0,20}\b(improvements?|patches?|fixes?|updates?)\b", re.I), "patch_adwi"),

    # ── Inspect code — NHR-008: code review of adwi source files ─────────────────
    (re.compile(r"\b(inspect|review|look at|examine).{0,20}(adwi.{0,10}\.py|adwi.?code|adwi.?source)\b", re.I), "inspect_code"),
    (re.compile(r"\b(inspect|review).{0,15}(adwi_cli|nightly\.py|memory\.py|backup\.py|grader\.py)\b", re.I), "inspect_code"),
    (re.compile(r"\b(find bugs in|check for bugs in|code review).{0,20}\badwi\b", re.I), "inspect_code"),

    # ── Fix error / exception — catches pasted tracebacks and HTTP error codes ────
    (re.compile(r"\b(TypeError|ValueError|KeyError|AttributeError|SyntaxError|ImportError|ModuleNotFoundError|NameError|RuntimeError|IndexError|OSError|IOError|FileNotFoundError|PermissionError|ZeroDivisionError|StopIteration|AssertionError|RecursionError|MemoryError|TimeoutError|ConnectionError|UnicodeError|ValidationError)\b\s*:", re.I), "fix_error"),
    # FIX-S3-003: exception class name without colon (e.g. "getting ModuleNotFoundError when I run")
    (re.compile(r"\b(getting|seeing|got|had)\s+(a\s+)?(ModuleNotFoundError|TypeError|ValueError|KeyError|AttributeError|SyntaxError|ImportError|NameError|RuntimeError|IndexError|OSError|FileNotFoundError|PermissionError|ConnectionError|TimeoutError|ValidationError)\b", re.I), "fix_error"),
    (re.compile(r"\b(getting|seeing|got)\b.{0,20}\b(error|exception|traceback)\b", re.I), "fix_error"),
    (re.compile(r"\b\d{3}\s+(not found|bad gateway|forbidden|service unavailable|unauthorized|too many requests|internal server error)\b", re.I), "fix_error"),
    (re.compile(r"\bgetting\s+(a\s+)?\d{3}\b", re.I), "fix_error"),
    (re.compile(r"\b(fix|help.{0,5}fix)\s+this\s+(error|exception|bug)\b", re.I), "fix_error"),
    (re.compile(r"\[Errno\s+\d+\]", re.I), "fix_error"),

    # ── Eval / test ──────────────────────────────────────────────────────────────
    # FIX-EVAL-003: routing eval patterns BEFORE test_adwi; "trigger routing evaluation" fix
    (re.compile(r"\b(test|check|evaluate|verify)\b.{0,15}\b(adwi\s+)?routing\b", re.I), "eval_routing"),
    (re.compile(r"\b(run|start|trigger|evaluate)\b.{0,20}\brouting\s+(eval(uation)?|tests?)\b", re.I), "eval_routing"),
    (re.compile(r"\badwi\b.{0,10}\beval\b.{0,10}\brouting\b", re.I), "eval_routing"),
    (re.compile(r"\b(run|start|trigger).{0,15}(routing.?tests?|eval.?routing|routing\s+eval(uation)?)\b", re.I), "eval_routing"),
    (re.compile(r"\b(run|start).{0,15}\b(adwi.?eval|eval.?adwi)\b", re.I), "eval_adwi"),
    (re.compile(r"\bevaluate\b.{0,10}\badwi\b", re.I), "eval_adwi"),
    # FIX-EVAL-002: "eval adwi pls", "start evaluation", "run eval" patterns
    (re.compile(r"\beval\s+adwi\b", re.I), "eval_adwi"),
    (re.compile(r"\bstart\b.{0,20}\b(adwi\s+)?(evaluation|eval)\b", re.I), "eval_adwi"),
    (re.compile(r"\b(run|execute|start)\b.{0,10}\beval\b(?!\s*[_\-]?\s*routing)", re.I), "eval_adwi"),
    (re.compile(r"\b(run|execute).{0,15}(adwi.?tests?|test.?adwi)\b", re.I), "test_adwi"),
    # FIX-TEST-002: "test adwi", "run tests", "test suite" patterns
    (re.compile(r"\btest\b.{0,10}\badwi\b", re.I), "test_adwi"),
    (re.compile(r"\b(run|execute).{0,15}(the\s+)?(unit\s*tests?|test\s*suite|adwi\s*tests?)\b", re.I), "test_adwi"),
    (re.compile(r"\b(adwi).{0,10}\btest\s*(run|suite|pass|fail)?\b", re.I), "test_adwi"),
    (re.compile(r"^(run|execute)\s+tests?\s*(please|pls)?\s*$", re.I), "test_adwi"),

    # ── GitHub repo visibility — BEFORE git_status and github_connected ───────────
    (re.compile(r"(make|set|change|convert).{0,20}(git.?repo|repo|repository).{0,20}(public|private|open source)", re.I), "github_visibility"),
    (re.compile(r"(make|set).{0,15}(public|private).{0,15}(repo|repository|github)", re.I), "github_visibility"),
    (re.compile(r"(repo|repository).{0,20}(visibility|public|private)", re.I), "github_visibility"),

    # ── GitHub connectivity — BEFORE git_status ───────────────────────────────────
    (re.compile(r"(is|are).{0,20}(github|git hub).{0,20}(connected|linked|set up|configured|working|authenticated|logged in)", re.I), "github_connected"),
    (re.compile(r"(is adwi|adwi).{0,20}(connected|linked).{0,20}(github|git)", re.I), "github_connected"),
    (re.compile(r"(github|git hub).{0,20}(account|auth|login|connection|access)", re.I), "github_connected"),
    (re.compile(r"(connected to|link(ed)? to|set up).{0,20}(github|git hub)", re.I), "github_connected"),

    # ── Git status (Bug 7: broadened patterns) ────────────────────────────────────
    (re.compile(r"git\s+(status|diff|log|show|repos?)\b", re.I), "git_status"),
    (re.compile(r"(what (changed|committed)|show commits|latest commit|my repos?)\b", re.I), "git_status"),
    (re.compile(r"\b(show|what|are|is)\b.{0,20}\b(recent commits?|unstaged|staged files?|uncommitted|current branch|repo clean)\b", re.I), "git_status"),
    (re.compile(r"\b(what.{0,10}(last|did).{0,10}commit|current branch|git\s+(stat|branch))\b", re.I), "git_status"),
    (re.compile(r"\brepo\b.{0,15}\b(clean|dirty|status|changes)\b", re.I), "git_status"),
    # FIX-S3-008: "what did I change", "what's modified", "show me what's changed"
    (re.compile(r"\bwhat\s+(did\s+i|have\s+i).{0,10}(change|modify|edit|commit)\b", re.I), "git_status"),
    (re.compile(r"\bwhat.{0,5}(is|has|s)\s+(changed|modified|staged)\b", re.I), "git_status"),
    (re.compile(r"\bshow\s+(me\s+)?(what.{0,5}changed|the\s+diff|changes?\s+since)\b", re.I), "git_status"),

    # FIX-SPRINT-003: "cmd_name function/handler in adwi" → inspect_code before generate_image
    # catches "generate_image function in adwi" — the _ + "function" + "in adwi" signal code lookup
    (re.compile(r"\b[a-z]+_[a-z_]+\b.{0,20}\b(?:function|handler|method|command)\b.{0,20}\bin\s+adwi\b", re.I), "inspect_code"),
    (re.compile(r"\b(?:show|find|where\s+is)\b.{0,15}\bthe\b.{0,15}\b[a-z]+_[a-z_]+\b.{0,10}\b(?:function|handler|method)\b", re.I), "inspect_code"),
    # ── Image generation ─────────────────────────────────────────────────────────
    (re.compile(r"(generate|create|draw|make|design).{0,20}(an? )?(image|picture|photo|illustration|artwork)", re.I), "generate_image"),

    # ── Code execution ───────────────────────────────────────────────────────────
    # FIX-PATCH-002: "run code improvement" / "self-improve adwi" → patch_adwi BEFORE run_code steals them
    (re.compile(r"\b(self.?improv|auto.?improv).{0,15}\badwi\b", re.I), "patch_adwi"),
    (re.compile(r"\b(run|execute)\b.{0,15}(self.?improv|autonomous\s*(code\s*)?improv)", re.I), "patch_adwi"),
    (re.compile(r"\b(run|execute)\b.{0,15}\bcode\s+improv", re.I), "patch_adwi"),
    # run_code: added \b around "test" to prevent "latest" ⊇ "test" false positive (FIX-RC-001)
    (re.compile(r"\b(run|execute|test)\b.{0,15}(this |the )?(python|code|script)\b", re.I), "run_code"),

    # ── Benchmark ────────────────────────────────────────────────────────────────
    # FIX-S3-001: "how fast is llama3.1:8b", typo "bechmark", tokens/sec variants
    # FIX-SPRINT-001b: drop trailing \b to allow model versions like "llama3.1:8b"
    (re.compile(r"\bhow\s+fast\s+(is|does|was|are)\b.{0,30}\b(llama|qwen|mistral|phi|gemma|ollama|adwi|model|llm)\d*", re.I), "benchmark"),
    (re.compile(r"\b(tokens?[/_]s|tok[/_]s|t[/_]s)\b", re.I), "benchmark"),
    (re.compile(r"\b(inference|llm|model|ollama).{0,20}\b(throughput|latency\s+benchmark|speed\s+test)\b", re.I), "benchmark"),
    (re.compile(r"\b(bechmark|benchamrk|benchmarck)\b", re.I), "benchmark"),
    (re.compile(r"(benchmark|speed.?test|how fast|tokens? per second).{0,20}(adwi|model|local|ollama)\b", re.I), "benchmark"),
    # FIX-SPRINT-001c: "tokens per second", "inference speed", "how performant" without requiring model name
    (re.compile(r"\b(?:how\s+many\s+)?tokens?\s+per\s+(?:sec(?:ond)?|s)\b", re.I), "benchmark"),
    # require "my" to distinguish measurement ("my inference speed") from advisory ("what affects inference speed")
    (re.compile(r"\bmy\s+inference\s+(?:speed|rate|throughput|perf)\b", re.I), "benchmark"),
    (re.compile(r"\bhow\s+perf(?:ormant)?\b.{0,30}\b(llama|qwen|mistral|phi|gemma|ollama|model|llm)\d*", re.I), "benchmark"),

    # ── Gmail Phase 8: remove-attachment intent — MUST precede gmail_attach_file ──────────────
    # Pattern 1: any remove/detach/drop + "attachment" keyword (unambiguous Gmail context)
    (re.compile(r"\b(?:remove|detach|drop)\b.{0,30}\battachment\b", re.I), "gmail_remove_attachment"),
    # Pattern 2: "detach" + file-type (detach is unambiguous — only used in attachment context)
    (re.compile(r"\bdetach\b.{0,30}\b(?:the\s+)?(?:pdf|file|document|spreadsheet|image|invoice|report|deck)\b", re.I), "gmail_remove_attachment"),
    # FIX-STRESS-009a: "remove the attached document" (attached + doc type, no trailing from required)
    (re.compile(r"\b(?:remove|detach)\b.{0,30}\battached\b.{0,30}\b(?:pdf|file|document|spreadsheet|image|invoice|report|deck)\b", re.I), "gmail_remove_attachment"),
    # Pattern 3: remove/drop + file-type + REQUIRED "from draft/email/message" (allows this/that)
    (re.compile(r"\b(?:remove|drop|delete)\b.{0,30}\b(?:the\s+)?(?:pdf|file|document|spreadsheet|image|invoice|report|deck)\b.{0,20}\bfrom\s+(?:(?:the|this|that)\s+)?(?:draft|email|message)\b", re.I), "gmail_remove_attachment"),
    # Pattern 4: "draft without attachment"
    (re.compile(r"\bdraft\b.{0,20}\b(?:without|no\s+attachment|remove\s+the)\b", re.I), "gmail_remove_attachment"),

    # ── Gmail Phase 7: attach-file intent — MUST precede gmail_rewrite_draft ─────────────────
    # ("add the PDF to this draft" would otherwise match gmail_rewrite_draft's add/include pattern)
    (re.compile(r"\battach\b.{0,50}\b(?:pdf|document|file|spreadsheet|invoice|report|deck|image|photo|attachment)\b", re.I), "gmail_attach_file"),
    # FIX-STRESS-009c: added "presentation|document|file" to file-type alternation
    (re.compile(r"\b(?:add|include)\b.{0,20}\b(?:the\s+)?(?:pdf|spreadsheet|invoice|report|deck|image|attachment|presentation|document|file)\b.{0,30}\b(?:(?:to|in)\s+(?:(?:this|the)\s+)?(?:draft|email|message|reply))\b", re.I), "gmail_attach_file"),
    (re.compile(r"\battach\b.{0,30}\b(?:that|the|saved)\b.{0,20}\battachment\b", re.I), "gmail_attach_file"),

    # ── Gmail Phase 14: subject update — MUST precede Phase 4 rewrite ───────────────────────
    # gmail_update_subject — "rewrite the subject", "make the subject clearer", "better subject"
    (re.compile(r"\b(?:rewrite|update|change|improve|fix)\b.{0,20}\bsubject\b", re.I), "gmail_update_subject"),
    # "make the subject clearer" — subject before style word
    (re.compile(r"\b(?:make|write)\b.{0,20}\bsubject\b.{0,25}\b(?:better|clearer|shorter|stronger|cleaner|good|clear|more\s+professional|more\s+concise)\b", re.I), "gmail_update_subject"),
    # "write a better subject" / "write a clearer subject line" — style before subject
    (re.compile(r"\b(?:write|give\s+me)\b.{0,20}\b(?:a\s+)?(?:better|clearer|shorter|stronger|good|clear|more\s+professional)\b.{0,10}\bsubject\b", re.I), "gmail_update_subject"),
    (re.compile(r"\bsubject\b.{0,25}\b(?:is|feels?|seems?|sounds?)\b.{0,20}\b(?:weak|vague|unclear|bad|poor|generic|long|boring)\b", re.I), "gmail_update_subject"),
    (re.compile(r"\bgive\s+me\b.{0,20}\b(?:a\s+)?(?:better|clearer|different|new|good)\b.{0,10}\bsubject\b", re.I), "gmail_update_subject"),

    # ── Gmail Phase 4: rewrite intent — MUST precede Phase 3 send/cancel patterns ──────────
    # Requires "it/the draft/the reply/this" + a style word, or "mention/add X to the draft"
    # FIX-STRESS-005: "rewrite the draft" (no style word required) and "rewrite to be warmer"
    (re.compile(r"\brewrite\b.{0,25}\b(?:it|the\s+draft|the\s+reply|this|the\s+email)\b", re.I), "gmail_rewrite_draft"),
    (re.compile(r"\brewrite\b.{0,30}\bto\s+(?:be|sound)\b", re.I), "gmail_rewrite_draft"),
    (re.compile(r"\b(?:make|rewrite|revise|edit)\b.{0,20}\b(?:it|the\s+draft|the\s+reply|this|the\s+email)\b.{0,40}\b(?:shorter|longer|brief(?:er)?|concis(?:e|er)|professional(?:ly)?|formal(?:ly)?|casual(?:ly)?|warm(?:er|ly)?|friendli(?:er)?|direct(?:ly)?|clear(?:er)?|natural(?:ly)?|informal(?:ly)?|polite(?:ly)?|robotic|engaging)\b", re.I), "gmail_rewrite_draft"),
    (re.compile(r"\bturn\s+(?:this|it)\b.{0,30}\binto\b.{0,30}\b(?:shorter|brief|concise|professional|update|summary|formal|casual|polite|warm|friendly|direct|natural)\b", re.I), "gmail_rewrite_draft"),
    (re.compile(r"\bwrite\b.{0,10}(?:a|an)\s+(?:shorter|briefer|more\s+(?:concise|direct|professional|formal|casual|friendly|polite|natural|warm))\b.{0,20}\b(?:version|draft|email|message|reply)?\b", re.I), "gmail_rewrite_draft"),
    (re.compile(r"\b(?:mention|add|include)\b.{0,50}\b(?:in|to)\s+(?:the\s+)?(?:draft|reply|email|message)\b", re.I), "gmail_rewrite_draft"),

    # ── Gmail Phase 5: add-cc / add-bcc — MUST precede Phase 3 (avoid cc/bcc in compose hitting here) ──
    # gmail_add_cc — "add cc Priya", "cc Priya to the draft", "cc Priya on this email"
    (re.compile(r"\badd\s+cc\b", re.I), "gmail_add_cc"),
    (re.compile(r"\bcc\b.{0,40}\b(?:to\s+(?:the\s+)?(?:draft|email|message)|on\s+(?:this|the\s+(?:draft|email|message)))\b", re.I), "gmail_add_cc"),
    # gmail_add_bcc — "add bcc me", "bcc Rahul on this draft", "bcc me on the email"
    (re.compile(r"\badd\s+bcc\b", re.I), "gmail_add_bcc"),
    (re.compile(r"\bbcc\b.{0,40}\b(?:to\s+(?:the\s+)?(?:draft|email|message)|on\s+(?:this|the\s+(?:draft|email|message)))\b", re.I), "gmail_add_bcc"),

    # ── Gmail Phase 13: reschedule/open scheduled sends — MUST precede Phase 6 (attachments) ──
    # gmail_open_scheduled_draft needs to beat gmail_save_attachment ("open...invoice")
    (re.compile(r"\breschedule\b", re.I), "gmail_reschedule_send"),
    (re.compile(r"\b(?:move|push|delay|postpone)\b.{0,30}\b(?:scheduled|the\s+(?:email|send|message|draft))\b.{0,30}\b(?:to|until)\b", re.I), "gmail_reschedule_send"),
    (re.compile(r"\bchange\b.{0,20}\bscheduled\b.{0,20}\b(?:time|date|send|email|message)\b", re.I), "gmail_reschedule_send"),
    (re.compile(r"\b(?:open|reopen|switch\s+to|load)\b.{0,20}\bscheduled\b.{0,20}\b(?:draft|email|send|message)\b", re.I), "gmail_open_scheduled_draft"),

    # ── Gmail Phase 6: attachment intents — MUST precede gmail_summarize (lower down) ──────
    # gmail_summarize_attachment — before Phase 3 AND before the generic gmail_summarize block
    (re.compile(r"\b(?:summarize|tldr|what.s\s+in|whats\s+in)\b.{0,30}\b(?:the\s+)?(?:attached\s+)?(?:attachment|pdf|document|invoice|receipt|spreadsheet)\b", re.I), "gmail_summarize_attachment"),
    (re.compile(r"\bwhat(?:'s|\s+is)\b.{0,30}\b(?:in\s+)?(?:the\s+)?(?:attached|attachment)\b", re.I), "gmail_summarize_attachment"),
    # FIX-STRESS-009d: "what does the attached document say"
    (re.compile(r"\bwhat\b.{0,30}\b(?:attached|attachment)\b.{0,30}\b(?:document|pdf|file|spreadsheet|invoice)?\b.{0,15}\bsay\b", re.I), "gmail_summarize_attachment"),
    # gmail_save_attachment — "save/download/open the PDF/attachment/invoice"
    (re.compile(r"\b(?:save|download|open)\b.{0,30}\b(?:the\s+)?(?:attached\s+)?(?:attachment|pdf|document|invoice|receipt|image|spreadsheet)\b", re.I), "gmail_save_attachment"),
    (re.compile(r"\b(?:save|download)\b.{0,25}\b(?:that|this|first|second|third)\b.{0,20}\b(?:attachment|file|pdf|document)\b", re.I), "gmail_save_attachment"),
    # FIX-STAGE3-002: "which draft has the PDF attached" → list_drafts, not list_attachments
    (re.compile(r"\bwhich\s+draft\b", re.I), "gmail_list_drafts"),
    # gmail_list_attachments — "show/list attachments", "any files attached?"
    (re.compile(r"\b(?:show|list|view|see)\b.{0,25}\battachment", re.I), "gmail_list_attachments"),
    (re.compile(r"\battachment.{0,25}\b(?:on|in|for|from)\b", re.I), "gmail_list_attachments"),
    (re.compile(r"\bany\s+attachments?\b", re.I), "gmail_list_attachments"),
    # FIX-STRESS-009e: "any files attached", "what attachments are there"
    (re.compile(r"\bany\b.{0,20}\bfiles?\b.{0,15}\battach", re.I), "gmail_list_attachments"),
    (re.compile(r"\bwhat\b.{0,30}\battachments?\b.{0,20}\bthere\b", re.I), "gmail_list_attachments"),
    (re.compile(r"\b(?:what|which)\b.{0,20}\b(?:file|attachment|pdf|document).{0,15}\battach", re.I), "gmail_list_attachments"),

    # ── Gmail Phase 12: multi-draft management — MUST precede Phase 11/10 patterns ──────────
    # gmail_list_drafts — plural "drafts" (beats gmail_list_scheduled for "show scheduled drafts")
    (re.compile(r"\b(?:list|show)\b.{0,5}\b(?:my\s+|all\s+)?drafts\b", re.I), "gmail_list_drafts"),
    (re.compile(r"\b(?:show|view|see)\b.{0,20}\ball\s+drafts\b", re.I), "gmail_list_drafts"),
    (re.compile(r"\b(?:show|list)\b.{0,20}\b(?:scheduled|unscheduled|unsent|pending)\s+drafts\b", re.I), "gmail_list_drafts"),
    (re.compile(r"\bwhat\s+drafts\b.{0,20}\b(?:do\s+I\s+have|are\s+there)\b", re.I), "gmail_list_drafts"),
    # gmail_open_draft — ordinal/name selection; MUST precede gmail_send_draft and gmail_show_draft
    (re.compile(r"\b(?:open|switch\s+to|go\s+(?:back\s+)?to|load|select|use)\b.{0,30}\b(?:\d|first|second|third|fourth|fifth|last)\b.{0,10}\bdraft\b", re.I), "gmail_open_draft"),
    (re.compile(r"\b(?:open|switch\s+to|go\s+(?:back\s+)?to|load|select)\b.{0,5}draft\s+[1-9]\b", re.I), "gmail_open_draft"),
    (re.compile(r"\bsend\b.{0,5}(?:draft\s+[1-9]|the\s+(?:first|second|third|fourth|fifth|last)\s+draft)\b", re.I), "gmail_open_draft"),
    (re.compile(r"\bsend\b.{0,5}the\s+(?!draft\b)\w+\s+draft\b", re.I), "gmail_open_draft"),
    (re.compile(r"\b(?:open|switch\s+to|go\s+(?:back\s+)?to)\b.{0,5}the\s+(?!draft\b)\w+\s+draft\b", re.I), "gmail_open_draft"),
    # gmail_delete_draft — targeted deletion (ordinal or named); MUST precede gmail_cancel_draft
    (re.compile(r"\b(?:delete|remove|trash)\b.{0,5}(?:draft\s+[1-9]|the\s+(?:first|second|third|fourth|fifth|last)\s+draft)\b", re.I), "gmail_delete_draft"),
    (re.compile(r"\b(?:delete|remove|trash)\b.{0,5}the\s+(?!draft\b)(?!that\b)(?!current\b)\w+\s+draft\b", re.I), "gmail_delete_draft"),
    (re.compile(r"\b(?:cancel|delete|remove)\b.{0,15}\bold\b.{0,10}\bdraft\b", re.I), "gmail_delete_draft"),

    # ── Gmail Phase 17: extract tasks / save / remind — MUST precede Phase 11 ──────────────
    # gmail_tasks_remind — "create/set reminders for those action items" — BEFORE followup_reminder
    (re.compile(r"\bcreate\b.{0,15}\breminders?\b.{0,40}\b(?:for\s+(?:those|these|the|them|each|all)\b|for\s+(?:the\s+)?(?:action\s+items?|deadlines?|tasks?))\b", re.I), "gmail_tasks_remind"),
    (re.compile(r"\bset\b.{0,15}\breminders?\b.{0,40}\b(?:for\s+(?:those|these|the|them|each|all)\b|for\s+(?:the\s+)?(?:action\s+items?|deadlines?|tasks?))\b", re.I), "gmail_tasks_remind"),
    (re.compile(r"\bremind\s+me\b.{0,40}\b(?:about\s+(?:those|these|each)\b|about\s+(?:the\s+)?(?:action\s+items?|deadlines?|tasks?))\b", re.I), "gmail_tasks_remind"),
    # gmail_tasks_save — "save those tasks to Obsidian", "export checklist", "add tasks to my notes"
    (re.compile(r"\b(?:save|add|put|write|export)\b.{0,30}\b(?:tasks?|items?|checklist|action\s+items?|todos?)\b.{0,40}\b(?:to|in(?:to)?)\b.{0,20}\b(?:obsidian|daily\s+note|my\s+notes?|my\s+list)\b", re.I), "gmail_tasks_save"),
    (re.compile(r"\b(?:save|add|put|export)\b.{0,20}\b(?:those?|these?|them)\b.{0,20}\b(?:tasks?|items?|checklist|action\s+items?|todos?)\b", re.I), "gmail_tasks_save"),
    (re.compile(r"\b(?:save|export)\b.{0,20}\b(?:the\s+)?(?:extracted\s+)?(?:tasks?|checklist|action\s+items?)\b", re.I), "gmail_tasks_save"),
    # gmail_extract_tasks — "turn this email into tasks", "extract deadlines", "what deadlines are here"
    # FIX-STRESS-011: "turn it into tasks" — pronoun alone without explicit email noun
    (re.compile(r"\b(?:turn|convert)\b.{0,20}\b(?:it|this|that)\b.{0,20}\b(?:into?|to)\b.{0,20}\b(?:tasks?|todos?|checklist|action\s+items?)\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\b(?:turn|convert)\b.{0,30}\b(?:this|the|it)\b.{0,20}\b(?:email|thread|message)\b.{0,20}\b(?:into?|to)\b.{0,20}\b(?:tasks?|todo|checklist|action\s+items?)\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\bextract\b.{0,30}\b(?:action\s+items?|tasks?|deadlines?|decisions?|asks?|due\s+dates?)\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\bextract\b.{0,30}\bdates?\b.{0,30}\b(?:from|in)\b.{0,20}\b(?:this|the)\b.{0,20}\b(?:email|thread|message)\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\bwhat\s+(?:deadlines?|due\s+dates?|dates?)\b.{0,30}\b(?:are\s+(?:in|mentioned)|(?:mentioned|are)\s+(?:here|in\s+(?:this|the)))\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\b(?:make|create|build|write|generate)\b.{0,25}\b(?:a\s+)?(?:follow.?up\s+checklist|task\s+list|todo(?:\s+|-)list|to.?do\s+list)\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\b(?:make|create|build|write|generate)\b.{0,30}\b(?:a\s+)?checklist\b.{0,50}\b(?:from|for|of)\b.{0,20}\b(?:this|the)\b.{0,20}\b(?:email|thread|message)\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\bsummarize\b.{0,30}\b(?:this|the)\b.{0,20}\b(?:email|thread)\b.{0,30}\bas\b.{0,20}\b(?:tasks?|todos?|action\s+items?|a?\s*checklist)\b", re.I), "gmail_extract_tasks"),
    (re.compile(r"\bwhat\s+follow.?ups?\s+(?:should|do)\s+I\b", re.I), "gmail_extract_tasks"),

    # ── Gmail Phase 11: follow-up reminders — MUST precede Phase 10 patterns ─────────────
    # gmail_cancel_followup FIRST (cancel+reminder must win over cancel+scheduled)
    (re.compile(r"\bcancel\b.{0,25}\b(?:follow.?up|reminder|that\s+reminder)\b", re.I), "gmail_cancel_followup"),
    (re.compile(r"\b(?:remove|delete|stop)\b.{0,20}\breminder\b", re.I), "gmail_cancel_followup"),
    # gmail_list_followups
    (re.compile(r"\b(?:show|list|view|what.{0,10}are)\b.{0,20}\b(?:follow.?up|pending\s+reminder)s?\b", re.I), "gmail_list_followups"),
    (re.compile(r"\b(?:what\s+(?:threads?|emails?)\s+am\s+I|what\s+am\s+I)\b.{0,20}\b(?:waiting|follow(?:ing)?)\b", re.I), "gmail_list_followups"),
    (re.compile(r"\b(?:pending|open)\s+follow.?ups?\b", re.I), "gmail_list_followups"),
    (re.compile(r"\b(?:who|what).{0,20}\b(?:hasn.t|have\s+not|haven.t)\s+replied\b", re.I), "gmail_list_followups"),
    # gmail_followup_reminder — remind me / set follow-up / if no reply
    (re.compile(r"\b(?:remind\s+me|set\s+(?:a\s+)?(?:follow.?up|reminder))\b", re.I), "gmail_followup_reminder"),
    (re.compile(r"\bfollow.?up\b.{0,30}\b(?:on\s+this|on\s+(?:the\s+)?(?:thread|email|message|it)|if\s+no\s+reply|reminder)\b", re.I), "gmail_followup_reminder"),
    (re.compile(r"\bif\s+no\s+reply\b", re.I), "gmail_followup_reminder"),
    (re.compile(r"\bif\s+they\s+(?:don.t|haven.t)\b.{0,20}\b(?:answer(?:ed)?|repl(?:y|ied)|respond(?:ed)?)\b", re.I), "gmail_followup_reminder"),

    # ── Gmail Phase 10: scheduled send — MUST precede gmail_send_draft ────────────────────
    # gmail_cancel_scheduled_send FIRST — "cancel scheduled X" must not bleed into list patterns
    (re.compile(r"\bcancel\b.{0,30}\bscheduled\b.{0,20}\b(?:send|email|message|draft)?\b", re.I), "gmail_cancel_scheduled_send"),
    (re.compile(r"\bcancel\b.{0,20}\bthe\s+scheduled\b", re.I), "gmail_cancel_scheduled_send"),
    (re.compile(r"\b(?:don.t\s+send|stop\s+sending|unschedule)\b.{0,30}\b(?:that|it|the\s+(?:email|draft|message))\b", re.I), "gmail_cancel_scheduled_send"),
    # gmail_list_scheduled
    (re.compile(r"\b(?:show|list|view|what|any)\b.{0,20}\b(?:my\s+)?scheduled\b.{0,20}\b(?:emails?|sends?|messages?|drafts?)\b", re.I), "gmail_list_scheduled"),
    (re.compile(r"\bscheduled\s+(?:emails?|sends?|messages?|drafts?)\b", re.I), "gmail_list_scheduled"),
    (re.compile(r"\bwhat.{0,20}\b(?:is|are|'s)\b.{0,15}\bscheduled\b", re.I), "gmail_list_scheduled"),
    (re.compile(r"\bwhat.s\s+scheduled\b", re.I), "gmail_list_scheduled"),
    # gmail_schedule_send: requires temporal indicator: tomorrow/weekday/at-time/delay/later
    # FIX-STRESS-001: removed bare \bschedule\b to stop FP on "on schedule" in non-email context
    # FIX-SCHED-001: "schedule for [weekday]" — anchored to start so "on schedule for Monday" doesn't FP
    (re.compile(r"^schedule\s+for\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I), "gmail_schedule_send"),
    (re.compile(r"\b(?:schedule|delay\s+send|send\s+later)\b.{0,40}\b(?:draft|email|message|this|it)\b", re.I), "gmail_schedule_send"),
    (re.compile(r"\b(?:delay\s+send|send\s+later)\b", re.I), "gmail_schedule_send"),
    (re.compile(r"\bsend\b.{0,30}\b(?:tomorrow|tonight|morning|afternoon|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next\s+week|in\s+\d+\s+(?:hours?|minutes?))\b", re.I), "gmail_schedule_send"),
    (re.compile(r"\bsend\b.{0,20}\b(?:this|it|the\s+(?:draft|email|message))\b.{0,30}\b(?:tomorrow|tonight|morning|afternoon|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I), "gmail_schedule_send"),
    (re.compile(r"\bsend\b.{0,30}at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.I), "gmail_schedule_send"),
    (re.compile(r"\bschedule\b.{0,30}\b(?:this|it|the\s+(?:draft|email|message))\b", re.I), "gmail_schedule_send"),

    # ── Gmail Phase 16: filter / rule builder — MUST precede Phase 3 ─────────
    # gmail_filter_cancel — "cancel rule creation", "discard the filter"
    (re.compile(r"\b(?:cancel|discard|abort|stop)\b.{0,20}\b(?:rule|filter)\b", re.I), "gmail_filter_cancel"),
    # gmail_filter_apply — "create that rule", "apply the filter", "save the rule" — before filter_build
    (re.compile(r"\bcreate\b.{0,15}\b(?:that|the)\b.{0,10}\b(?:rule|filter)\b", re.I), "gmail_filter_apply"),
    (re.compile(r"\b(?:apply|confirm|save)\b.{0,20}\b(?:the|that)\b.{0,15}\b(?:rule|filter)\b", re.I), "gmail_filter_apply"),
    (re.compile(r"\byes,?\s+create\b.{0,20}\b(?:rule|filter)\b", re.I), "gmail_filter_apply"),
    # gmail_filter_list — "show my rules", "list my Gmail filters"
    (re.compile(r"\b(?:show|list|view)\b.{0,20}\b(?:my\s+)?(?:rules|filters)\b", re.I), "gmail_filter_list"),
    (re.compile(r"\b(?:show|list)\b.{0,15}\bsaved\b.{0,15}\b(?:rules|filters)\b", re.I), "gmail_filter_list"),
    # gmail_filter_build — "always label X", "create a rule for X", "auto archive X", "make a filter"
    (re.compile(r"\b(?:always|auto|automatically)\b.{0,30}\b(?:label|archive|star)\b", re.I), "gmail_filter_build"),
    (re.compile(r"\b(?:always|auto|automatically)\b.{0,40}\bmark\b.{0,30}\bread\b", re.I), "gmail_filter_build"),
    (re.compile(r"\bcreate\b.{0,20}\b(?:a\s+)?(?:rule|filter)\b.{0,25}\b(?:for|to|that|when)\b", re.I), "gmail_filter_build"),
    (re.compile(r"\b(?:make|build|set\s+up)\b.{0,20}\b(?:a\s+)?(?:rule|filter)\b", re.I), "gmail_filter_build"),
    (re.compile(r"\b(?:create|make)\b.{0,10}\b(?:a\s+)?gmail\s+(?:rule|filter)\b", re.I), "gmail_filter_build"),
    (re.compile(r"\b(?:show\s+me|what\s+rule|what\s+filter)\b.{0,30}\b(?:for|would|you\s+make)\b", re.I), "gmail_filter_build"),

    # ── Gmail Phase 15: thread intel + forward — MUST precede Phase 3 (gmail_draft_reply / gmail_compose) ──
    # gmail_thread_intel — action items, decisions, questions, reply-needed, latest-delta
    (re.compile(r"\baction\s+items?\b", re.I), "gmail_thread_intel"),
    (re.compile(r"\bwhat\s+(?:action\s+items?|decisions?|questions?|changed|do\s+I\s+(?:owe|need\s+to\s+do))\b", re.I), "gmail_thread_intel"),
    (re.compile(r"\b(?:do\s+I\s+owe|should\s+I\s+reply|is\s+a\s+reply\s+needed|reply\s+needed|need\s+to\s+respond)\b", re.I), "gmail_thread_intel"),
    (re.compile(r"\b(?:what\s+changed|latest\s+(?:reply|message|update|delta)|last\s+(?:reply|message|update))\b", re.I), "gmail_thread_intel"),
    (re.compile(r"\bdecisions?\b.{0,20}\b(?:in|from|this|the)\b.{0,20}\b(?:thread|conversation|email|chain)\b", re.I), "gmail_thread_intel"),
    (re.compile(r"\bquestions?\s+(?:waiting|outstanding|for\s+me|pending)\b", re.I), "gmail_thread_intel"),
    (re.compile(r"\bsummarize\b.{0,20}\blatest\b.{0,20}\b(?:reply|message|part|update)\b", re.I), "gmail_thread_intel"),
    # gmail_forward — "forward to X", "fwd this to Y" — MUST precede gmail_compose
    (re.compile(r"\b(?:forward|fwd)\b.{0,25}\bto\b", re.I), "gmail_forward"),
    (re.compile(r"\b(?:forward|fwd)\b.{0,20}\b(?:this|it|the\s+(?:email|thread|message))\b", re.I), "gmail_forward"),

    # ── Gmail Phase 3: draft / send intents — MUST precede Phase 2 mutation patterns ──────
    # gmail_send_draft — anchored bare forms; also "send the draft" (requires "draft" word)
    (re.compile(r"^send\s+(?:it|the\s+draft|that|this)\s*$", re.I), "gmail_send_draft"),
    # FIX-STRESS-003: allow "go ahead and send" without requiring "it/now/draft" suffix
    (re.compile(r"^(?:go\s+ahead\s+and\s+)?send(?:\s+it|\s+the\s+draft|\s+now)?\s*$", re.I), "gmail_send_draft"),
    (re.compile(r"\bsend\b.{0,20}\b(?:the\s+)?draft\b", re.I), "gmail_send_draft"),
    (re.compile(r"\bsend\b.{0,15}\b(?:the\s+)?(?:reply|response)\b", re.I), "gmail_send_draft"),
    # FIX-STAGE3-003: "send an email to X" is compose; only "send the email/message" is send_draft
    (re.compile(r"\bsend\b.{0,20}\bthe\s+(?:email|mail|message)\b", re.I), "gmail_send_draft"),
    (re.compile(r"\b(?:looks?\s+good|lgtm|approved?|good\s+to\s+go)\b.{0,25}\bsend\b", re.I), "gmail_send_draft"),
    # gmail_cancel_draft — requires "draft" qualifier (more specific than bare gmail_cancel)
    (re.compile(r"\b(?:cancel|discard|delete|clear|abort)\b.{0,20}\b(?:the\s+)?draft\b", re.I), "gmail_cancel_draft"),
    (re.compile(r"\b(?:forget|throw\s+away)\b.{0,20}\b(?:the\s+)?draft\b", re.I), "gmail_cancel_draft"),
    # FIX-STRESS-004: "throw away the draft" / "don't want the draft"
    (re.compile(r"\bdon.t\s+want\b.{0,20}\b(?:the\s+)?draft\b", re.I), "gmail_cancel_draft"),
    # gmail_show_draft
    (re.compile(r"\b(?:show|display|view|preview|read)\b.{0,20}\b(?:the\s+|my\s+)?draft\b", re.I), "gmail_show_draft"),
    (re.compile(r"\bwhat(?:\s+does)?.{0,20}(?:the\s+)?draft\b", re.I), "gmail_show_draft"),
    # gmail_draft_reply — "draft a reply", "reply saying X", "write back saying X"
    # FIX-STRESS-002: extended to cover "draft a response", "write a reply", "reply to the latest"
    (re.compile(r"\bdraft\b.{0,20}\b(?:a\s+)?(?:reply|response)\b", re.I), "gmail_draft_reply"),
    (re.compile(r"\b(?:write|compose)\b.{0,15}\ba?\s*(?:reply|response)\b", re.I), "gmail_draft_reply"),
    (re.compile(r"\breply\b.{0,30}\b(?:saying|that|with|to\s+(?:it|this|that|the\s+email|the\s+thread|the\s+latest))\b", re.I), "gmail_draft_reply"),
    (re.compile(r"\b(?:respond|write\s+back)\b.{0,30}\b(?:saying|that|to\s+(?:it|this|that))\b", re.I), "gmail_draft_reply"),
    (re.compile(r"\breply\b.{0,30}\bto\s+(?:the\s+)?(?:latest|last|current)\b", re.I), "gmail_draft_reply"),
    # gmail_compose — "compose an email to X", "email X saying Y", "write an email to X", "send an email to X"
    (re.compile(r"\b(?:compose|write)\b.{0,20}\b(?:an?\s+)?(?:new\s+)?(?:email|mail|message)\b", re.I), "gmail_compose"),
    (re.compile(r"\bemail\b.{0,40}\b(?:saying|to\s+say|to\s+tell|that)\b", re.I), "gmail_compose"),
    # FIX-STAGE3-003b: "send an email to X" is compose (send_draft requires "the" after FIX-STAGE3-003)
    (re.compile(r"\bsend\b.{0,15}\ban?\s+(?:email|mail|message)\b", re.I), "gmail_compose"),

    # ── Gmail Phase 2: mutation intents — MUST precede gmail_open / gmail_list_category ──
    # gmail_confirm — anchored bare inputs; dispatch checks _GMAIL_CTX["pending"] before acting
    (re.compile(r"^confirm\s*$", re.I), "gmail_confirm"),
    (re.compile(r"^yes,?\s+do\s+it\s*$", re.I), "gmail_confirm"),
    # gmail_undo — MUST precede gmail_cancel (both short/anchored; undo is more specific)
    (re.compile(r"^undo\s*$", re.I), "gmail_undo"),
    (re.compile(r"^undo\s+that\s*$", re.I), "gmail_undo"),
    (re.compile(r"\bundo\b.{0,30}\b(?:archive|trash|that\s+archive|that\s+trash|mark|last\s+action|that\s+action)\b", re.I), "gmail_undo"),
    (re.compile(r"\b(?:bring\s+back|restore)\b.{0,25}\b(?:those|them|those\s+emails?|that\s+email)\b", re.I), "gmail_undo"),
    # gmail_cancel — anchored
    (re.compile(r"^cancel(?:\s+that)?\s*$", re.I), "gmail_cancel"),
    (re.compile(r"^(?:never\s+mind|abort|stop\s+that)\s*$", re.I), "gmail_cancel"),
    # gmail_mark_read — before mark_unread: "those unread emails as read" must route here
    (re.compile(r"\bmark\b.{0,35}\b(?:as\s+)?read\b", re.I), "gmail_mark_read"),
    # gmail_mark_unread
    # FIX-STRESS-007: added "flag" as synonym for "mark" in unread context
    (re.compile(r"\b(?:mark|flag)\b.{0,35}\b(?:as\s+)?unread\b", re.I), "gmail_mark_unread"),
    # gmail_archive — MUST precede gmail_list_category (both share category/spam words)
    (re.compile(r"\b(?:archive|move\s+to\s+archive)\b.{0,40}\b(?:emails?|mail|messages?|them|those|these|that|it|all|promos?|promotional|promotions?|newsletters?|social|updates?|forums?|spam)\b", re.I), "gmail_archive"),
    (re.compile(r"\barchive\b.{0,20}\b(?:from|about|older\s+than)\b", re.I), "gmail_archive"),
    # FIX-STRESS-006: "move [X] to archive/trash" with noun between move and destination
    (re.compile(r"\bmove\b.{0,30}\bto\s+archive\b", re.I), "gmail_archive"),
    # gmail_trash — MUST precede gmail_list_category
    (re.compile(r"\b(?:trash|move\s+to\s+trash)\b.{0,40}\b(?:emails?|mail|messages?|them|those|these|that|it|all|promos?|promotional|promotions?|newsletters?|social|updates?|forums?|spam)\b", re.I), "gmail_trash"),
    (re.compile(r"\btrash\b.{0,20}\b(?:from|about|older\s+than)\b", re.I), "gmail_trash"),
    (re.compile(r"\bdelete\b.{0,30}\b(?:emails?|mail|messages?|them|those|these|that|promos?|spam)\b", re.I), "gmail_trash"),
    (re.compile(r"\bmove\b.{0,30}\bto\s+trash\b", re.I), "gmail_trash"),

    # ── Gmail Phase 9: triage — MUST precede gmail_open (triage beats bare "open") ──
    (re.compile(r"\b(?:what|which)\b.{0,20}\b(?:needs?|need\s+my)\b.{0,20}\breply\b", re.I), "gmail_triage"),
    (re.compile(r"\bwhat\s+(?:should|do)\s+I\s+(?:answer|respond|reply)\b", re.I), "gmail_triage"),
    # FIX-STRESS-008: extended to include "need action" not just "need attention"
    (re.compile(r"\b(?:which|what)\b.{0,15}\bemails?\b.{0,20}\b(?:urg(?:ent|ently)|important|need\s+(?:attention|action))\b", re.I), "gmail_triage"),
    (re.compile(r"\btriage\b.{0,20}\b(?:my\s+)?(?:inbox|email|mail)\b", re.I), "gmail_triage"),
    (re.compile(r"\b(?:inbox\s+triage|email\s+triage)\b", re.I), "gmail_triage"),
    (re.compile(r"\bwhat\b.{0,20}\b(?:needs?\s+(?:my\s+)?attention|action[-\s]?(?:needed|required|items?))\b", re.I), "gmail_triage"),
    (re.compile(r"\b(?:show|find)\b.{0,15}\b(?:action[-\s]?needed|urgent|important)\b.{0,15}\bemails?\b", re.I), "gmail_triage"),
    (re.compile(r"\b(?:which|what)\b.{0,20}\bthreads?\b.{0,20}\b(?:waiting|pending|unresponded|owe|reply)\b", re.I), "gmail_triage"),
    (re.compile(r"\bwhat\b.{0,20}\b(?:from\s+today|today\b).{0,20}\b(?:needs?|attention|important|matters?)\b", re.I), "gmail_triage"),
    (re.compile(r"\b(?:emails?|inbox).{0,20}\b(?:waiting\s+on\s+me|waiting\s+for\s+me)\b", re.I), "gmail_triage"),

    # ── Gmail open (search + open first result) — MUST precede gmail_read ────────
    # "open latest email from Amazon", "open the email about the budget"
    (re.compile(r"\b(open|read)\b.{0,20}\b(email|mail|message)\b.{0,30}\b(from|about|regarding|by)\b", re.I), "gmail_open"),
    (re.compile(r"\b(open|read)\b.{0,15}\b(latest|newest|recent|last)\b.{0,25}\b(email|mail|message)\b.{0,30}\b(from|about)\b", re.I), "gmail_open"),
    (re.compile(r"\b(find\s+and\s+open|search\s+and\s+open)\b.{0,30}\b(email|mail|message)\b", re.I), "gmail_open"),

    # ── Gmail summarize-thread shortcut — MUST precede gmail_thread ──────────────
    # "summarize the thread about X" / "tldr the conversation"
    (re.compile(r"\b(summarize|tldr)\b.{0,20}\b(thread|conversation)\b", re.I), "gmail_summarize"),

    # ── Gmail thread — show full conversation ─────────────────────────────────
    (re.compile(r"\b(show|open|read|get|view)\b.{0,20}\b(thread|conversation|email\s+chain|message\s+chain)\b", re.I), "gmail_thread"),
    (re.compile(r"\bthread\b.{0,20}\b(about|from|with|on)\b", re.I), "gmail_thread"),

    # FIX-SPRINT-007: "search web for X and summarize it" → web_search, not gmail_summarize
    # MUST precede the "summarize it" gmail_summarize pattern below
    (re.compile(r"\b(?:search|look\s+up|find)\b.{0,20}\b(?:web|internet|online|for)\b.{0,60}\b(?:summarize|tldr|summary)\b", re.I), "web_search"),
    # ── Gmail summarize — MUST precede gmail_read (avoids "summarize" → gmail_read) ──
    # "summarize this email", "summarize the thread about X", "tldr"
    (re.compile(r"^(?:tldr|tl;dr|tl\.dr)\s*$", re.I), "gmail_summarize"),
    (re.compile(r"\b(summarize|tldr|tl;dr|tl\.dr|give\s+me\s+a\s+summary)\b.{0,30}\b(this|that|the|an?)?\b.{0,10}\b(email|mail|message|thread|conversation)\b", re.I), "gmail_summarize"),
    (re.compile(r"\b(summarize|tldr)\s+(that|this|it|the\s+thread)\b", re.I), "gmail_summarize"),

    # ── Gmail list category ────────────────────────────────────────────────────
    (re.compile(r"\b(show|list|check|open|display)\b.{0,20}\b(promotions?|promo|promotional|newsletters?)\b", re.I), "gmail_list_category"),
    (re.compile(r"\b(show|list|check|open|display)\b.{0,20}\bspam\b", re.I), "gmail_list_category"),
    (re.compile(r"\b(show|list|check|open|display)\b.{0,20}\b(social|updates?|forums?)\b.{0,15}\b(emails?|mail|messages?)?\b", re.I), "gmail_list_category"),

    # ── Gmail read (specific email) — MUST precede generic gmail ─────────────────
    # "open 5", "read 3", "open #2" → bare number follow-up to inbox listing
    (re.compile(r"^(open|read)\s+#?(\d{1,2})\s*$", re.I), "gmail_read"),
    # "read/open the latest/newest/first email"
    (re.compile(r"\b(read|open|show)\b.{0,20}\b(latest|newest|first|top|most\s+recent)\b.{0,20}\b(email|mail|message)\b", re.I), "gmail_read"),
    # "open email 5", "read message 3", "open email number 2"
    (re.compile(r"\b(read|open|show)\b.{0,15}\b(email|mail|message)\b.{0,15}\b#?(\d{1,2})\b", re.I), "gmail_read"),
    # "open this email", "read this email [subject]"
    (re.compile(r"\b(read|open)\s+this\s+(email|mail|message)\b", re.I), "gmail_read"),

    # ── Gmail ────────────────────────────────────────────────────────────────────
    # FIX-GMAIL-002: typos (gmial, emil), "messages" synonym, "inbox check" word-order
    # FIX-STRESS-009: extended inbox listing variants ("list messages", "how many unread", etc.)
    (re.compile(r"\b(do\s+i\s+have\s+any|any\s+(new|unread)?\s*)(emails?|messages?|mail)\b", re.I), "gmail"),
    (re.compile(r"\binbox\b.{0,15}\b(check|status|new|unread|count|messages?)\b", re.I), "gmail"),
    (re.compile(r"\bwhat.{0,10}in\s+(?:my\s+)?inbox\b", re.I), "gmail"),
    (re.compile(r"\b(gm[i]?al|emial)\b", re.I), "gmail"),
    (re.compile(r"(check|show|read|open|get|fetch|look\s+at|list).{0,20}(my )?(email|gmail|inbox|mail|messages?|emial|emil)\b", re.I), "gmail"),
    (re.compile(r"\bhow\s+many\b.{0,20}\b(?:unread|emails?|messages?)\b", re.I), "gmail"),
    (re.compile(r"\bshow\b.{0,15}\bme\b.{0,10}\bunread\b", re.I), "gmail"),
    (re.compile(r"(any (new|unread) )?emails?\b", re.I), "gmail"),
    (re.compile(r"gmail\b", re.I), "gmail"),

    # ── Memory ledger ────────────────────────────────────────────────────────────
    (re.compile(r"(scan|index|update|build).{0,20}(my )?(memory|memories|ledger|context)", re.I), "memory_scan"),
    # FIX-MEMSCAN-002: refresh/rebuild/rescan and "memory scan X" patterns
    (re.compile(r"\b(refresh|rebuild|rescan|reindex)\b.{0,20}\b(memory|knowledge|index|ledger)\b", re.I), "memory_scan"),
    (re.compile(r"\bindex\b.{0,20}\b(terminal\s+history|history|session|conversation)\b", re.I), "memory_scan"),
    (re.compile(r"\bmemory\s+(scan|update|rescan|refresh|rebuild)\b", re.I), "memory_scan"),
    (re.compile(r"\bscan\s+mem\w*\b", re.I), "memory_scan"),
    (re.compile(r"(what do you (remember|know|recall)|do you remember|tell me what you know).{0,40}(about|regarding)\b", re.I), "memory_recall"),
    (re.compile(r"(remember|recall|what do you know about|memory).{0,30}\?", re.I), "memory_recall"),
    (re.compile(r"memory (stats|status|ledger|database|db)\b", re.I), "memory_stats"),
    # NHR-009: additional synonyms — "memory statistics/metrics/entries"
    (re.compile(r"memory\s+(statistics|metrics|size|count|entries|records)\b", re.I), "memory_stats"),
    # FIX-MEMST-001: "how many X in memory" / "entries in memory"
    (re.compile(r"\bhow\s+many\b.{0,20}\b(things?|entries?|items?|records?)\b.{0,20}\bin\s+(your\s+|adwi.s\s+)?memory\b", re.I), "memory_stats"),
    (re.compile(r"\b(entries?|items?|records?)\s+in\s+(your\s+|my\s+|adwi.s\s+)?memory\b", re.I), "memory_stats"),
    (re.compile(r"\bmemry\s+(stats?|status|count|size)\b", re.I), "memory_stats"),
    # FIX-MEMCTX-001: show/what context → memory_context (NO regex existed before)
    (re.compile(r"\b(show|display|what.{0,10}(is|do\s+you\s+have))\b.{0,20}\b(session\s+)?context\b(?!\s+(window|length|limit|size))", re.I), "memory_context"),
    (re.compile(r"\bcontext\b.{0,20}\b(summary|dump|snapshot|right\s+now|currently)\b", re.I), "memory_context"),

    # ── Semantic router ──────────────────────────────────────────────────────────
    (re.compile(r"route (this|the|my)?\s*(query|question|request|command)\b", re.I), "route"),
    (re.compile(r"which tool (should|would|to) (handle|use for|run)\b", re.I), "route"),

    # FIX-SPRINT-002: "generate/suggest ideas for adwi features" / "low-hanging fruit" → what_next
    # MUST precede capabilities \badwi\b...features pattern
    (re.compile(r"\b(?:generate|suggest|brainstorm|come\s+up\s+with)\b.{0,20}\bideas?\b.{0,30}\b(?:adwi|features?|improvements?|enhancements?)\b", re.I), "what_next"),
    (re.compile(r"\bbrainstorm\b.{0,30}\b(?:adwi|improvements?|features?|enhancements?)\b", re.I), "what_next"),
    (re.compile(r"\blow[\s-]?hanging\s+fruit\b", re.I), "what_next"),
    # ── Capabilities ─────────────────────────────────────────────────────────────
    # FIX-S3-004: "adwi feature list", typos, colloquial "wut can u do"
    (re.compile(r"\badwi\b.{0,20}\b(feature\s+list|features|commands|abilities|capabilities)\b", re.I), "capabilities"),
    (re.compile(r"\b(cpaabilit|capabilites|capabilty|cabpabilities)\b", re.I), "capabilities"),
    (re.compile(r"\bwut\s+can\s+(u|you)\b.{0,15}(do|help|offer)\b", re.I), "capabilities"),

    # ── Sync knowledge base ──────────────────────────────────────────────────────
    # FIX-S3-006: "sync/update knowledge to Open WebUI", "push notes to webui"
    (re.compile(r"\b(sync|update|push)\b.{0,20}\b(knowledge|notes?)\b.{0,20}\b(open.?webui|openwebui|webui)\b", re.I), "sync"),
    (re.compile(r"\bopen.?webui\b.{0,20}\b(sync|update|push|add|knowledge)\b", re.I), "sync"),
    (re.compile(r"\bsync\b.{0,15}\b(knowledge\s+base|knowledge)\b", re.I), "sync"),
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

_IMG_PATH_RE = re.compile(
    r"(?:^|[\s:'\"(])([~/][\w./-]+\.(?:png|jpg|jpeg|gif|bmp|webp|heic|avif|tiff?))\b",
    re.I,
)

def extract_image_path(text):
    """Detect an image file path in text — works for bare paths and embedded paths."""
    # Fast path: entire text is a path
    t = text.strip().strip("'\"")
    p = Path(t).expanduser()
    if p.suffix.lower() in IMAGE_EXTS and (p.exists() or p.is_absolute()):
        return str(p)
    # Scan for embedded path in natural-language sentence
    m = _IMG_PATH_RE.search(text)
    if m:
        candidate = m.group(1)
        cp = Path(candidate).expanduser()
        if cp.suffix.lower() in IMAGE_EXTS and (cp.exists() or cp.is_absolute() or candidate.startswith("~")):
            return str(cp)
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

def _ollama_chat(model, messages, stream=False, max_tokens=None, temperature=0.25, ctx=131072, json_schema=None):
    opts = {"temperature": temperature, "num_ctx": ctx}
    if max_tokens: opts["num_predict"] = max_tokens
    payload = {"model": model, "messages": messages, "stream": stream, "think": False, "options": opts}
    if json_schema:
        payload["format"] = json_schema  # Ollama native structured output
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

# ── Intent classification (llama3.1:8b + Ollama JSON schema enforcement) ───────

# All valid intent tokens — Ollama constrained decoding guarantees one of these
_ALL_INTENTS = [
    # File system
    "disk_usage", "large_files", "old_files", "duplicates",
    "organize", "cleanup", "file_read", "file_search", "file_list",
    # Media
    "youtube", "image", "generate_image",
    # System
    "status", "self_heal", "what_next", "daily_improve", "benchmark",
    "run_code", "doctor",
    # Model / routing
    "model_status", "use_local", "use_cloud", "capabilities",
    # Knowledge & memory
    "rag_search", "memory_recall", "memory_scan", "memory_stats",
    "memory_context",
    # Web
    "browse", "web_search", "exa_search", "tavily_search", "firecrawl",
    # Obsidian vault
    "obsidian_search", "obsidian_read", "obsidian_write", "obsidian_daily",
    # Git & backup
    "git_status", "backup_now", "backup_status", "backup_log",
    # Comms — Gmail
    "gmail", "gmail_read", "gmail_open", "gmail_thread", "gmail_summarize", "gmail_list_category",
    "gmail_archive", "gmail_trash", "gmail_mark_read", "gmail_mark_unread",
    "gmail_confirm", "gmail_cancel", "gmail_undo",
    "gmail_draft_reply", "gmail_compose", "gmail_show_draft",
    "gmail_send_draft", "gmail_cancel_draft", "gmail_rewrite_draft", "gmail_update_subject",
    "gmail_add_cc", "gmail_add_bcc",
    "gmail_list_attachments", "gmail_save_attachment", "gmail_summarize_attachment",
    "gmail_attach_file", "gmail_remove_attachment",
    "gmail_triage",
    "gmail_schedule_send", "gmail_list_scheduled", "gmail_cancel_scheduled_send",
    "gmail_followup_reminder", "gmail_list_followups", "gmail_cancel_followup",
    "gmail_reschedule_send", "gmail_open_scheduled_draft",
    "gmail_list_drafts", "gmail_open_draft", "gmail_delete_draft",
    "gmail_thread_intel", "gmail_forward",
    "gmail_filter_build", "gmail_filter_apply", "gmail_filter_cancel", "gmail_filter_list",
    "gmail_extract_tasks", "gmail_tasks_save", "gmail_tasks_remind",
    # n8n / automation
    "sync",
    # Nightly
    "nightly_status", "nightly_run",
    # Repair & eval
    "fix_error", "patch_adwi", "inspect_code", "test_adwi", "eval_routing", "eval_adwi",
    "learn_from_error", "export_training",
    # Route / misc
    "route", "github_connected", "trusted_roots",
    "extract_ideas", "implement_idea", "tool_roadmap",
    # Voice (Pillar C)
    "voice_in", "voice_out",
    # Catch-all
    "chat",
]

# ── Phase 6: Chain-of-Intent Schema & Semantic Slot-Filling ──────────────────
# Ollama-native JSON Schema — forces the model to reason in `analysis` before
# committing to an intent, then extract structured argument slots instead of
# leaving callers to do fragile inline regex.
_INTENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {
            "type": "string",
            "description": (
                "A dense, one-sentence breakdown parsing verbs, core entities, "
                "and the user's implicit operational goal. Reason here first."
            ),
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "intent":     {"type": "string", "enum": _ALL_INTENTS},
        "arguments":  {
            "type": "object",
            "description": (
                "Extracted key-value parameter slots needed by the target tool. "
                "Typed keys: path (file/dir path), query (search string), url (URL), "
                "size_mb (integer MB threshold), days (integer age in days), "
                "description (image prompt), target (generic fallback). "
                "Omit keys that do not apply. Empty object {} is valid."
            ),
        },
    },
    "required": ["analysis", "confidence", "intent", "arguments"],
}

_INTENT_SYSTEM = (
    "You are Adwi's intent classifier. Produce a JSON object with exactly 4 fields:\n"
    "\n"
    "1. analysis   — One dense sentence: parse the verbs, core entities, and the\n"
    "                user's implicit operational goal. Reason here BEFORE choosing intent.\n"
    "2. confidence — Float 0.0–1.0. Certainty of intent mapping.\n"
    "3. intent     — ONE string from the allowed enum. Classification rules:\n"
    "   'memory_recall'  : user asks what YOU (adwi) remember or know about their personal setup.\n"
    "                      NOT for searching personal notes/Obsidian/vault — those are\n"
    "                      'obsidian_search' or 'rag_search'. Only Adwi's own learned memory.\n"
    "   'disk_usage'     : storage/disk space questions ONLY (not RAM/CPU)\n"
    "   'large_files'    : find files exceeding a size threshold\n"
    "   'old_files'      : find files older than a time period\n"
    "   'gmail'          : general email questions, list inbox, check unread, search messages\n"
    "   'gmail_read'     : read a specific email by position number, 'latest', or 'this email'\n"
    "   'gmail_open'     : search for email(s) and open the best match — requires from/about qualifier\n"
    "                      e.g. 'open latest email from Amazon', 'open email about the budget'\n"
    "   'gmail_thread'   : show/view a full email thread or conversation\n"
    "   'gmail_summarize': LLM-summarize the current email, thread, or a searched email\n"
    "                      e.g. 'summarize that', 'summarize the thread about budget'\n"
    "   'gmail_list_category': list emails in a Gmail category — promotions, spam, social, updates\n"
    "   'gmail_archive'  : preview + queue archive for emails (removes from inbox); say 'confirm' to apply\n"
    "                      e.g. 'archive those promotions', 'archive emails from Amazon'\n"
    "   'gmail_trash'    : preview + queue move-to-trash; say 'confirm' to apply\n"
    "                      e.g. 'trash spam older than a week', 'delete those social emails'\n"
    "   'gmail_mark_read': preview + queue mark-as-read; say 'confirm' to apply\n"
    "                      e.g. 'mark these as read', 'mark all promos read'\n"
    "   'gmail_mark_unread': preview + queue mark-as-unread; say 'confirm' to apply\n"
    "   'gmail_confirm'  : ONLY if there is a pending Gmail mutation action to execute\n"
    "                      bare 'confirm', 'yes do it' — confirms archive/trash/mark-read\n"
    "   'gmail_cancel'   : cancel a pending Gmail mutation — 'cancel', 'never mind'\n"
    "   'gmail_undo'     : undo the last confirmed Gmail mutation (archive/trash/mark-read/mark-unread)\n"
    "                      'undo', 'undo that', 'undo the archive', 'bring back those emails'\n"
    "                      Only valid after a mutation has been confirmed this session.\n"
    "   'gmail_draft_reply': draft a reply to the current email — 'reply saying X', 'draft a reply'\n"
    "                      ALWAYS draft-first, never auto-send. Requires 'send it' to send.\n"
    "   'gmail_compose'  : compose a new email draft — 'email X saying Y', 'compose an email to X'\n"
    "                      ALWAYS draft-first, never auto-send.\n"
    "   'gmail_show_draft': show the current pending draft — 'show the draft', 'what does the draft say'\n"
    "   'gmail_send_draft': send the current draft after user review — 'send it', 'send the draft'\n"
    "                      Only valid when a draft is pending. Requires explicit confirmation.\n"
    "   'gmail_cancel_draft': cancel/delete the current draft — 'cancel the draft', 'discard the draft'\n"
    "   'gmail_rewrite_draft': rewrite/update the current draft body — 'make it shorter',\n"
    "                      'rewrite it professionally', 'make it warmer', 'make it more direct',\n"
    "                      'make it less robotic', 'make it more natural', 'turn this into a concise update',\n"
    "                      'write a shorter version', 'mention that I can do Friday'.\n"
    "                      Always requires a current draft. Shows updated preview after rewrite.\n"
    "                      NEVER use for subject-only changes (→ gmail_update_subject).\n"
    "   'gmail_update_subject': update/rewrite the subject line of the current draft — 'make the subject clearer',\n"
    "                      'rewrite the subject', 'give me a better subject', 'change the subject',\n"
    "                      'the subject sounds weak', 'write a stronger subject line'.\n"
    "                      NEVER for body rewrites (→ gmail_rewrite_draft). Always requires a current draft.\n"
    "   'gmail_add_cc'    : add a CC recipient to the current draft — 'add cc Priya',\n"
    "                      'cc Priya to the draft', 'also cc my manager'\n"
    "                      Always requires an active draft.\n"
    "   'gmail_add_bcc'   : add a BCC recipient to the current draft — 'add bcc me',\n"
    "                      'bcc Rahul on this draft', 'also bcc myself'\n"
    "                      Always requires an active draft.\n"
    "   'gmail_list_attachments': list attached files on the current email — 'show attachments',\n"
    "                      'what files are attached', 'any attachments on that email'\n"
    "   'gmail_save_attachment': save a specific attachment to the workspace — 'save the PDF',\n"
    "                      'download the invoice', 'save the first attachment', 'open the PDF'\n"
    "   'gmail_summarize_attachment': save and LLM-summarize an attachment — 'summarize the PDF',\n"
    "                      'what's in the attached document', 'tldr the invoice'\n"
    "   'gmail_attach_file': attach a local file to the current outbound draft — 'attach the PDF',\n"
    "                      'add the invoice to this draft', 'attach that saved attachment',\n"
    "                      'include the report in the email'. Always requires an active draft.\n"
    "                      NEVER use for incoming/inbound email attachments — use gmail_list_attachments\n"
    "                      or gmail_save_attachment for reading/saving received files.\n"
    "   'gmail_remove_attachment': remove an outbound attachment from the current draft —\n"
    "                      'remove the PDF from the draft', 'detach the attachment', 'drop the invoice',\n"
    "                      'remove attachment 1'. Only valid when a draft with attachments exists.\n"
    "   'gmail_triage'   : analyze and rank the inbox — 'what needs my reply?', 'which emails are urgent?',\n"
    "                      'triage my inbox', 'what needs attention today?', 'show action-needed emails',\n"
    "                      'what should I answer?', 'which threads am I waiting on?', 'inbox triage',\n"
    "                      'emails waiting on me'. ALWAYS read-only — no mutations.\n"
    "                      Populates candidates for follow-up open/reply/archive after triage.\n"
    "                      NEVER use gmail_archive/gmail_trash for triage requests.\n"
    "   'gmail_schedule_send': schedule the current draft for future delivery — REQUIRES explicit time phrase.\n"
    "                      'send this tomorrow morning', 'schedule for Monday at 9', 'send at 3 PM',\n"
    "                      'delay send until Friday', 'schedule it for next week', 'send in 2 hours'.\n"
    "                      NEVER use when user wants immediate send (no time phrase) → use gmail_send_draft.\n"
    "                      NEVER schedule without a draft in context.\n"
    "   'gmail_list_scheduled': show pending Adwi-scheduled sends — 'show scheduled emails',\n"
    "                      'what emails are scheduled', 'list scheduled sends', 'any scheduled messages'.\n"
    "   'gmail_reschedule_send': move a pending scheduled send to a new time — 'reschedule to tomorrow morning',\n"
    "                      'reschedule the Rahul send to Friday at 9', 'move the scheduled email to Monday',\n"
    "                      'change the scheduled send time to next week', 'postpone to Friday', 'push to in 2 hours'.\n"
    "                      ALWAYS requires a time phrase. NEVER for new schedules (→ gmail_schedule_send).\n"
    "   'gmail_open_scheduled_draft': load the draft underlying a scheduled send — 'open the scheduled invoice draft',\n"
    "                      'reopen the scheduled Rahul email', 'switch to the scheduled draft'.\n"
    "                      NEVER use for listing (→ gmail_list_scheduled) or time changes (→ gmail_reschedule_send).\n"
    "   'gmail_cancel_scheduled_send': cancel a pending scheduled send — 'cancel the scheduled send',\n"
    "                      'cancel scheduled 1', 'unschedule that', 'don't send that', 'stop the scheduled email'.\n"
    "                      NEVER use for canceling an immediate send (use gmail_cancel for pending mutations).\n"
    "   'gmail_followup_reminder': set a follow-up reminder on the last sent email or current thread.\n"
    "                      'remind me if no reply in 3 days', 'follow up on this Friday if they don't answer',\n"
    "                      'set a follow-up reminder', 'if they haven't replied by Monday ping me',\n"
    "                      'remind me to follow up'. NEVER auto-sends anything — reminder only.\n"
    "                      NEVER use when user asks to see reminders (→ gmail_list_followups).\n"
    "   'gmail_list_followups': list all pending follow-up reminders with live reply-detection.\n"
    "                      'show my follow-ups', 'what am I waiting on?', 'who hasn't replied?',\n"
    "                      'pending follow-ups', 'open follow-ups', 'list my reminders'.\n"
    "   'gmail_cancel_followup': cancel an existing follow-up reminder.\n"
    "                      'cancel the follow-up', 'cancel reminder 2', 'remove that reminder',\n"
    "                      'stop the follow-up reminder', 'delete reminder'. NEVER for scheduled sends.\n"
    "   'gmail_list_drafts': list all Gmail drafts — 'show my drafts', 'list drafts',\n"
    "                      'show scheduled drafts', 'show unsent drafts', 'which draft has a PDF?'.\n"
    "                      ONLY use for PLURAL 'drafts' or explicit list context.\n"
    "                      NEVER use when user wants to see the current single draft (→ gmail_show_draft).\n"
    "   'gmail_open_draft': switch active draft by ordinal or name — 'open draft 2', 'open the second draft',\n"
    "                      'go back to the invoice draft', 'switch to the Rahul draft',\n"
    "                      'send the second draft' (selects AND sends).\n"
    "                      NEVER use for 'send the draft' (→ gmail_send_draft).\n"
    "   'gmail_delete_draft': delete a specific draft by ordinal or name — 'delete draft 2',\n"
    "                      'delete the Rahul draft', 'cancel the old draft', 'remove draft 1'.\n"
    "                      NEVER use for 'delete the draft' (plain → gmail_cancel_draft).\n"
    "   'gmail_thread_intel': structured thread analysis — 'what action items are in this thread?',\n"
    "                      'do I owe a reply here?', 'what changed in the last reply?',\n"
    "                      'what decisions were made?', 'questions waiting on me?',\n"
    "                      'summarize the latest part', 'should I reply?'. Requires thread context.\n"
    "   'gmail_forward'  : forward current email to a new recipient — 'forward to Rahul',\n"
    "                      'forward this to priya@example.com', 'forward with a summary',\n"
    "                      'fwd this to the team'. Always creates a draft first.\n"
    "   'gmail_filter_build': parse and preview a reusable Gmail filter rule from natural language —\n"
    "                      'always label invoices Finance', 'archive newsletters from this sender',\n"
    "                      'mark GitHub notifications as read', 'create a rule for Amazon receipts',\n"
    "                      'create a Gmail filter for these promotional emails',\n"
    "                      'show me what rule you would make for these emails'.\n"
    "                      NEVER use when the user just wants a one-time action (→ gmail_archive, gmail_mark_read).\n"
    "                      'always', 'auto', 'create a rule/filter', 'make a filter' are the key signals.\n"
    "   'gmail_filter_apply': confirm and create the pending Gmail filter rule —\n"
    "                      'create that rule', 'apply the filter', 'save the rule', 'yes create it'.\n"
    "                      ONLY use when a pending rule exists (user built one first).\n"
    "   'gmail_filter_cancel': cancel the pending rule — 'cancel rule creation', 'discard the filter'.\n"
    "   'gmail_filter_list': list saved Gmail rules — 'show my rules', 'list my Gmail filters'.\n"
    "   'gmail_extract_tasks': extract action items, deadlines, decisions, or asks from current email/thread —\n"
    "                      'turn this email into a task list', 'extract action items',\n"
    "                      'what deadlines are mentioned here?', 'make a follow-up checklist',\n"
    "                      'summarize this thread as tasks', 'extract decisions'.\n"
    "                      Requires email/thread in context. Stores result for follow-up save/remind.\n"
    "   'gmail_tasks_save' : save extracted tasks/checklist to Obsidian daily note —\n"
    "                      'save those tasks to Obsidian', 'add to my daily note',\n"
    "                      'export the checklist', 'save those action items'.\n"
    "                      ONLY use after gmail_extract_tasks (requires pending_tasks in context).\n"
    "   'gmail_tasks_remind': create follow-up reminders from extracted task deadlines —\n"
    "                      'create reminders for those action items', 'set reminders for the deadlines',\n"
    "                      'remind me about those tasks'.\n"
    "                      Key signal: requires 'those/these/the action items/deadlines' anchor.\n"
    "                      NEVER use for 'remind me about this thread in 3 days' (→ gmail_followup_reminder).\n"
    "   'organize'       : user wants to organize, structure, or tidy their files/folders/workspace.\n"
    "                      EVEN when phrased as a question: 'what's the best way to structure my files?',\n"
    "                      'how should I organize my workspace?', 'how to structure project folders?'.\n"
    "                      Key signals: organize/structure/tidy + files/folders/workspace/projects.\n"
    "                      NOT cleanup (which is deletion-focused). NOT file_search (finding files).\n"
    "   'cleanup'        : user wants to delete, remove, or purge unwanted files/data from their machine.\n"
    "                      Examples: 'purge old downloads', 'what should I delete?', 'remove leftover installers',\n"
    "                      'clean up junk', 'free up space by removing files', 'what's safe to delete?'.\n"
    "                      Key signals: delete/remove/purge/trash + files/data/space.\n"
    "                      NOT organize (sorting/restructuring). NOT old_files (listing old files).\n"
    "   'generate_image' : ONLY when creating a brand-new image/picture/artwork/visual output.\n"
    "                      NEVER for explanations, comparisons, or code/model concepts.\n"
    "                      'generation' as a software concept (code generation, token generation,\n"
    "                      model generation) is NOT this intent.\n"
    "                      NEVER for: 'generate a summary', 'generate a report', 'generate a plan',\n"
    "                      'generate a list', 'generate a todo list', 'generate code', 'generate ideas'\n"
    "                      → those are 'nightly_status', 'what_next', 'run_code', or 'chat'.\n"
    "                      ONLY use when prompt explicitly asks for an image/picture/photo/drawing.\n"
    "   'web_search'     : explicit request for internet/web search\n"
    "   'status'         : asks if services/systems are running or healthy (shallow check)\n"
    "   'doctor'         : deep full-system health check and diagnostic — MORE thorough than 'status'.\n"
    "                      REQUIRES explicit depth keyword: 'run doctor', 'full health check',\n"
    "                      'deep diagnostic', 'thorough check', 'complete health check'.\n"
    "                      'stack health check' or bare 'health check' alone → use 'status'.\n"
    "   'sync'           : sync the adwi knowledge base to Open WebUI — ONLY when user says 'sync'\n"
    "                      or 'update knowledge base'. NOT for general 'manage' or 'update' requests.\n"
    "   'capabilities'   : user EXPLICITLY asks what ADWI/YOU can do — must mention 'you', 'adwi',\n"
    "                      'your features', 'your commands', or 'show help'. Questions about\n"
    "                      alternatives, comparisons, recommendations, or subscriptions are NOT this.\n"
    "   'daily_improve'  : run the daily self-improvement routine. Keywords: 'daily improve',\n"
    "                      'daily improvement', 'daily routine', 'run daily maintenance'.\n"
    "                      NOT 'patch_adwi' (which uses aider for code changes).\n"
    "   'patch_adwi'     : apply code-level changes to adwi source via aider. ONLY when the\n"
    "                      user says 'aider', 'patch adwi', 'apply patches', 'run aider',\n"
    "                      'self-patch', or 'auto-patch'. NOT daily_improve (routine).\n"
    "                      NOT fix_error (which handles pasted exception text).\n"
    "   'what_next'      : user asks for AI-suggested next improvements or features to build.\n"
    "                      'what should I build next', 'suggest adwi improvements',\n"
    "                      'adwi roadmap', 'next feature ideas'. Advisory, not action.\n"
    "                      ALSO: 'how should I improve adwi', 'what code changes would make adwi better',\n"
    "                      'what should I refactor in adwi', 'generate a todo list for adwi' → what_next.\n"
    "                      NOT 'patch_adwi' (aider code changes). NOT 'daily_improve' (runs routine).\n"
    "   'inspect_code'   : read and explain an adwi source file. User says 'inspect', 'review',\n"
    "                      'look at' or 'find bugs in' adwi source code or a specific .py file.\n"
    "                      'code review adwi', 'inspect adwi_cli.py', 'find bugs in adwi'.\n"
    "   'youtube'        : summarise or transcribe a YouTube video. User mentions 'youtube'\n"
    "                      with a URL or with words like 'summarise', 'transcript', 'video'.\n"
    "                      Also for youtu.be or youtube.com links without a verb.\n"
    "   'obsidian_search': search the user's personal Obsidian vault (notes). PREFERRED over\n"
    "                      'memory_recall' when the prompt contains 'vault', 'obsidian',\n"
    "                      'my notes', or 'note search'. This is the USER's personal notes,\n"
    "                      NOT Adwi's internal memory about the user's setup.\n"
    "                      NEVER for advisory questions about Obsidian as an app:\n"
    "                      'what's the best obsidian theme', 'obsidian alternatives',\n"
    "                      'how do I use obsidian callouts' → those are 'chat', not vault searches.\n"
    "   'obsidian_daily' : open or append to today's Obsidian daily note or journal entry.\n"
    "                      'daily note', 'today's note', 'open today's journal'.\n"
    "                      NOT obsidian_search (which searches across all notes).\n"
    "   'fix_error'      : user pastes an EXACT exception string containing an error class\n"
    "                      (ModuleNotFoundError, TypeError, ValueError, AttributeError, KeyError,\n"
    "                      RuntimeError, etc.) OR an HTTP status code (404, 500, 502).\n"
    "                      The raw error text MUST be present in the message.\n"
    "                      Vague 'why did this break' without error text → use 'self_heal' instead.\n"
    "                      Advisory questions about errors → 'chat': 'when does ValueError occur?',\n"
    "                      'help my code has a bug' (no traceback), 'what causes KeyError?' → 'chat'.\n"
    "   'self_heal'      : user says adwi/service is broken or wants general repair WITHOUT pasting\n"
    "                      an actual error message. 'fix my setup', 'adwi is broken', 'repair ollama'.\n"
    "                      Also: 'something is broken', 'nothing is working', 'self-heal'.\n"
    "                      'doctor' is ONLY for EXPLICIT deep health-check requests\n"
    "                      ('run doctor', 'full health check', 'deep diagnostic').\n"
    "   'backup_now'     : backup workspace to GitHub, push backup. Includes 'push to github',\n"
    "                      'push my changes', 'save to github', 'commit and push' even when\n"
    "                      phrased in git terms. Different from 'git_status' which only READS\n"
    "                      repo state without committing or pushing anything.\n"
    "   'backup_status'  : check when the last backup ran, backup health, recent backup git log.\n"
    "   'backup_log'     : show the full backup history log file.\n"
    "   'image'          : analyze or describe an existing image file path\n"
    "   'model_status'   : user asks what model Adwi is using, which model is loaded/active,\n"
    "                      or asks to show model info. NOT a disk question.\n"
    "   'use_local'      : switch to a local Ollama model (llama, qwen, mistral, phi, gemma, etc.).\n"
    "                      'switch to local', 'use local model', 'use qwen', 'switch to llama'.\n"
    "   'use_cloud'      : switch to a cloud API model (gemini, gpt, openai, claude, etc.).\n"
    "                      'use gemini', 'switch to cloud', 'use gpt-4', 'cloud model'.\n"
    "   'voice_in'       : activate voice/microphone input, start listening, speech-to-text.\n"
    "                      'voice input', 'listen to me', 'start recording', 'voice mode'.\n"
    "   'voice_out'      : text-to-speech output — read aloud, speak, TTS, say this out loud.\n"
    "                      'text to speech', 'say this aloud', 'read this out loud', 'TTS'.\n"
    "   'file_read'      : read and display the contents of a specific file path.\n"
    "                      'read adwi_cli.py', 'show contents of README.md', 'cat this file'.\n"
    "   'file_list'      : list files in a specific directory or path (like ls). NOT a search.\n"
    "                      'ls downloads', 'list files in /tmp', 'what files are in my workspace'.\n"
    "   'file_search'    : search the filesystem for files by name, extension, or pattern.\n"
    "                      'find all .py files', 'search for config.yaml', 'locate requirements.txt'.\n"
    "   'git_status'     : git repository queries — branches, commits, diffs, staged/unstaged\n"
    "                      changes, recent history. Anything about the git state of the repo.\n"
    "                      'show recent commits', 'are there uncommitted changes', 'current branch'.\n"
    "   'nightly_status' : check when the nightly maintenance last ran and what it produced.\n"
    "                      'nightly status', 'when did nightly last run', 'show nightly log'.\n"
    "   'nightly_run'    : trigger / run the nightly maintenance routine now.\n"
    "                      'run nightly', 'trigger nightly', 'run daily maintenance'.\n"
    "   'trusted_roots'  : show which file paths / directories Adwi is allowed to read or write.\n"
    "                      'show trusted roots', 'what paths can adwi read', 'allowed directories'.\n"
    "   'memory_context' : show the current session memory/context summary.\n"
    "                      'show context', 'show my context', 'what context do you have',\n"
    "                      'current session context', 'context summary', 'show me the context'.\n"
    "   'benchmark'      : run an actual timed speed/performance test on local models.\n"
    "                      Use for CURRENT performance measurement questions: 'benchmark adwi',\n"
    "                      'run a speed test', 'how many tokens per second am I getting',\n"
    "                      'how fast is llama3.1:8b on this machine', 'what's my inference speed',\n"
    "                      'how performant is llama3.1 on my mac', 'time the model response',\n"
    "                      'tokens/s', 'how fast is ollama on this hardware'.\n"
    "                      NOT advisory/explanatory questions → those are 'chat':\n"
    "                      'why is ollama slow', 'how can I speed up my LLM', 'is 16GB enough',\n"
    "                      'what affects inference speed', 'how to make AI faster' → 'chat'.\n"
    "   'chat'           : DEFAULT for everything else — use this for:\n"
    "                      • advisory/recommendation questions ('what is the best...', 'should I...')\n"
    "                      • questions about tools, services, subscriptions NOT directly about adwi\n"
    "                      • comparisons ('X vs Y', 'which is better')\n"
    "                      • how-to questions, explanations, general knowledge\n"
    "                      • anything where the user wants a conversational answer, not a system action\n"
    "                      When in doubt, ALWAYS prefer 'chat' over any other intent.\n"
    "4. arguments  — Object of typed parameter slots the tool will consume:\n"
    "   path        : absolute or relative file/directory path\n"
    "   query       : search string or natural-language query for search/recall tools\n"
    "   url         : full URL (http/https)\n"
    "   size_mb     : integer megabyte threshold (e.g. 200 for '>200MB')\n"
    "   days        : integer day count (e.g. 365 for 'older than a year')\n"
    "   description : image generation prompt text\n"
    "   target      : generic string fallback when no typed key fits\n"
    "   Omit inapplicable keys. {} is valid.\n"
    "\n"
    "Return valid JSON only — no markdown fences, no prose explanation."
)

# ── Phase 7: Qdrant few-shot retrieval helpers ───────────────────────────────

_NLU_PROVISIONED = False   # module-level flag — provision once per process

def _ensure_nlu_fixtures_provisioned() -> None:
    """Provision the Qdrant nlu_fixtures collection on first NLU call."""
    global _NLU_PROVISIONED
    if _NLU_PROVISIONED:
        return
    _NLU_PROVISIONED = True  # set optimistically to avoid retry storms
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("adwi_memory", ADWI_DIR / "memory.py")
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.provision_nlu_fixtures()
        if result.get("seeded"):
            pass  # silent — user doesn't need to see this
    except Exception:
        pass  # non-fatal: Qdrant may be temporarily down


def _get_nlu_few_shots(text: str) -> str:
    """
    Query Qdrant nlu_fixtures for top-3 semantic matches and return a
    Markdown few-shot block to inject into the classification system prompt.
    Returns '' on any failure so the main NLU path is never blocked.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("adwi_memory", ADWI_DIR / "memory.py")
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        hits = mod.query_nlu_fixtures(text, k=3)
        if not hits:
            return ""
        lines = ["", "Relevant examples from NLU fixture store (ranked by semantic similarity):"]
        for h in hits:
            args_str = json.dumps(h.get("arguments", {})) if h.get("arguments") else "{}"
            lines.append(
                f'• "{h["user_phrase"]}" → intent: {h["intent"]}, arguments: {args_str}'
            )
        lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""


def classify_intent(text: str) -> dict:
    """Classify user intent: regex pre-filter → llama3.1:8b with JSON schema enforcement."""
    import time as _time
    _t0 = _time.monotonic()

    # 1. Instant checks (no model call needed)
    yt = extract_youtube_url(text)
    if yt: return {"intent": "youtube", "target": yt}
    img = extract_image_path(text)
    if img: return {"intent": "image", "target": img}

    # 2. Regex pre-filter — zero-latency for common phrases
    pre = _regex_prefilter(text)
    if pre: return {"intent": pre, "target": None}

    # 3. Structured LLM call with JSON schema enforcement + Phase 7 few-shot injection
    _ensure_nlu_fixtures_provisioned()
    few_shots = _get_nlu_few_shots(text)
    _system_with_shots = _INTENT_SYSTEM + few_shots if few_shots else _INTENT_SYSTEM
    with _otel_span("classify_intent", {
        "input.text": text[:200],
        "model": MODEL_FAST,
        "nlu.few_shot_count": str(few_shots.count("•")) if few_shots else "0",
    }):
        msgs = [
            {"role": "system", "content": _system_with_shots},
            {"role": "user",   "content": text},
        ]
        req = _ollama_chat(
            MODEL_FAST, msgs,
            stream=False, max_tokens=300, temperature=0, ctx=2048,
            json_schema=_INTENT_JSON_SCHEMA,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = json.load(resp).get("message", {}).get("content", "{}")
            raw = strip_think(raw)
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                result = json.loads(m.group(0))
                if result.get("intent") not in _ALL_INTENTS:
                    result["intent"] = "chat"
                # Ensure arguments is always a dict
                args = result.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
                result["arguments"] = args
                # Build backward-compat `target` from typed argument slots
                target = (
                    args.get("path") or args.get("url") or
                    args.get("query") or args.get("description") or
                    args.get("target")
                )
                if target and not str(target).startswith("/") and not str(target).startswith("http"):
                    guessed = Path(HOME / str(target)).expanduser()
                    if guessed.exists():
                        target = str(guessed)
                        args["path"] = target
                result["target"] = target
                result.setdefault("analysis", "")
                result["_latency_ms"] = int((_time.monotonic() - _t0) * 1000)
                return result
        except Exception:
            pass

    # 4. Fallback: ultra-fast qwen3:0.6b (minimal schema — no analysis block)
    _fallback_prompt = (
        "Return JSON only: {\"intent\": one of [" +
        ", ".join(f'"{i}"' for i in _ALL_INTENTS[:20]) +
        ", ...], \"arguments\": {}}. User: " + text
    )
    req2 = _ollama_chat(MODEL_NLU_FALLBACK, [{"role":"user","content":_fallback_prompt}],
                        stream=False, max_tokens=80, temperature=0, ctx=512)
    try:
        with urllib.request.urlopen(req2, timeout=8) as resp:
            raw = json.load(resp).get("message", {}).get("content", "{}")
        raw = strip_think(raw)
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            result = json.loads(m.group(0))
            if result.get("intent") in _ALL_INTENTS:
                args = result.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
                result["arguments"] = args
                result["target"] = (
                    args.get("path") or args.get("url") or
                    args.get("query") or args.get("target")
                )
                result.setdefault("analysis", "")
                result.setdefault("confidence", 0.5)
                result["_latency_ms"] = int((_time.monotonic() - _t0) * 1000)
                return result
    except Exception:
        pass

    return {"intent": "chat", "target": None, "arguments": {}, "analysis": "", "confidence": 0.0}

# ── Local streaming (adwi:latest) ─────────────────────────────────────────────
def stream_local(prompt, system=None, model=None, messages=None):
    m = model or load_routing().get("ADWI_LOCAL_MODEL", MODEL_MAIN)
    if messages is not None:
        msgs = messages
    else:
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

def _llm_generate(prompt: str, system: str = None, max_tokens: int = 600) -> str:
    """Non-streaming main-model call for silent content generation. Returns text."""
    m = load_routing().get("ADWI_LOCAL_MODEL", MODEL_MAIN)
    sys_msg = system or "You are Adwi, Suneel's personal AI assistant. Be concise and practical."
    msgs = [{"role": "system", "content": sys_msg},
            {"role": "user",   "content": "/no_think\n" + prompt}]
    req = _ollama_chat(m, msgs, stream=False, max_tokens=max_tokens, ctx=4096)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return strip_think(redact(json.load(resp).get("message", {}).get("content", "")))
    except Exception as e:
        return f"[LLM error: {e}]"


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
    global _SESSION_HISTORY
    r = load_routing()

    # Build system message
    _SYS = (
        "You are Adwi, Suneel's local AI assistant running on his M4 Max Mac (131K context, 64GB RAM). "
        "Your real capabilities include: web browsing (/browse), Gmail read-only (/gmail), "
        "git repo inspection (/git), semantic notes search (/rag), code execution (/run-python), "
        "image analysis (minicpm-v), YouTube summarization, disk analysis, and SearXNG web search. "
        "You DO have internet access through these tools. "
        "You are connected to GitHub via the gh CLI tool. "
        "Be practical, concise, warm. Never reveal secrets or do destructive/financial actions."
    )

    # Build messages list: system + recent history + current user turn
    max_msgs = _SESSION_MAX_TURNS * 2  # each turn = 1 user + 1 assistant
    prior = _SESSION_HISTORY[-max_msgs:] if _SESSION_HISTORY else []
    msgs = [{"role": "system", "content": _SYS}] + prior + [{"role": "user", "content": "/no_think\n" + prompt}]

    if r.get("ADWI_CHAT_BACKEND", "openwebui") == "openwebui":
        result = call_cloud(prompt, messages=msgs)
        if result:   # empty string means stream_local already printed (400 fallback)
            adwi_say(result)
            _SESSION_HISTORY.append({"role": "user",      "content": prompt})
            _SESSION_HISTORY.append({"role": "assistant", "content": result})
    else:
        result = stream_local(prompt, messages=msgs)
        if result:
            _SESSION_HISTORY.append({"role": "user",      "content": prompt})
            _SESSION_HISTORY.append({"role": "assistant", "content": result})

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
        headers = {"Content-Type": "application/json"}
        secret = os.environ.get("ADWI_LOCAL_SECRET", "")
        if secret:
            headers["X-Adwi-Secret"] = secret
        req  = urllib.request.Request(
            url, data=data, method=method, headers=headers,
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
    """Run Python code — Phase 2 gate + Phase 4 live heal on error."""
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

    # Phase 2: use rich gate with why-explanation
    approved = _rich_permission_gate(
        "PYTHON",
        code.splitlines()[0][:80] + (" …" if "\n" in code else ""),
        "Execute this Python code in an isolated temporary file to perform the requested operation.",
    )
    if not approved:
        cprint("  Cancelled.", GRAY); return

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code); tmp = f.name

    try:
        r = subprocess.run(
            ["python3", tmp], capture_output=True, text=True, timeout=30,
            env={**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
        )
        combined_err = (r.stderr or "").strip()
        if r.stdout: print(r.stdout)
        if combined_err:
            # Phase 4: try to heal before showing raw traceback
            patchable = any(t in combined_err for t in (
                "Traceback (most recent call last)", "ModuleNotFoundError",
                "ImportError", "AttributeError", "TypeError", "NameError",
            ))
            if patchable and r.returncode != 0:
                healed = _cli_live_heal(combined_err)
                if healed:
                    # Retry once after heal
                    r2 = subprocess.run(
                        ["python3", tmp], capture_output=True, text=True, timeout=30,
                        env={**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
                    )
                    if r2.stdout: print(r2.stdout)
                    if r2.stderr: cprint(r2.stderr[:500], YELLOW)
                    cprint(f"\n  exit {r2.returncode}", GRAY)
                    log_action("run-python", f"code:\n{code}\n\n[healed]\nstdout:\n{r2.stdout}\nstderr:\n{r2.stderr}")
                    return
                else:
                    cprint(combined_err[:1000], YELLOW)
            else:
                cprint(combined_err[:1000], YELLOW)
        cprint(f"\n  exit {r.returncode}", GRAY)
        log_action("run-python", f"code:\n{code}\n\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    except subprocess.TimeoutExpired:
        cprint("  Timed out (30s limit).", YELLOW)
    except Exception as e:
        cprint(f"  Error: {e}", RED)
    finally:
        Path(tmp).unlink(missing_ok=True)

def cmd_run_bash(raw: str) -> None:
    """Run a shell command — Phase 3 risk gate + Phase 2 rich gate + Phase 4 live heal."""
    cmd = raw.strip()
    if not cmd:
        cprint("  No command given.", YELLOW); return

    # Phase 3: three-tier classification
    risk = _classify_cli_risk(cmd)
    if risk == "BLOCKED":
        cprint(f"  {RED}Blocked: command matches destructive/financial deny pattern.{RESET}", ""); return

    adwi_head("Run bash")

    if risk == "REVIEW-REQUIRED":
        # Phase 2: rich permission gate with WHY explanation
        # Ask the fast model for a one-line why
        try:
            import urllib.request as _ur, json as _j
            _payload = _j.dumps({
                "model": "llama3.1:8b",
                "messages": [
                    {"role": "user", "content": f"/no_think\nIn one sentence, why would someone run this shell command: `{cmd[:200]}`"}
                ],
                "stream": False, "options": {"temperature": 0.1, "num_predict": 60},
            }).encode()
            _req = _ur.Request("http://127.0.0.1:11434/api/chat", data=_payload,
                               headers={"Content-Type": "application/json"})
            with _ur.urlopen(_req, timeout=12) as _r:
                why = _j.loads(_r.read())["message"]["content"].strip().splitlines()[0]
        except Exception:
            why = "This command requires elevated access or makes persistent changes."

        approved = _rich_permission_gate("SHELL", cmd, why)
        if not approved:
            cprint("  Cancelled.", GRAY); return
    else:
        # SAFE: simple confirmation (no LLM roundtrip)
        cprint(f"  $ {cmd}", CYAN)
        ans = input(f"\n  {YELLOW}Run this? (y/n){RESET} ").strip().lower()
        if ans not in ("y", "yes"):
            cprint("  Cancelled.", GRAY); return

    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
        )
        combined_out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
        combined_err = (r.stderr or "").strip()

        # Phase 4: intercept patchable runtime errors
        patchable = any(t in combined_err for t in (
            "Traceback (most recent call last)", "ModuleNotFoundError", "ImportError",
            "AttributeError", "TypeError", "NameError", "SyntaxError",
        ))
        if patchable and r.returncode != 0:
            healed = _cli_live_heal(combined_err)
            if healed:
                r2 = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=60,
                    env={**os.environ, "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
                )
                out2 = (r2.stdout or "") + (("\n[stderr] " + r2.stderr) if r2.stderr else "")
                print(redact(out2))
                cprint(f"\n  exit {r2.returncode}", GRAY)
                log_action("run-bash", f"cmd: {cmd}\n\n[healed]\n{redact(out2)}")
                return

        print(redact(combined_out))
        cprint(f"\n  exit {r.returncode}", GRAY)
        log_action("run-bash", f"cmd: {cmd}\n\n{redact(combined_out)}")
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
    """Run one-time OAuth2 browser flow to authorize Gmail (Phase 2: gmail.modify scope)."""
    adwi_head("Gmail authorization")
    cprint("  This will open your browser for Google OAuth2 sign-in.", CYAN)
    cprint("  Scope: gmail.modify — read + archive / trash / mark-read (no send)", GREEN)
    ans = input(f"  {YELLOW}Proceed? (y/n){RESET} ").strip().lower()
    if ans not in ("y","yes"):
        cprint("  Cancelled.", GRAY); return
    try:
        gh = _gmail()
        # Delete existing token so we always get a fresh flow with the current scope
        token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
        if token.exists():
            token.unlink()
            cprint("  Old token removed — re-authorizing with gmail.modify scope…", GRAY)
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
        _GMAIL_IDS.clear();     _GMAIL_IDS.extend(em["id"] for em in emails)
        _GMAIL_SUBJECTS.clear(); _GMAIL_SUBJECTS.extend(em["subject"] for em in emails)
        _GMAIL_CTX["thread_ids"] = [em.get("thread_id", "") for em in emails]
        _GMAIL_CTX["candidates"] = list(emails)
        _GMAIL_CTX["pending"]    = None  # clear any pending action from previous context
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)
        if "credentials" in str(e).lower() or "token" in str(e).lower():
            cprint("  Try: /gmail-auth  to re-authorize", GRAY)

_GMAIL_IDS: list = []       # ephemeral id list for /gmail-read <n>
_GMAIL_SUBJECTS: list = []  # parallel subject list for "open this email [subject]" lookup

_GMAIL_CTX: dict = {
    "current_email":     None,  # full email dict — set by cmd_gmail_read / cmd_gmail_open
    "current_thread":    None,  # full thread dict — set by cmd_gmail_thread
    "thread_ids":        [],    # thread IDs parallel to _GMAIL_IDS
    "candidates":        [],    # candidate email dicts from last list/category (Phase 2)
    "draft":             None,  # current draft (Phase 3): {draft_id, to, cc, bcc, subject, body, mode, …}
    "pending":           None,  # pending mutation (Phase 2): {action, ids, count, description}
    "pending_recipient": None,  # Phase 4: {name, instruction, candidates, mode, subject, cc, bcc}
    "contacts":          {},    # Phase 5: session contact cache {normalized_name: {email, display}}
    "attachments":        [],   # Phase 6: attachment metadata list from current email/thread
    "current_attachment": None, # Phase 6: last selected/saved attachment dict
    "pending_attach":     None, # Phase 7: file disambiguation candidates [{path, filename, size}]
    "last_mutation":      None, # Phase 8: undo — {action, ids, count, description} of last confirmed op
    "triage_results":     None, # Phase 9: {reply_needed, action_needed, fyi, noise} id lists
    "scheduled_send":     None, # Phase 10: {id, draft_id, to, subject, send_at_iso} or None
    "selected_scheduled": None, # Phase 13: user-selected scheduled-send entry
    "last_sent":          None, # Phase 11: {thread_id, to, subject, sent_at_iso} — captured after send
    "followup_reminder":  None, # Phase 11: most recently created follow-up reminder entry
    "draft_list":         [],   # Phase 12: cached [{draft_id,to,subject,mode,has_attachment,…}] from list_drafts
    "thread_intel":       None, # Phase 15: last thread intelligence result {mode, subject}
    "pending_rule":       None, # Phase 16: candidate filter rule dict or None
    "pending_tasks":      None, # Phase 17: extracted tasks/deadlines/decisions dict or None
}

_GMAIL_ACTION_PAST = {
    "archive":     "archived",
    "trash":       "moved to trash",
    "mark_read":   "marked as read",
    "mark_unread": "marked as unread",
}

_GMAIL_MAX_CANDIDATES  = 25  # hard cap on mutation batch size
ATTACH_SAVE_DIR        = BASE / "gmail-attachments"  # Phase 6: bounded attachment save dir
SCHEDULED_SENDS_FILE   = BASE / "adwi" / "scheduled_sends.json"  # Phase 10: pending scheduled-send queue
FOLLOWUP_FILE          = BASE / "adwi" / "followup_reminders.json"  # Phase 11: follow-up reminders queue
GMAIL_RULES_FILE       = BASE / "adwi" / "gmail_rules.json"         # Phase 16: local rule store

_GMAIL_CATEGORY_MAP = {
    "promotions": "CATEGORY_PROMOTIONS", "promotion":  "CATEGORY_PROMOTIONS",
    "promo":      "CATEGORY_PROMOTIONS", "promos":     "CATEGORY_PROMOTIONS",
    "promotional":"CATEGORY_PROMOTIONS", "newsletter": "CATEGORY_PROMOTIONS",
    "newsletters":"CATEGORY_PROMOTIONS",
    "social":     "CATEGORY_SOCIAL",    "socials":    "CATEGORY_SOCIAL",
    "updates":    "CATEGORY_UPDATES",   "update":     "CATEGORY_UPDATES",
    "forums":     "CATEGORY_FORUMS",    "forum":      "CATEGORY_FORUMS",
    "spam":       "SPAM",
}

# ── Gmail Phase 9: triage signal patterns ──────────────────────────────────────

_TRIAGE_NOISE_FROM = re.compile(
    r"\b(?:noreply|no-reply|notifications?|newsletter|mailer(?:[-_]|daemon)?|"
    r"bounce|automailer|alerts?|do-?not-?reply|support-ticket|info@)\b",
    re.I,
)
_TRIAGE_NOISE_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS", "SPAM"}
_TRIAGE_ACTION_SUBJECT = re.compile(
    r"\b(?:invoice|payment|due|deadline|urgent|asap|action\s+required|"
    r"approval\s+(?:needed|required)|please\s+review|meeting\s+request|"
    r"sign[-\s]off|by\s+(?:eod|eow|end\s+of\s+(?:day|week)|friday|monday|today|tomorrow))\b",
    re.I,
)
_TRIAGE_REPLY_SNIPPET = re.compile(
    r"(?:\?|can\s+you|could\s+you|please\s+(?:let\s+me\s+know|confirm|respond|reply|send)|"
    r"let\s+me\s+know|do\s+you\s+have|are\s+you\s+able|would\s+you)",
    re.I,
)


def _gmail_precheck_noise(em: dict) -> bool:
    """Return True if email is likely noise from structural signals alone."""
    label_ids = em.get("label_ids", [])
    if _TRIAGE_NOISE_LABELS.intersection(label_ids):
        return True
    if _TRIAGE_NOISE_FROM.search(em.get("from", "")):
        return True
    return False


def _gmail_triage_llm(emails: list) -> list:
    """
    Classify up to 20 emails via a single LLM batch call.
    Returns [{id, triage, reason}, ...] or [] on LLM failure / JSON parse error.
    triage values: reply_needed | action_needed | fyi | noise
    """
    if not emails:
        return []
    lines = []
    for i, em in enumerate(emails, 1):
        sender  = em.get("from", "")[:45]
        subject = em.get("subject", "")[:70]
        snippet = em.get("snippet", "")[:150]
        eid     = em["id"][:8]
        lines.append(
            f"[{i}] id={eid}\n"
            f"  From: {sender}\n"
            f"  Subject: {subject}\n"
            f"  Preview: {snippet}"
        )
    digest = "\n\n".join(lines)
    prompt = (
        "Classify each inbox email for inbox triage. Return ONLY a valid JSON array.\n"
        "triage must be exactly one of: reply_needed, action_needed, fyi, noise\n"
        "  reply_needed  — direct question or clearly expects Suneel's personal response\n"
        "  action_needed — deadline, invoice, payment, approval needed, meeting request\n"
        "  fyi           — informational only, no reply or action required\n"
        "  noise         — newsletter, marketing, automated alert, social notification\n"
        "reason: max 8 plain words, no quotes inside the string\n\n"
        "Return ONLY valid JSON (no markdown, no code fences, no explanation outside the array):\n"
        '[{"id":"12345678","triage":"reply_needed","reason":"direct question about timeline"}]\n\n'
        "Emails:\n" + digest
    )
    raw = _llm_generate(
        prompt,
        system=(
            "You are classifying inbox emails for a personal assistant. "
            "Output ONLY a valid JSON array. No explanation, no markdown."
        ),
        max_tokens=1600,
    )
    try:
        start = raw.index('[')
        end   = raw.rindex(']') + 1
        data  = json.loads(raw[start:end])
        if isinstance(data, list):
            return data
    except (ValueError, json.JSONDecodeError):
        pass
    return []


def cmd_gmail_triage(text: str = "") -> None:
    """
    Phase 9: Inbox triage — classify inbox emails into reply_needed / action_needed / fyi / noise.
    Read-only: never mutates the mailbox.
    """
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return

    # ── Mode detection from natural language ──────────────────────────────────
    txt_l = text.lower()
    if re.search(r"\b(?:today|this\s+morning|this\s+afternoon)\b", txt_l):
        query = "is:unread in:inbox newer_than:1d"
        mode  = "today"
    elif re.search(r"\b(?:reply|respond|answer|waiting\s+(?:on|for)\s+me)\b", txt_l):
        query = "is:unread in:inbox newer_than:7d"
        mode  = "reply"
    elif re.search(r"\b(?:urgent|asap|critical|action\s+required|high\s+priority)\b", txt_l):
        query = "is:unread in:inbox newer_than:7d"
        mode  = "urgent"
    else:
        query = "is:unread in:inbox newer_than:7d"
        mode  = "full"

    adwi_head(f"Gmail — Inbox Triage ({mode})")
    cprint("  Fetching inbox…", GRAY)

    try:
        gh = _gmail()
        emails = gh.list_inbox_for_triage(max_results=20, query=query)
    except Exception as e:
        cprint(f"  Failed to fetch inbox: {e}", RED)
        if "403" in str(e) or "scope" in str(e).lower():
            cprint("  Scope error — run /gmail-auth to re-authorize.", YELLOW)
        return

    if not emails:
        cprint("  No unread emails found for this query.", GRAY)
        return

    cprint(f"  Fetched {len(emails)} email{'s' if len(emails) != 1 else ''}. Classifying…", GRAY)

    # ── Structural pre-filter: noise detection before LLM ────────────────────
    structural_noise: list = []
    to_classify: list      = []
    for em in emails:
        if _gmail_precheck_noise(em):
            structural_noise.append(em)
        else:
            to_classify.append(em)

    # ── LLM batch classification ──────────────────────────────────────────────
    llm_results: dict = {}   # id[:8] → {triage, reason}
    if to_classify:
        raw_results = _gmail_triage_llm(to_classify)
        for r in raw_results:
            if isinstance(r, dict) and "id" in r and "triage" in r:
                llm_results[r["id"][:8]] = {
                    "triage": r.get("triage", "fyi"),
                    "reason": r.get("reason", ""),
                }

    # ── Build buckets ─────────────────────────────────────────────────────────
    buckets: dict = {"reply_needed": [], "action_needed": [], "fyi": [], "noise": []}

    for em in structural_noise:
        buckets["noise"].append(em)

    for em in to_classify:
        eid8   = em["id"][:8]
        result = llm_results.get(eid8)
        if result:
            triage = result["triage"]
            if triage not in buckets:
                triage = "fyi"
        else:
            # Structural fallback when LLM didn't classify this one
            if _TRIAGE_ACTION_SUBJECT.search(em.get("subject", "")):
                triage = "action_needed"
            elif _TRIAGE_REPLY_SNIPPET.search(em.get("snippet", "")):
                triage = "reply_needed"
            elif em.get("is_unread"):
                triage = "fyi"
            else:
                triage = "noise"
        buckets[triage].append(em)

    # Urgent mode: elevate action_needed emails to top when user asks for urgent
    if mode == "urgent":
        buckets["reply_needed"] = buckets["action_needed"] + buckets["reply_needed"]
        buckets["action_needed"] = []

    # ── Render grouped output ─────────────────────────────────────────────────
    display_list: list = []  # ordered list for follow-up (candidates)

    _BUCKET_LABELS = [
        ("reply_needed",  f"{RED}● Reply Needed{RESET}"),
        ("action_needed", f"{YELLOW}▲ Action Needed{RESET}"),
        ("fyi",           f"{CYAN}ℹ  FYI{RESET}"),
        ("noise",         f"{GRAY}~ Noise{RESET}"),
    ]

    any_shown = False
    for bucket_key, label in _BUCKET_LABELS:
        items = buckets[bucket_key]
        if not items:
            continue
        any_shown = True
        cprint(f"\n  {label}  ({len(items)})", "")
        cprint("  " + "─" * 60, GRAY)
        for em in items:
            display_list.append(em)
            idx        = len(display_list)
            eid8       = em["id"][:8]
            result     = llm_results.get(eid8)
            reason_str = f" — {result['reason']}" if result and result.get("reason") else ""
            unread_dot = "•" if em.get("is_unread") else " "
            sender     = em.get("from", "").split("<")[0].strip()[:22]
            subject    = em.get("subject", "")[:48]
            cprint(f"  {unread_dot} [{idx}] {sender:<23} {subject}{reason_str}", "")

    if not any_shown:
        cprint("  No emails to triage.", GRAY)
        return

    # ── Populate session context for follow-up commands ───────────────────────
    global _GMAIL_IDS, _GMAIL_SUBJECTS
    _GMAIL_IDS      = [em["id"] for em in display_list]
    _GMAIL_SUBJECTS = [em.get("subject", "") for em in display_list]
    _GMAIL_CTX["candidates"]     = display_list
    _GMAIL_CTX["triage_results"] = {
        "reply_needed":  [em["id"] for em in buckets["reply_needed"]],
        "action_needed": [em["id"] for em in buckets["action_needed"]],
        "fyi":           [em["id"] for em in buckets["fyi"]],
        "noise":         [em["id"] for em in buckets["noise"]],
        "mode":          mode,
    }

    # Summary footer
    rn = len(buckets["reply_needed"])
    an = len(buckets["action_needed"])
    cprint(f"\n  {GRAY}Tip: 'open 1' reads an email · 'reply to 1' drafts a reply · 'archive those' · 'undo'{RESET}", "")
    if rn + an > 0:
        cprint(
            f"  {YELLOW}{rn} needing reply · {an} needing action{RESET} — "
            f"use 'show reply-needed' to refilter.", ""
        )


# ── Gmail Phase 10: scheduled send ─────────────────────────────────────────────

_DAYS_OF_WEEK = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

_TIME_OF_DAY_DEFAULTS = {
    "morning":   9,
    "afternoon": 14,
    "evening":   18,
    "tonight":   21,
    "night":     21,
    "noon":      12,
    "midday":    12,
    "eod":       17,
    "end of day":17,
    "end-of-day":17,
    "eow":       9,   # end of week → Friday 9 AM (special-cased below)
}


def _resolve_schedule_time(text: str) -> tuple:
    """
    Parse a natural-language schedule phrase into (datetime, human_label).
    Returns (None, error_msg) if phrase is too ambiguous or cannot be resolved.

    Supported patterns (case-insensitive):
      in N minutes / in N hours
      at HH:MM / at H PM / at H AM / at H (context-aware)
      tonight / this morning / this afternoon / this evening
      tomorrow [morning|afternoon|evening|at TIME]
      [next] WEEKDAY [at TIME]
      EOD / end of day / noon / midday
    """
    now  = datetime.now()
    text_l = text.lower().strip()

    def _apply_hm(base: datetime, h: int, m: int = 0) -> datetime:
        return base.replace(hour=h, minute=m, second=0, microsecond=0)

    # ── "in N minutes / hours / days / weeks" ────────────────────────────────
    m = re.search(r"\bin\s+(\d+|a|an)\s+(minute|min|hour|hr|day|week)s?\b", text_l)
    if m:
        n_raw, unit = m.group(1), m.group(2)
        n = 1 if n_raw in ("a", "an") else int(n_raw)
        if unit.startswith("w"):
            delta = timedelta(weeks=n)
        elif unit.startswith("d"):
            delta = timedelta(days=n)
        elif unit.startswith("h"):
            delta = timedelta(hours=n)
        else:
            delta = timedelta(minutes=n)
        dt = now + delta
        label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')}"
        return dt, label

    # ── Explicit time "at H:MM PM" / "at H PM" / "at H" ──────────────────────
    time_m = re.search(
        r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)?\b", text_l
    )
    parsed_hour, parsed_min = None, 0
    if time_m:
        parsed_hour = int(time_m.group(1))
        parsed_min  = int(time_m.group(2)) if time_m.group(2) else 0
        meridiem    = (time_m.group(3) or "").lower()
        if meridiem == "pm" and parsed_hour < 12:
            parsed_hour += 12
        elif meridiem == "am" and parsed_hour == 12:
            parsed_hour = 0
        elif not meridiem:
            # Ambiguous — if hour < 8, assume PM (e.g. "at 3" → 3 PM)
            if parsed_hour < 8:
                parsed_hour += 12

    # ── "next week" ───────────────────────────────────────────────────────────
    if re.search(r"\bnext\s+week\b", text_l):
        target = now + timedelta(weeks=1)
        h = parsed_hour if parsed_hour is not None else 9
        dt = _apply_hm(target, h, parsed_min)
        label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')}"
        return dt, label

    # ── "tonight" / "this evening" / "this morning" / "this afternoon" ────────
    for phrase, default_h in [
        ("tonight", 21), ("this evening", 18), ("this night", 21),
        ("this morning", 9), ("this afternoon", 14),
    ]:
        if phrase in text_l:
            h = parsed_hour if parsed_hour is not None else default_h
            dt = _apply_hm(now, h, parsed_min)
            if dt <= now:
                dt += timedelta(days=1)
            label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')}"
            return dt, label

    # ── "today" ───────────────────────────────────────────────────────────────
    if re.search(r"\btoday\b", text_l):
        if parsed_hour is not None:
            dt = _apply_hm(now, parsed_hour, parsed_min)
            if dt <= now:
                return None, "That time has already passed today — did you mean tomorrow?"
            label = f"today at {dt.strftime('%-I:%M %p')}"
            return dt, label
        return None, "Please specify a time — e.g. 'today at 3 PM'."

    # ── "tomorrow [morning|afternoon|time]" ───────────────────────────────────
    if re.search(r"\btomorrow\b", text_l):
        tomorrow = now + timedelta(days=1)
        h = parsed_hour
        if h is None:
            for tod, dh in _TIME_OF_DAY_DEFAULTS.items():
                if tod in text_l:
                    h = dh; break
        h = h if h is not None else 9   # default: tomorrow 9 AM
        dt = _apply_hm(tomorrow, h, parsed_min)
        label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')}"
        return dt, label

    # ── "[next] WEEKDAY [at TIME]" ────────────────────────────────────────────
    for day_name, day_num in _DAYS_OF_WEEK.items():
        if re.search(rf"\b{day_name}\b", text_l):
            today_num = now.weekday()
            days_ahead = (day_num - today_num) % 7
            if days_ahead == 0:
                days_ahead = 7   # "Monday" when today is Monday → next Monday
            target = now + timedelta(days=days_ahead)
            h = parsed_hour
            if h is None:
                for tod, dh in _TIME_OF_DAY_DEFAULTS.items():
                    if tod in text_l:
                        h = dh; break
            h = h if h is not None else 9
            dt = _apply_hm(target, h, parsed_min)
            label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')}"
            return dt, label

    # ── Bare time-of-day (no date context) ────────────────────────────────────
    for tod, dh in _TIME_OF_DAY_DEFAULTS.items():
        if re.search(rf"\b{re.escape(tod)}\b", text_l):
            h = parsed_hour if parsed_hour is not None else dh
            dt = _apply_hm(now, h, parsed_min)
            if dt <= now:
                dt += timedelta(days=1)
            label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')}"
            return dt, label

    # ── Bare explicit time only ("at 3 PM") ───────────────────────────────────
    if parsed_hour is not None:
        dt = _apply_hm(now, parsed_hour, parsed_min)
        if dt <= now:
            dt += timedelta(days=1)
        label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')}"
        return dt, label

    return None, (
        "I couldn't parse a send time from that. "
        "Try: 'tomorrow morning', 'Monday at 9 AM', 'at 3 PM', 'in 2 hours'."
    )


def _load_scheduled_sends() -> list:
    """Read the scheduled-sends queue file. Returns [] if missing or corrupt."""
    try:
        if SCHEDULED_SENDS_FILE.exists():
            return json.loads(SCHEDULED_SENDS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_scheduled_sends(entries: list) -> None:
    """Write the scheduled-sends queue atomically."""
    SCHEDULED_SENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULED_SENDS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")
    tmp.replace(SCHEDULED_SENDS_FILE)


def _load_followup_reminders() -> list:
    """Read the follow-up reminders file. Returns [] if missing or corrupt."""
    try:
        if FOLLOWUP_FILE.exists():
            return json.loads(FOLLOWUP_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_followup_reminders(entries: list) -> None:
    """Write the follow-up reminders file atomically."""
    FOLLOWUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FOLLOWUP_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")
    tmp.replace(FOLLOWUP_FILE)


def cmd_gmail_schedule_send(text: str = "") -> None:
    """
    Phase 10: Schedule the current draft to be sent at a future time.
    Shows a preview with the resolved timestamp, then confirms before scheduling.
    """
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return

    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft to schedule. Create one first with 'compose' or 'reply saying …'.", YELLOW)
        return

    draft_id = draft.get("draft_id")
    to       = draft.get("to", "")
    subject  = draft.get("subject", "")
    if not draft_id:
        cprint("  Draft has no saved draft ID — cannot schedule. Try recreating the draft.", RED)
        return

    # ── Parse time from user text ─────────────────────────────────────────────
    dt, label = _resolve_schedule_time(text)
    if dt is None:
        adwi_head("Gmail — Schedule Send")
        cprint(f"  {YELLOW}{label}{RESET}", "")
        return

    if dt <= datetime.now():
        adwi_head("Gmail — Schedule Send")
        cprint(f"  {YELLOW}Resolved time is in the past ({label}). Please pick a future time.{RESET}", "")
        return

    # ── Preview ───────────────────────────────────────────────────────────────
    adwi_head("Gmail — Schedule Send")
    cprint(f"  To:       {to}", "")
    cprint(f"  Subject:  {subject}", "")
    cprint(f"  Send at:  {YELLOW}{label}{RESET}", "")
    cprint(f"  Draft ID: {draft_id[:20]}…", GRAY)
    cprint("", "")
    ans = input(f"  {YELLOW}Schedule this send? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled — draft still saved in Gmail.", GRAY)
        return

    # ── Persist to queue ──────────────────────────────────────────────────────
    import hashlib as _hlib
    uid = "ss_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + _hlib.md5(draft_id.encode()).hexdigest()[:4]
    entry = {
        "id":            uid,
        "draft_id":      draft_id,
        "to":            to,
        "subject":       subject,
        "send_at_iso":   dt.isoformat(timespec="seconds"),
        "created_at_iso":datetime.now().isoformat(timespec="seconds"),
        "status":        "pending",
    }
    entries = _load_scheduled_sends()
    entries.append(entry)
    _save_scheduled_sends(entries)

    _GMAIL_CTX["scheduled_send"] = entry
    cprint(f"\n  {GREEN}✓ Scheduled — '{subject[:40]}' will be sent {label}.{RESET}", "")
    cprint(f"  {GRAY}ID: {uid}  ·  'show scheduled' to review  ·  'cancel scheduled send' to undo{RESET}", "")


def cmd_gmail_list_scheduled() -> None:
    """Phase 10: Show all Adwi-scheduled pending sends."""
    entries = _load_scheduled_sends()
    pending = [e for e in entries if e.get("status") == "pending"]
    sent    = [e for e in entries if e.get("status") == "sent"]
    failed  = [e for e in entries if e.get("status") == "failed"]

    adwi_head("Gmail — Scheduled Sends")
    if not entries:
        cprint("  No scheduled sends on record.", GRAY)
        return

    if pending:
        cprint(f"\n  {YELLOW}Pending ({len(pending)}){RESET}", "")
        cprint("  " + "─" * 58, GRAY)
        for i, e in enumerate(pending, 1):
            try:
                dt   = datetime.fromisoformat(e["send_at_iso"])
                when = dt.strftime("%a %b %-d at %-I:%M %p")
            except Exception:
                when = e.get("send_at_iso", "?")
            to_short = e.get("to", "?")[:35]
            subj     = e.get("subject", "?")[:40]
            cprint(f"  [{i}] {when:<25} To: {to_short}", "")
            cprint(f"       {GRAY}{subj}  ·  id: {e.get('id','?')}{RESET}", "")

    if sent:
        cprint(f"\n  {GREEN}Sent ({len(sent)}){RESET}", "")
        for e in sent[-3:]:   # show last 3
            cprint(f"  ✓ {e.get('send_at_iso','?')[:16]}  {e.get('subject','?')[:40]}", GRAY)

    if failed:
        cprint(f"\n  {RED}Failed ({len(failed)}){RESET}", "")
        for e in failed:
            cprint(f"  ✗ {e.get('send_at_iso','?')[:16]}  {e.get('subject','?')[:40]}", RED)

    if pending:
        cprint(f"\n  {GRAY}'reschedule [n] to [time]' · 'open scheduled draft [n]' · 'cancel scheduled send [n]'{RESET}", "")
        cprint(f"  {GRAY}runner checks every 2 min{RESET}", "")


def cmd_gmail_cancel_scheduled_send(text: str = "") -> None:
    """Phase 10: Cancel a pending scheduled send (by index, ID, or most recent)."""
    entries  = _load_scheduled_sends()
    pending  = [e for e in entries if e.get("status") == "pending"]

    adwi_head("Gmail — Cancel Scheduled Send")
    if not pending:
        cprint("  No pending scheduled sends to cancel.", GRAY)
        _GMAIL_CTX["scheduled_send"] = None
        return

    # Select via shared helper (ordinal, digit, keyword)
    target, ambiguous = _resolve_scheduled_ref(text)
    if ambiguous:
        cprint(f"  Multiple pending sends match — which one?", YELLOW)
        for i, e in enumerate(ambiguous, 1):
            try:
                when = datetime.fromisoformat(e["send_at_iso"]).strftime("%a %b %-d at %-I:%M %p")
            except Exception:
                when = e.get("send_at_iso", "?")[:16]
            cprint(f"  [{i}] {when:<25} {e.get('subject','?')[:40]}", "")
        return
    if target is None:
        if len(pending) == 1:
            target = pending[0]
        else:
            cprint(f"  {len(pending)} pending sends — say 'cancel scheduled send 1', 'cancel the Rahul send', etc.", YELLOW)
            for i, e in enumerate(pending, 1):
                try:
                    when = datetime.fromisoformat(e["send_at_iso"]).strftime("%a %b %-d at %-I:%M %p")
                except Exception:
                    when = e.get("send_at_iso", "?")[:16]
                cprint(f"  [{i}] {when:<25} {e.get('subject','?')[:40]}", "")
            return

    try:
        dt   = datetime.fromisoformat(target["send_at_iso"])
        when = dt.strftime("%a %b %-d at %-I:%M %p")
    except Exception:
        when = target.get("send_at_iso", "?")

    cprint(f"  Cancelling: '{target.get('subject','?')[:50]}' scheduled for {when}", "")
    ans = input(f"  {YELLOW}Confirm cancel? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Kept.", GRAY); return

    target["status"] = "cancelled"
    _save_scheduled_sends(entries)
    if (_GMAIL_CTX.get("scheduled_send") or {}).get("id") == target["id"]:
        _GMAIL_CTX["scheduled_send"] = None
    cprint(f"  {GREEN}✓ Cancelled — draft still exists in Gmail and can be sent manually.{RESET}", "")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 13 — Reschedule / open scheduled sends
# ─────────────────────────────────────────────────────────────────────────────

def cmd_gmail_reschedule_send(text: str = "") -> None:
    """Phase 13: Move a pending scheduled send to a new time."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return

    entries = _load_scheduled_sends()
    pending = [e for e in entries if e.get("status") == "pending"]

    adwi_head("Gmail — Reschedule Scheduled Send")
    if not pending:
        cprint("  No pending scheduled sends to reschedule.", GRAY); return

    target, ambiguous = _resolve_scheduled_ref(text)

    if ambiguous:
        cprint("  Multiple scheduled sends match — which one?", YELLOW)
        for i, e in enumerate(ambiguous, 1):
            try:
                when = datetime.fromisoformat(e["send_at_iso"]).strftime("%a %b %-d at %-I:%M %p")
            except Exception:
                when = e.get("send_at_iso", "?")[:16]
            cprint(f"  [{i}] {when:<25} {e.get('subject','?')[:40]}  →  {e.get('to','?')[:30]}", "")
        cprint("  Say: 'reschedule 1 to tomorrow morning', 'reschedule the Rahul send to Monday', etc.", GRAY)
        return

    if target is None:
        if len(pending) == 1:
            target = pending[0]
        else:
            cprint(f"  {len(pending)} pending sends — specify which one (ordinal, number, or name).", YELLOW)
            for i, e in enumerate(pending, 1):
                try:
                    when = datetime.fromisoformat(e["send_at_iso"]).strftime("%a %b %-d at %-I:%M %p")
                except Exception:
                    when = e.get("send_at_iso", "?")[:16]
                cprint(f"  [{i}] {when:<25} {e.get('subject','?')[:40]}", "")
            return

    # Extract time phrase after a preposition when present
    time_text = text
    m_prep = re.search(r"\b(?:to|until|for)\b\s*(.+)", text, re.I | re.DOTALL)
    if m_prep:
        time_text = m_prep.group(1).strip()

    dt, label = _resolve_schedule_time(time_text)
    if dt is None:
        cprint(f"  {YELLOW}{label}{RESET}", "")
        cprint("  Try: 'reschedule to tomorrow morning', 'reschedule the Rahul send to Friday at 9 AM'.", GRAY)
        return

    if dt <= datetime.now():
        cprint(f"  {YELLOW}Resolved time is in the past ({label}). Please pick a future time.{RESET}", "")
        return

    try:
        old_when = datetime.fromisoformat(target["send_at_iso"]).strftime("%a %b %-d at %-I:%M %p")
    except Exception:
        old_when = target.get("send_at_iso", "?")[:16]

    cprint(f"  Subject:   {target.get('subject','?')[:55]}", "")
    cprint(f"  To:        {target.get('to','?')[:55]}", "")
    cprint(f"  Was:       {GRAY}{old_when}{RESET}", "")
    cprint(f"  New time:  {YELLOW}{label}{RESET}", "")
    ans = input(f"  {YELLOW}Reschedule to {label}? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Kept original schedule.", GRAY); return

    target["send_at_iso"] = dt.isoformat(timespec="seconds")
    target["rescheduled_at_iso"] = datetime.now().isoformat(timespec="seconds")
    _save_scheduled_sends(entries)

    if (_GMAIL_CTX.get("scheduled_send") or {}).get("id") == target["id"]:
        _GMAIL_CTX["scheduled_send"] = target
    if (_GMAIL_CTX.get("selected_scheduled") or {}).get("id") == target["id"]:
        _GMAIL_CTX["selected_scheduled"] = target

    cprint(f"  {GREEN}✓ Rescheduled — will now send {label}.{RESET}", "")


def cmd_gmail_open_scheduled_draft(text: str = "") -> None:
    """Phase 13: Load the underlying draft from a pending scheduled send into session context."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return

    adwi_head("Gmail — Open Scheduled Draft")

    target, ambiguous = _resolve_scheduled_ref(text)
    if ambiguous:
        cprint("  Multiple pending sends match — which one?", YELLOW)
        for i, e in enumerate(ambiguous, 1):
            try:
                when = datetime.fromisoformat(e["send_at_iso"]).strftime("%a %b %-d at %-I:%M %p")
            except Exception:
                when = e.get("send_at_iso", "?")[:16]
            cprint(f"  [{i}] {when:<25} {e.get('subject','?')[:40]}  →  {e.get('to','?')[:30]}", "")
        return

    if target is None:
        entries = _load_scheduled_sends()
        pending = [e for e in entries if e.get("status") == "pending"]
        if not pending:
            cprint("  No pending scheduled sends found.", GRAY); return
        if len(pending) == 1:
            target = pending[0]
        else:
            cprint("  Specify which scheduled send to open (by ordinal or name).", YELLOW)
            for i, e in enumerate(pending, 1):
                cprint(f"  [{i}] {e.get('subject','?')[:50]}  →  {e.get('to','?')[:30]}", "")
            return

    draft_id = target.get("draft_id", "")
    if not draft_id:
        cprint("  This scheduled send has no draft ID on record.", RED); return

    try:
        gh = _gmail()
        full_draft = gh.get_draft(draft_id)
    except Exception as exc:
        cprint(f"  Error loading draft: {exc}", RED)
        cprint("  The draft may have already been sent or deleted.", YELLOW); return

    _GMAIL_CTX["draft"] = full_draft
    _GMAIL_CTX["selected_scheduled"] = target

    try:
        when = datetime.fromisoformat(target["send_at_iso"]).strftime("%a %b %-d at %-I:%M %p")
    except Exception:
        when = target.get("send_at_iso", "?")[:16]

    cprint(f"  Draft loaded. This send is scheduled for {YELLOW}{when}{RESET}.", "")
    cprint(f"  {GRAY}To change the schedule: 'reschedule to [new time]'", "")
    cprint(f"  To cancel the scheduled send: 'cancel the scheduled send'{RESET}", "")
    _gmail_draft_preview(full_draft)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 11 — Follow-up reminders
# ─────────────────────────────────────────────────────────────────────────────

def cmd_gmail_followup_reminder(text: str = "") -> None:
    """
    Phase 11: Set a follow-up reminder on the last sent email (or current thread).
    Reminds Suneel if no reply arrives by the specified deadline.
    Does NOT send anything automatically.
    """
    import hashlib as _hl11

    # Context priority: last_sent > current_email > current_thread > draft
    ctx_src = None
    thread_id = ""
    to = subject = ""
    tracked_since_ms = int(datetime.now().timestamp() * 1000)

    last_sent = _GMAIL_CTX.get("last_sent")
    cur_email  = _GMAIL_CTX.get("current_email")
    cur_thread = _GMAIL_CTX.get("current_thread")
    draft      = _GMAIL_CTX.get("draft")

    if last_sent and last_sent.get("thread_id"):
        ctx_src = "last_sent"
        thread_id = last_sent["thread_id"]
        to        = last_sent.get("to", "")
        subject   = last_sent.get("subject", "")
        tracked_since_ms = last_sent.get("sent_at_ms", tracked_since_ms)
    elif cur_email and cur_email.get("thread_id"):
        ctx_src = "current_email"
        thread_id = cur_email["thread_id"]
        to        = cur_email.get("from_header", cur_email.get("from", ""))
        subject   = cur_email.get("subject", "")
    elif cur_thread and cur_thread.get("thread_id"):
        ctx_src = "current_thread"
        thread_id = cur_thread["thread_id"]
        to        = cur_thread.get("from_header", "")
        subject   = cur_thread.get("subject", "")
    elif draft:
        ctx_src = "draft"
        thread_id = ""   # draft not yet sent — no thread_id available
        to        = draft.get("to", "")
        subject   = draft.get("subject", "")

    if not thread_id and ctx_src != "draft":
        cprint("  No sent email or open thread in context. Send an email first, or open a thread.", YELLOW)
        return

    # Resolve due time
    dt, label = _resolve_schedule_time(text)
    if dt is None:
        # Default: 3 business days from now
        dt = datetime.now() + timedelta(days=3)
        label = f"{dt.strftime('%A, %B %-d')} at {dt.strftime('%-I:%M %p')} (3 days)"

    due_at_iso  = dt.isoformat(timespec="seconds")
    uid = "fu_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + _hl11.md5(thread_id.encode()).hexdigest()[:4]

    adwi_head("Gmail — Follow-up Reminder")
    cprint(f"  Thread:  {subject[:60] or '(no subject)'}", "")
    cprint(f"  To:      {to[:60] or '(unknown)'}", "")
    cprint(f"  Remind:  {label}", "")
    if not thread_id:
        cprint("  Note: This draft hasn't been sent yet — reminder will fire by date, not reply detection.", YELLOW)
    ans = input(f"  {YELLOW}Set this reminder? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY); return

    entry = {
        "id":                uid,
        "thread_id":         thread_id,
        "to":                to,
        "subject":           subject,
        "tracked_since_ms":  tracked_since_ms,
        "due_at_iso":        due_at_iso,
        "status":            "pending",   # pending | due | satisfied | cancelled
        "created_at_iso":    datetime.now().isoformat(timespec="seconds"),
        "note":              text.strip() or "",
    }
    reminders = _load_followup_reminders()
    reminders.append(entry)
    _save_followup_reminders(reminders)
    _GMAIL_CTX["followup_reminder"] = entry
    cprint(f"  {GREEN}✓ Reminder set — I'll flag this thread if no reply by {label}.{RESET}", "")
    cprint("  Say 'show follow-ups' to review all pending reminders.", GRAY)


def cmd_gmail_list_followups() -> None:
    """Phase 11: List all follow-up reminders with live reply-detection check."""
    reminders = _load_followup_reminders()
    if not reminders:
        cprint("  No follow-up reminders.", GRAY); return

    adwi_head("Gmail — Follow-up Reminders")
    now_iso = datetime.now().isoformat(timespec="seconds")

    # For pending reminders that have a thread_id, do a live reply check
    gh = None
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if token.exists():
        try:
            gh = _gmail()
        except Exception:
            gh = None

    changed = False
    for r in reminders:
        if r.get("status") != "pending":
            continue
        tid = r.get("thread_id", "")
        if gh and tid:
            try:
                check = gh.get_thread_reply_check(tid, r.get("tracked_since_ms", 0))
                if check.get("has_reply"):
                    r["status"] = "satisfied"
                    r["satisfied_at_iso"] = check.get("reply_at_iso", now_iso)
                    r["reply_from"] = check.get("reply_from", "")
                    changed = True
            except Exception:
                pass
        # Mark overdue pending
        if r.get("status") == "pending" and r.get("due_at_iso", "9999") <= now_iso:
            r["status"] = "due"
            changed = True

    if changed:
        _save_followup_reminders(reminders)

    _STATUS_ICONS = {
        "pending":   "⏳",
        "due":       "🔔",
        "satisfied": "✓",
        "cancelled": "✗",
    }
    for i, r in enumerate(reminders, 1):
        status  = r.get("status", "?")
        icon    = _STATUS_ICONS.get(status, "?")
        subject = (r.get("subject") or "(no subject)")[:45]
        due     = (r.get("due_at_iso") or "?")[:16].replace("T", " ")
        to      = (r.get("to") or "")[:30]
        line    = f"  [{i}] {icon} {subject}"
        if to:
            line += f"  →  {to}"
        cprint(line, GREEN if status == "satisfied" else ("" if status == "pending" else YELLOW))
        cprint(f"       due {due}  status: {status}", GRAY)
        if status == "satisfied":
            rf = r.get("reply_from", "")
            ra = (r.get("satisfied_at_iso") or "")[:16].replace("T", " ")
            cprint(f"       replied by {rf} at {ra}", GRAY)
    cprint("", "")
    cprint("  Say 'cancel follow-up' or 'cancel reminder 2' to remove one.", GRAY)


def cmd_gmail_cancel_followup(text: str = "") -> None:
    """Phase 11: Cancel a follow-up reminder by index or most recent."""
    reminders = _load_followup_reminders()
    pending   = [r for r in reminders if r.get("status") in ("pending", "due")]

    adwi_head("Gmail — Cancel Follow-up Reminder")
    if not pending:
        cprint("  No active follow-up reminders to cancel.", GRAY)
        _GMAIL_CTX["followup_reminder"] = None
        return

    target = None
    m = re.search(r"\b([1-9])\b", text)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(pending):
            target = pending[idx]
        else:
            cprint(f"  No active reminder #{m.group(1)}.", YELLOW); return
    elif len(pending) == 1:
        target = pending[0]
    else:
        cprint(f"  {len(pending)} active reminders — say 'cancel reminder 1', 'cancel 2', etc.", YELLOW)
        for i, r in enumerate(pending, 1):
            subj = (r.get("subject") or "(no subject)")[:40]
            due  = (r.get("due_at_iso") or "?")[:16].replace("T", " ")
            cprint(f"  [{i}] {subj}  due {due}", "")
        return

    cprint(f"  Cancelling reminder: '{(target.get('subject') or '')[:50]}'", "")
    ans = input(f"  {YELLOW}Confirm cancel? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Kept.", GRAY); return

    target["status"] = "cancelled"
    _save_followup_reminders(reminders)
    if (_GMAIL_CTX.get("followup_reminder") or {}).get("id") == target["id"]:
        _GMAIL_CTX["followup_reminder"] = None
    cprint(f"  {GREEN}✓ Reminder cancelled.{RESET}", "")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 12 — Multi-draft memory + draft management
# ─────────────────────────────────────────────────────────────────────────────

_DRAFT_ORDINALS: dict = {
    "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
    "sixth": 5, "seventh": 6, "eighth": 7, "ninth": 8, "tenth": 9,
    "1st": 0, "2nd": 1, "3rd": 2, "4th": 3, "5th": 4,
    "last": -1,
}


def _resolve_draft_ref(text: str) -> tuple:
    """
    Find a draft from _GMAIL_CTX["draft_list"] by ordinal or name/keyword.
    Returns (entry_dict, []) if exactly one match,
            (None, [candidates]) if ambiguous (>1 match),
            (None, []) if not found or list is empty.
    """
    dl = _GMAIL_CTX.get("draft_list", [])
    if not dl:
        return None, []

    text_l = text.lower().strip()

    # Try ordinal word
    for word, idx in _DRAFT_ORDINALS.items():
        if re.search(rf"\b{word}\b", text_l):
            real_idx = len(dl) - 1 if idx == -1 else idx
            if 0 <= real_idx < len(dl):
                return dl[real_idx], []
            return None, []

    # Try bare digit: "draft 2", "open 3"
    m = re.search(r"\b([1-9])\b", text_l)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(dl):
            return dl[idx], []
        return None, []

    # Keyword search: strip stop-words, match to/subject
    stop = r"\b(?:the|a|an|my|that|this|old|draft|drafts|send|open|delete|remove|trash|switch|to|go|back|select|load|use)\b"
    kw = re.sub(stop, " ", text_l).strip()
    kw = re.sub(r"\s+", " ", kw).strip()
    if not kw:
        return None, []

    matches = [
        e for e in dl
        if kw in (e.get("to") or "").lower() or kw in (e.get("subject") or "").lower()
    ]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, matches
    return None, []


def _resolve_scheduled_ref(text: str, pending_only: bool = True) -> tuple:
    """
    Phase 13: Find a scheduled-send entry by ordinal or name/keyword.
    Returns (entry, []) if one match, (None, [candidates]) if ambiguous, (None, []) if not found.
    pending_only: if True, only search entries with status='pending'.
    """
    all_entries = _load_scheduled_sends()
    entries = [e for e in all_entries if not pending_only or e.get("status") == "pending"]
    if not entries:
        return None, []

    text_l = text.lower().strip()

    # Ordinal word
    for word, idx in _DRAFT_ORDINALS.items():
        if re.search(rf"\b{word}\b", text_l):
            real_idx = len(entries) - 1 if idx == -1 else idx
            if 0 <= real_idx < len(entries):
                return entries[real_idx], []
            return None, []

    # Bare digit
    m = re.search(r"\b([1-9])\b", text_l)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(entries):
            return entries[idx], []
        return None, []

    # Strip command/time stop-words, match To or Subject
    stop = r"\b(?:the|a|an|my|that|this|scheduled|schedule|reschedule|send|email|message|move|push|delay|postpone|change|cancel|open|reopen|to|for|until|load|switch)\b"
    kw = re.sub(stop, " ", text_l).strip()
    kw = re.sub(r"\s+", " ", kw).strip()

    # Remove time phrases so "to tomorrow" doesn't become the keyword
    time_pat = r"\b(?:tomorrow|tonight|morning|afternoon|evening|eod|noon|am|pm|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next\s+week|in\s+\d+\s+\w+|at\s+\d{1,2})\b"
    kw = re.sub(time_pat, " ", kw).strip()
    kw = re.sub(r"\s+", " ", kw).strip()

    if kw:
        matches = [
            e for e in entries
            if kw in (e.get("to") or "").lower() or kw in (e.get("subject") or "").lower()
        ]
        if len(matches) == 1:
            return matches[0], []
        if len(matches) > 1:
            return None, matches

    # No keyword match — implicit "that" context: return single entry
    if len(entries) == 1:
        return entries[0], []
    return None, []


def _draft_list_row(i: int, e: dict, scheduled_ids: set) -> str:
    """Format one row for the draft list display."""
    to_s   = (e.get("to") or "(no recipient)")[:30]
    subj   = (e.get("subject") or "(no subject)")[:38]
    mode   = "↩ reply" if e.get("mode") == "reply" else "✉ compose"
    att    = " 📎" if e.get("has_attachment") else ""
    sched  = " ⏰" if e.get("draft_id") in scheduled_ids else ""
    return f"  [{i}] {to_s:<30}  {subj:<38}  {mode}{att}{sched}"


def cmd_gmail_list_drafts(text: str = "") -> None:
    """Phase 12: List all Gmail drafts with metadata and scheduled status."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return

    try:
        gh = _gmail()
        drafts = gh.list_drafts(max_results=15)
    except Exception as e:
        cprint(f"  Error fetching drafts: {e}", RED); return

    _GMAIL_CTX["draft_list"] = drafts

    if not drafts:
        cprint("  No drafts found in Gmail.", GRAY); return

    # Cross-reference scheduled sends
    scheduled_ids = {
        e.get("draft_id", "") for e in _load_scheduled_sends()
        if e.get("status") == "pending"
    }

    # Optional filter: "show scheduled drafts" / "show unscheduled drafts"
    text_l = text.lower()
    want_sched   = re.search(r"\bscheduled\b", text_l)
    want_unsched = re.search(r"\bunscheduled\b|\bunsent\b", text_l)
    want_att     = re.search(r"\battach(?:ment|ed)?\b|\bpdf\b|\bfile\b", text_l)

    display = drafts
    filter_label = ""
    if want_sched:
        display = [d for d in drafts if d["draft_id"] in scheduled_ids]
        filter_label = " (scheduled only)"
    elif want_unsched:
        display = [d for d in drafts if d["draft_id"] not in scheduled_ids]
        filter_label = " (unscheduled)"
    elif want_att:
        display = [d for d in drafts if d.get("has_attachment")]
        filter_label = " (with attachment)"

    adwi_head(f"Gmail — Drafts ({len(display)}/{len(drafts)}){filter_label}")
    if not display:
        cprint(f"  No drafts match that filter.", GRAY); return

    for i, e in enumerate(display, 1):
        cprint(_draft_list_row(i, e, scheduled_ids), "")

    cprint("", "")
    cprint("  Say 'open draft 2' · 'send the second draft' · 'delete draft 1' to act.", GRAY)
    if want_att and not display:
        cprint("  Note: attachment detection is based on draft format — may not be 100% accurate.", GRAY)


def cmd_gmail_open_draft(text: str = "") -> None:
    """
    Phase 12: Switch active draft context to a specific draft by ordinal or name.
    If text contains a send verb, confirms and sends after switching.
    """
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return

    # Populate draft_list if empty
    if not _GMAIL_CTX.get("draft_list"):
        try:
            gh = _gmail()
            _GMAIL_CTX["draft_list"] = gh.list_drafts(max_results=15)
        except Exception as e:
            cprint(f"  Error fetching drafts: {e}", RED); return

    dl = _GMAIL_CTX["draft_list"]
    if not dl:
        cprint("  No drafts found in Gmail.", GRAY); return

    entry, ambiguous = _resolve_draft_ref(text)

    if ambiguous:
        adwi_head("Gmail — Open Draft — Disambiguation")
        cprint(f"  Multiple drafts match — which one?", YELLOW)
        scheduled_ids = {e.get("draft_id") for e in _load_scheduled_sends() if e.get("status") == "pending"}
        for i, e in enumerate(ambiguous, 1):
            cprint(_draft_list_row(i, e, scheduled_ids), "")
        cprint("  Say 'open draft 1', 'open the first one', etc.", GRAY)
        return

    if entry is None:
        adwi_head("Gmail — Open Draft")
        cprint(f"  No draft found matching: '{text[:50]}'", YELLOW)
        cprint(f"  {len(dl)} draft(s) available. Say 'show my drafts' to see the list.", GRAY)
        return

    # Fetch full draft content (body, cc, bcc)
    try:
        gh         = _gmail()
        full_draft = gh.get_draft(entry["draft_id"])
    except Exception as e:
        cprint(f"  Error loading draft: {e}", RED); return

    # Merge list metadata into full draft dict
    full_draft["mode"] = entry.get("mode", full_draft.get("mode", "compose"))
    _GMAIL_CTX["draft"] = full_draft

    send_intent = bool(re.search(r"\bsend\b", text.lower()))

    adwi_head("Gmail — Draft Loaded")
    cprint(f"  Switched to: {(entry.get('subject') or '(no subject)')[:55]}", GREEN)
    _gmail_draft_preview(full_draft)

    if send_intent:
        cmd_gmail_send_draft()


def cmd_gmail_delete_draft(text: str = "") -> None:
    """
    Phase 12: Delete a draft by ordinal, name, or (if none specified) the current draft.
    Shows preview + requires confirmation before deleting.
    """
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return

    # Populate draft_list if empty
    if not _GMAIL_CTX.get("draft_list"):
        try:
            gh = _gmail()
            _GMAIL_CTX["draft_list"] = gh.list_drafts(max_results=15)
        except Exception as e:
            cprint(f"  Error fetching drafts: {e}", RED); return

    dl = _GMAIL_CTX["draft_list"]

    # Resolve target: ordinal/name → draft_list; else current draft
    target_meta = None
    entry, ambiguous = _resolve_draft_ref(text)

    if ambiguous:
        adwi_head("Gmail — Delete Draft — Disambiguation")
        cprint("  Multiple drafts match — which one do you want to delete?", YELLOW)
        scheduled_ids = {e.get("draft_id") for e in _load_scheduled_sends() if e.get("status") == "pending"}
        for i, e in enumerate(ambiguous, 1):
            cprint(_draft_list_row(i, e, scheduled_ids), "")
        cprint("  Say 'delete draft 1', 'delete the first one', etc.", GRAY)
        return

    if entry is not None:
        target_meta = entry
    elif _GMAIL_CTX.get("draft"):
        # No reference given — fall through to current draft
        target_meta = _GMAIL_CTX["draft"]
    else:
        adwi_head("Gmail — Delete Draft")
        if dl:
            cprint("  No reference given and no current draft. Say 'delete draft 1' or 'show my drafts'.", YELLOW)
        else:
            cprint("  No drafts found.", GRAY)
        return

    draft_id = target_meta.get("draft_id", "")
    to       = (target_meta.get("to") or "")[:50]
    subject  = (target_meta.get("subject") or "(no subject)")[:50]

    adwi_head("Gmail — Delete Draft")
    cprint(f"  To:      {to}", "")
    cprint(f"  Subject: {subject}", "")
    cprint(f"  Draft ID: {draft_id[:20]}…", GRAY)
    ans = input(f"  {YELLOW}Permanently delete this draft? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled — draft kept.", GRAY); return

    try:
        gh = _gmail()
        gh.delete_draft(draft_id)
        cprint(f"  {GREEN}✓ Draft deleted.{RESET}", "")
    except Exception as e:
        cprint(f"  Error deleting draft: {e}", RED); return

    # Clear from draft_list
    _GMAIL_CTX["draft_list"] = [d for d in dl if d.get("draft_id") != draft_id]
    # Clear current draft if it was the one deleted
    cur = _GMAIL_CTX.get("draft") or {}
    if cur.get("draft_id") == draft_id:
        _GMAIL_CTX["draft"] = None


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
        _GMAIL_CTX["current_email"] = em
        adwi_head(f"Email: {em['subject']}")
        cprint(f"  From: {em['from']}", CYAN)
        cprint(f"  Date: {em['date']}", GRAY)
        print()
        print(em["body"][:3000])
        if len(em["body"]) > 3000:
            cprint(f"\n  … (truncated — full email is longer)", GRAY)
        print(f"\n  {GRAY}Follow-ups: /gmail-thread · /gmail-summarize{RESET}")
    except Exception as e:
        cprint(f"  Error reading email: {e}", RED)

def cmd_gmail_open(query: str) -> None:
    """Search for emails matching query and open the most recent match."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return
    if not query.strip():
        cmd_gmail_read("1"); return
    try:
        gh = _gmail()
        emails = gh.list_emails(max_results=5, query=query)
        if not emails:
            cprint(f"  No emails found for: {query}", YELLOW); return
        _GMAIL_IDS.clear();     _GMAIL_IDS.extend(e["id"] for e in emails)
        _GMAIL_SUBJECTS.clear(); _GMAIL_SUBJECTS.extend(e["subject"] for e in emails)
        _GMAIL_CTX["thread_ids"] = [e.get("thread_id", "") for e in emails]
        if len(emails) > 1:
            cprint(f"  Found {len(emails)} matches — opening most recent", GRAY)
        em = gh.read_email(emails[0]["id"])
        _GMAIL_CTX["current_email"] = em
        adwi_head(f"Email: {em['subject']}")
        cprint(f"  From: {em['from']}", CYAN)
        cprint(f"  Date: {em['date']}", GRAY)
        print()
        print(em["body"][:3000])
        if len(em["body"]) > 3000:
            cprint(f"\n  … (truncated)", GRAY)
        if len(emails) > 1:
            print(f"\n  {GRAY}{len(emails)-1} more match(es) · /gmail-thread for conversation · /gmail-summarize{RESET}")
        else:
            print(f"\n  {GRAY}Follow-ups: /gmail-thread · /gmail-summarize{RESET}")
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)


def _display_thread(thread: dict) -> None:
    """Render a thread with condensed per-message display."""
    adwi_head(f"Thread ({thread['count']} messages): {thread['subject'][:55]}")
    for i, msg in enumerate(thread["messages"], 1):
        sender = msg["from"].split("<")[0].strip()[:35]
        cprint(f"\n  {'─'*58}", GRAY)
        cprint(f"  {i}. {BOLD}{sender}{RESET}  {GRAY}{msg['date'][:16]}{RESET}", "")
        print()
        for line in msg["body"][:500].splitlines()[:12]:
            print(f"     {line}")
        if len(msg["body"]) > 500:
            cprint(f"     … (truncated)", GRAY)
    cprint(f"\n  {'─'*58}", GRAY)
    print(f"  {GRAY}/gmail-summarize  to summarize this thread{RESET}")


def cmd_gmail_thread(query: str = "") -> None:
    """Load and display the full thread for the current email or a search query."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return
    try:
        gh = _gmail()
        thread_id = None

        if query.strip():
            emails = gh.list_emails(max_results=3, query=query)
            if emails:
                thread_id = emails[0].get("thread_id")
                if not thread_id:
                    em = gh.read_email(emails[0]["id"])
                    thread_id = em.get("thread_id")
            if not thread_id:
                cprint(f"  No emails found for: {query}", YELLOW); return
        elif _GMAIL_CTX.get("current_email"):
            thread_id = _GMAIL_CTX["current_email"].get("thread_id")
        elif _GMAIL_CTX.get("current_thread"):
            _display_thread(_GMAIL_CTX["current_thread"]); return
        elif _GMAIL_IDS:
            em = gh.read_email(_GMAIL_IDS[0])
            _GMAIL_CTX["current_email"] = em
            thread_id = em.get("thread_id")

        if not thread_id:
            cprint("  No thread context. Open an email first, or specify a search query.", YELLOW); return

        thread = gh.get_thread(thread_id)
        _GMAIL_CTX["current_thread"] = thread
        _display_thread(thread)
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)


# ── Gmail Phase 17: extract tasks ────────────────────────────────────────────

def _extract_email_tasks(body: str, subject: str = "", mode: str = "full") -> dict:
    """
    LLM-based structured extraction from email/thread content.
    mode: "full" | "action_items" | "deadlines" | "decisions" | "asks"
    Returns {action_items, deadlines [{item,date_str},...], decisions, asks, source_subject, mode}
    """
    prompt_parts = {
        "full": (
            "Extract ONLY items clearly present. Be conservative and never invent:\n"
            "1. ACTION ITEMS: specific tasks for Suneel (start each with a verb)\n"
            "2. DEADLINES: items with explicit due dates or timeframes\n"
            "3. DECISIONS: decisions made or agreed upon\n"
            "4. ASKS: direct requests or questions directed at Suneel\n\n"
            "Use EXACTLY this format (omit empty sections, write 'None found.' for absent):\n"
            "ACTION ITEMS:\n- item\n\nDEADLINES:\n- item | due: date\n\n"
            "DECISIONS:\n- item\n\nASKS:\n- item"
        ),
        "action_items": (
            "List ONLY specific action items or tasks for Suneel. Start each with a verb.\n"
            "Respond with a bullet list (- item) or 'None found.'"
        ),
        "deadlines": (
            "List ONLY deadlines, due dates, or timeframes mentioned.\n"
            "Format each as: - task description | due: date/time\n"
            "Respond with a bullet list or 'None found.'"
        ),
        "decisions": (
            "List ONLY decisions that were made or agreed upon.\n"
            "Respond with a bullet list (- item) or 'None found.'"
        ),
        "asks": (
            "List ONLY direct requests, questions, or asks directed at Suneel.\n"
            "Respond with a bullet list (- item) or 'None found.'"
        ),
    }
    prompt_text = prompt_parts.get(mode, prompt_parts["full"])
    full_prompt = f"Subject: {subject}\n\nContent:\n{body[:3000]}\n\n{prompt_text}"
    raw = _ollama(
        full_prompt,
        system=(
            "You are a precise email analyst. Extract only what is explicitly present "
            "in the text. Never invent items that are not clearly stated."
        ),
        timeout=35,
    )
    return _parse_task_extraction(raw, mode, subject)


def _parse_task_extraction(raw: str, mode: str, subject: str) -> dict:
    """Parse LLM extraction output into structured dict."""
    def _section_items(text: str, header: str) -> list:
        m = re.search(rf"{header}:\s*\n((?:[ \t]*[-*]\s*.+\n?)*)", text, re.IGNORECASE)
        if not m:
            return []
        items = []
        for line in m.group(1).splitlines():
            item = line.strip().lstrip("-* ").strip()
            if item and item.lower() not in ("none", "none found.", "none found", "n/a"):
                items.append(item)
        return items

    def _parse_deadlines(raw_list: list) -> list:
        result = []
        for dl in raw_list:
            if " | due:" in dl.lower():
                parts = dl.split("|", 1)
                result.append({
                    "item":     parts[0].strip(),
                    "date_str": parts[1].replace("due:", "").replace("Due:", "").strip(),
                })
            else:
                result.append({"item": dl, "date_str": ""})
        return result

    if mode == "full":
        action_items = _section_items(raw, "ACTION ITEMS")
        decisions    = _section_items(raw, "DECISIONS")
        asks         = _section_items(raw, "ASKS")
        deadlines    = _parse_deadlines(_section_items(raw, "DEADLINES"))
    elif mode == "action_items":
        action_items = [l.strip().lstrip("-* ").strip() for l in raw.splitlines() if l.strip().startswith(("-", "*"))]
        deadlines = decisions = asks = []
    elif mode == "deadlines":
        deadlines    = _parse_deadlines([l.strip().lstrip("-* ").strip() for l in raw.splitlines() if l.strip().startswith(("-", "*"))])
        action_items = decisions = asks = []
    elif mode == "decisions":
        decisions    = [l.strip().lstrip("-* ").strip() for l in raw.splitlines() if l.strip().startswith(("-", "*"))]
        action_items = deadlines = asks = []
    elif mode == "asks":
        asks         = [l.strip().lstrip("-* ").strip() for l in raw.splitlines() if l.strip().startswith(("-", "*"))]
        action_items = decisions = deadlines = []
    else:
        action_items = decisions = asks = []
        deadlines = []

    _noise = {"none", "none found", "none found.", "n/a", "-"}
    action_items = [i for i in action_items if len(i) > 3 and i.lower() not in _noise]
    decisions    = [i for i in decisions    if len(i) > 3 and i.lower() not in _noise]
    asks         = [i for i in asks         if len(i) > 3 and i.lower() not in _noise]
    deadlines    = [d for d in deadlines    if len(d.get("item", "")) > 3 and d["item"].lower() not in _noise]

    return {
        "action_items":   action_items,
        "deadlines":      deadlines,
        "decisions":      decisions,
        "asks":           asks,
        "source_subject": subject,
        "mode":           mode,
    }


def _task_list_preview(result: dict) -> None:
    """Render extracted tasks/deadlines/decisions preview box."""
    W       = 60
    subject = (result.get("source_subject") or "")[:50]
    ai      = result.get("action_items", [])
    dl      = result.get("deadlines",    [])
    dec     = result.get("decisions",    [])
    asks    = result.get("asks",         [])
    total   = len(ai) + len(dl) + len(dec) + len(asks)

    cprint(f"  {'─' * W}", GRAY)
    cprint(f"  FROM: {subject or '(current email/thread)'}", BOLD)
    if ai:
        cprint(f"\n  ACTION ITEMS ({len(ai)})", CYAN)
        for i, item in enumerate(ai, 1):
            cprint(f"    {i}. {item[:W - 6]}", "")
    if dl:
        cprint(f"\n  DEADLINES ({len(dl)})", YELLOW)
        for i, d in enumerate(dl, 1):
            date_part = f" — {d['date_str']}" if d.get("date_str") else ""
            cprint(f"    {i}. {d['item'][:W - 20]}{date_part}", "")
    if dec:
        cprint(f"\n  DECISIONS ({len(dec)})", GREEN)
        for i, item in enumerate(dec, 1):
            cprint(f"    {i}. {item[:W - 6]}", "")
    if asks:
        cprint(f"\n  ASKS ({len(asks)})", "")
        for i, item in enumerate(asks, 1):
            cprint(f"    {i}. {item[:W - 6]}", "")
    if total == 0:
        cprint("  (No items found — try 'show the thread' first, then ask again.)", GRAY)
    cprint(f"\n  {'─' * W}", GRAY)
    hints = []
    if ai or asks:
        hints.append("'save to Obsidian' / 'add to my list'")
    if dl:
        hints.append("'create reminders for those'")
    if hints:
        cprint(f"  {GRAY}Next: {' or '.join(hints)}{RESET}", "")


def cmd_gmail_extract_tasks(text: str = "") -> None:
    """Phase 17: Extract action items, deadlines, decisions, asks from current email/thread."""
    tl   = text.lower()
    mode = "full"
    if   re.search(r"\bdeadlines?\b|\bdue\s+dates?\b", tl) and not re.search(r"\baction\s+items?\b|\bdecisions?\b|\basks?\b", tl):
        mode = "deadlines"
    elif re.search(r"\bdecisions?\b", tl) and not re.search(r"\baction\s+items?\b|\bdeadlines?\b|\basks?\b", tl):
        mode = "decisions"
    elif re.search(r"\basks?\b|\bwhat\s+am\s+I\s+being\s+asked\b", tl) and not re.search(r"\baction\s+items?\b|\bdeadlines?\b|\bdecisions?\b", tl):
        mode = "asks"
    elif re.search(r"\baction\s+items?\b|\btasks?\b|\bchecklist\b|\btodo\b", tl) and not re.search(r"\bdeadlines?\b|\bdecisions?\b", tl):
        mode = "action_items"

    thread = _GMAIL_CTX.get("current_thread")
    email  = _GMAIL_CTX.get("current_email")

    if thread and thread.get("messages"):
        subject = thread.get("subject", "")
        body    = _thread_build_context(thread, max_chars=3000)
        source  = f"thread ({thread.get('count', 1)} msg)"
    elif email:
        subject = email.get("subject", "")
        body    = email.get("body", "")[:3000]
        source  = "email"
    else:
        cprint("  No email or thread in context. Open an email or thread first.", YELLOW)
        return

    adwi_head(f"Gmail — Extract Tasks ({mode})")
    cprint(f"  {GRAY}Analyzing {source}: {subject[:55]}…{RESET}")
    result = _extract_email_tasks(body, subject=subject, mode=mode)
    _GMAIL_CTX["pending_tasks"] = result
    _task_list_preview(result)


def cmd_gmail_tasks_save(text: str = "") -> None:
    """Phase 17: Save extracted tasks/checklist to Obsidian daily note."""
    result = _GMAIL_CTX.get("pending_tasks")
    if not result:
        cprint("  No extracted tasks in context. Say 'extract action items' or 'turn this email into tasks' first.", YELLOW)
        return

    subject = result.get("source_subject") or "email"
    ai      = result.get("action_items", [])
    dl      = result.get("deadlines",    [])
    dec     = result.get("decisions",    [])
    asks    = result.get("asks",         [])
    total   = len(ai) + len(dl) + len(dec) + len(asks)

    if total == 0:
        cprint("  Extracted list is empty — nothing to save.", YELLOW); return

    lines = [f"### Tasks from: {subject}"]
    if ai:
        lines.append("\n**Action Items**")
        for item in ai:
            lines.append(f"- [ ] {item}")
    if dl:
        lines.append("\n**Deadlines**")
        for d in dl:
            date_part = f" (due: {d['date_str']})" if d.get("date_str") else ""
            lines.append(f"- [ ] {d['item']}{date_part}")
    if dec:
        lines.append("\n**Decisions**")
        for item in dec:
            lines.append(f"- {item}")
    if asks:
        lines.append("\n**Asks**")
        for item in asks:
            lines.append(f"- [ ] {item}")

    adwi_head("Gmail — Save Tasks to Obsidian Daily Note")
    cprint(f"  {total} item(s) to append:\n", "")
    for ln in lines:
        cprint(f"  {GRAY}{ln}{RESET}", "")
    ans = input(f"\n  {YELLOW}Append to today's Obsidian daily note? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY); return

    content    = "\n".join(lines)
    obs_result = _obsidian_api("POST", "/daily-note", {"content": f"\n{content}\n"})
    if "error" in obs_result:
        cprint(f"  ✗ {obs_result['error']}", RED)
        cprint("  (Is the Obsidian Bridge running? Try: bin/start-obsidian-bridge)", GRAY)
    else:
        cprint(f"  {GREEN}✓ {total} item(s) saved → {obs_result.get('daily_note', 'daily note')}{RESET}", "")
        _GMAIL_CTX["pending_tasks"] = None


def cmd_gmail_tasks_remind(text: str = "") -> None:
    """Phase 17: Create follow-up reminders from extracted task deadlines / action items."""
    import hashlib as _hl17
    result = _GMAIL_CTX.get("pending_tasks")
    if not result:
        cprint("  No extracted tasks in context. Say 'extract deadlines' or 'extract action items' first.", YELLOW)
        return

    dl = result.get("deadlines",    [])
    ai = result.get("action_items", [])

    if not dl and not ai:
        cprint("  No action items or deadlines found to create reminders from.", YELLOW); return

    items_to_remind = dl if dl else [{"item": a, "date_str": ""} for a in ai[:5]]

    thread    = _GMAIL_CTX.get("current_thread")
    email     = _GMAIL_CTX.get("current_email")
    thread_id = (thread or {}).get("thread_id") or (email or {}).get("thread_id") or ""
    subject   = result.get("source_subject", "")

    adwi_head("Gmail — Create Reminders from Tasks")
    cprint(f"  {len(items_to_remind)} reminder(s) to create:\n", "")
    for i, d in enumerate(items_to_remind, 1):
        date_part = f" — due: {d['date_str']}" if d.get("date_str") else " — default: 3 days"
        cprint(f"  {i}. {d['item'][:55]}{date_part}", GRAY)

    ans = input(f"\n  {YELLOW}Create these reminders? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled.", GRAY); return

    reminders = _load_followup_reminders()
    now       = datetime.now()
    created   = 0

    for idx, d in enumerate(items_to_remind):
        due_dt = None
        ds     = (d.get("date_str") or "").lower()
        if ds:
            try:
                if "tomorrow"    in ds: due_dt = now + timedelta(days=1)
                elif "today"     in ds or "eod" in ds:
                    due_dt = now.replace(hour=17, minute=0, second=0, microsecond=0)
                elif "next week" in ds: due_dt = now + timedelta(days=7)
                elif "friday"    in ds:
                    ahead = (4 - now.weekday()) % 7 or 7
                    due_dt = now + timedelta(days=ahead)
                elif "monday"    in ds:
                    ahead = (0 - now.weekday()) % 7 or 7
                    due_dt = now + timedelta(days=ahead)
                elif re.search(r"\d{1,2}/\d{1,2}", ds):
                    m_ = re.search(r"(\d{1,2})/(\d{1,2})", ds)
                    mo, da = int(m_.group(1)), int(m_.group(2))
                    due_dt = now.replace(month=mo, day=da, hour=9, minute=0, second=0, microsecond=0)
                    if due_dt < now:
                        due_dt = due_dt.replace(year=now.year + 1)
            except Exception:
                pass
        if due_dt is None:
            due_dt = now + timedelta(days=3)

        uid = f"fu_{now.strftime('%Y%m%d_%H%M%S')}_{_hl17.md5(d['item'].encode()).hexdigest()[:4]}_{idx}"
        reminders.append({
            "id":               uid,
            "thread_id":        thread_id,
            "to":               "",
            "subject":          f"[Task] {d['item'][:80]}",
            "tracked_since_ms": int(now.timestamp() * 1000),
            "due_at_iso":       due_dt.isoformat(timespec="seconds"),
            "status":           "pending",
            "created_at_iso":   now.isoformat(timespec="seconds"),
            "note":             f"From email: {subject[:60]}",
        })
        created += 1

    _save_followup_reminders(reminders)
    cprint(f"  {GREEN}✓ {created} reminder(s) created. Say 'show follow-ups' to review.{RESET}", "")
    _GMAIL_CTX["pending_tasks"] = None


# ── Gmail Phase 16: filter / rule builder ────────────────────────────────────

def _extract_sender_email(from_str: str) -> str:
    """Extract bare email address from 'Name <email>' or bare email string."""
    m = re.search(r"<([^>]+)>", from_str)
    return m.group(1).strip() if m else from_str.strip()


def _load_gmail_rules() -> list:
    if GMAIL_RULES_FILE.exists():
        try:
            return json.loads(GMAIL_RULES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_gmail_rules(rules: list) -> None:
    GMAIL_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = GMAIL_RULES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(GMAIL_RULES_FILE)


def _parse_filter_rule(text: str) -> dict:
    """Parse natural-language input into a structured candidate filter rule."""
    rule: dict = {
        "criteria": {"from_": "", "to": "", "subject": "", "query": ""},
        "actions":  {"label": "", "archive": False, "mark_read": False, "star": False},
        "description": "",
        "status": "pending",
    }

    # ── Action extraction ────────────────────────────────────────────────────
    # FIX-STRESS-010b: added "label X as Y" pattern (first) so lowercase labels are captured
    # before the greedy uppercase-at-EOL pattern or the bare first-word fallback
    label_m = (
        re.search(r'\blabel\b.{0,40}\bas\s+["\']?([A-Za-z][A-Za-z0-9_-]{1,25})["\']?\b', text, re.I)
        or re.search(r"\blabel\b.{1,30}\b([A-Z][A-Za-z0-9_-]{1,25})\s*$", text)
        or re.search(r'\blabel\s+(?:as\s+|it\s+)?["\']?([A-Za-z][A-Za-z0-9_-]{1,25})["\']?\b', text, re.I)
        or re.search(r'\bapply\s+label\s+["\']?([A-Za-z][A-Za-z0-9_-]{1,25})["\']?\b', text, re.I)
    )
    if label_m:
        rule["actions"]["label"] = label_m.group(1).strip("\"' ")
    if re.search(r"\barchive\b|\bskip\s+inbox\b|\bnot\s+in\s+inbox\b", text, re.I):
        rule["actions"]["archive"] = True
    # FIX-STRESS-010: extended span to 30 chars to handle "mark newsletters as read"
    if re.search(r"\bmark\b.{0,30}(?:as\s+)?read\b|\bmark\s+read\b", text, re.I):
        rule["actions"]["mark_read"] = True
    if re.search(r"\bstar\b.{0,10}\b(?:it|them|message|email|emails)?\b|\bmark\s+(?:as\s+)?important\b", text, re.I):
        rule["actions"]["star"] = True

    # ── Criteria extraction ──────────────────────────────────────────────────
    em = _GMAIL_CTX.get("current_email")

    if re.search(r"\bfrom\s+this\s+sender\b|\bthis\s+sender\b|\bsame\s+sender\b", text, re.I):
        if em:
            rule["criteria"]["from_"] = _extract_sender_email(em.get("from", ""))
    elif sender_m := re.search(r"\bfrom\s+([\w.@+-]+(?:\.(?:com|io|org|net|co|app|ai|dev))?)\b", text, re.I):
        rule["criteria"]["from_"] = sender_m.group(1).strip()

    # Well-known sender shorthands
    if re.search(r"\bgithub\b.{0,20}\bnotifications?\b|\bnotifications?\b.{0,20}\bgithub\b", text, re.I):
        rule["criteria"]["from_"] = "notifications@github.com"
    elif re.search(r"\bamazon\b", text, re.I) and not rule["criteria"]["from_"]:
        rule["criteria"]["from_"] = "@amazon.com"

    # Subject keywords → criteria + sensible action default
    if re.search(r"\binvoices?\b", text, re.I):
        rule["criteria"]["subject"] = "invoice"
        if not rule["actions"]["label"] and not rule["actions"]["archive"]:
            rule["actions"]["label"] = "Finance"
    elif re.search(r"\breceipts?\b", text, re.I):
        rule["criteria"]["subject"] = "receipt"
        if not rule["actions"]["label"] and not rule["actions"]["archive"]:
            rule["actions"]["label"] = "Finance"

    # Category keywords → query + sensible action default
    if re.search(r"\bnewsletters?\b|\bpromotions?\b|\bpromotional\b", text, re.I):
        rule["criteria"]["query"] = "category:promotions"
        if not rule["actions"]["label"] and not rule["actions"]["archive"]:
            rule["actions"]["archive"] = True
    elif re.search(r"\bnotifications?\b", text, re.I) and not rule["criteria"]["from_"]:
        rule["criteria"]["query"] = "category:updates"

    # "these/this emails" → use current email sender as criterion
    if re.search(r"\b(?:these|this)\b.{0,15}\b(?:emails?|messages?|mails?)\b", text, re.I) and em:
        if not rule["criteria"]["from_"]:
            rule["criteria"]["from_"] = _extract_sender_email(em.get("from", ""))

    # ── Description ─────────────────────────────────────────────────────────
    crit_parts: list[str] = []
    if rule["criteria"]["from_"]:   crit_parts.append(f"from '{rule['criteria']['from_']}'")
    if rule["criteria"]["to"]:      crit_parts.append(f"to '{rule['criteria']['to']}'")
    if rule["criteria"]["subject"]: crit_parts.append(f"subject contains '{rule['criteria']['subject']}'")
    if rule["criteria"]["query"]:   crit_parts.append(f"matching {rule['criteria']['query']}")

    act_parts: list[str] = []
    if rule["actions"]["label"]:     act_parts.append(f"label '{rule['actions']['label']}'")
    if rule["actions"]["archive"]:   act_parts.append("skip inbox")
    if rule["actions"]["mark_read"]: act_parts.append("mark as read")
    if rule["actions"]["star"]:      act_parts.append("star")

    crit_str = " and ".join(crit_parts) if crit_parts else "any email"
    act_str  = ", ".join(act_parts) if act_parts else "⚠ no action set"
    rule["description"] = f"When {crit_str}: {act_str}"
    return rule


def _filter_criteria_to_query(criteria: dict) -> str:
    """Convert rule criteria dict to a Gmail search query string."""
    parts: list[str] = []
    if criteria.get("from_"):    parts.append(f"from:{criteria['from_']}")
    if criteria.get("to"):       parts.append(f"to:{criteria['to']}")
    if criteria.get("subject"):  parts.append(f"subject:{criteria['subject']}")
    if criteria.get("query"):    parts.append(criteria["query"])
    return " ".join(parts)


def _filter_preview(rule: dict) -> None:
    """Render a structured filter rule preview box."""
    W = 62
    crit = rule.get("criteria", {})
    acts = rule.get("actions", {})
    cprint(f"\n  ┌{'─'*W}┐", GRAY)
    cprint(f"  │  {BOLD}Gmail Rule Preview{RESET}{'':>{W-20}}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    cprint(f"  │  {CYAN}MATCH CRITERIA:{RESET}{'':>{W-18}}│")
    if crit.get("from_"):
        cprint(f"  │    From:    {crit['from_'][:W-14]:<{W-14}}│")
    if crit.get("subject"):
        subj_line = f"contains '{crit['subject']}'"
        cprint(f"  │    Subject: {subj_line[:W-14]:<{W-14}}│")
    if crit.get("query"):
        cprint(f"  │    Query:   {crit['query'][:W-14]:<{W-14}}│")
    if not any(crit.get(k) for k in ("from_", "to", "subject", "query")):
        cprint(f"  │    {YELLOW}(all incoming email — refine before creating){RESET}{'':>{W-47}}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    cprint(f"  │  {CYAN}ACTIONS:{RESET}{'':>{W-11}}│")
    if acts.get("label"):
        cprint(f"  │    ✓ Apply label: {acts['label'][:W-20]:<{W-20}}│")
    if acts.get("archive"):
        cprint(f"  │    ✓ Skip inbox (archive){'':>{W-28}}│")
    if acts.get("mark_read"):
        cprint(f"  │    ✓ Mark as read{'':>{W-20}}│")
    if acts.get("star"):
        cprint(f"  │    ✓ Star the message{'':>{W-24}}│")
    if not any(acts.get(k) for k in ("label", "archive", "mark_read", "star")):
        cprint(f"  │    {YELLOW}⚠ No action — say 'archive' or 'label Finance'{RESET}{'':>{W-49}}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    hint = "Say 'create that rule' to apply  ·  'cancel' to discard"
    cprint(f"  │  {YELLOW}{hint:<{W-2}}{RESET}│")
    cprint(f"  └{'─'*W}┘\n", GRAY)


def cmd_gmail_filter_build(text: str = "") -> None:
    """Parse natural-language input into a Gmail filter rule and show a preview."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return

    adwi_head("Gmail — Rule Builder")
    rule = _parse_filter_rule(text)

    has_criteria = any(rule["criteria"].get(k) for k in ("from_", "to", "subject", "query"))
    has_action   = any(rule["actions"].get(k) for k in ("label", "archive", "mark_read", "star"))

    if not has_criteria and not has_action:
        cprint("  Could not extract criteria or action from that.", YELLOW)
        cprint("  Try:", GRAY)
        cprint("    'always label invoices Finance'", GRAY)
        cprint("    'archive newsletters from this sender'", GRAY)
        cprint("    'mark GitHub notifications as read'", GRAY)
        cprint("    'create a rule for Amazon receipts'", GRAY)
        return

    _GMAIL_CTX["pending_rule"] = rule
    _filter_preview(rule)


def cmd_gmail_filter_apply(text: str = "") -> None:
    """Confirm and apply the pending Gmail filter rule."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return

    rule = _GMAIL_CTX.get("pending_rule")
    if not rule or rule.get("status") != "pending":
        cprint("  No pending rule. Build one first — e.g. 'always label invoices Finance'.", YELLOW)
        return

    has_action = any(rule["actions"].get(k) for k in ("label", "archive", "mark_read", "star"))
    if not has_action:
        cprint("  This rule has no action. Say 'archive' or 'label Finance' first.", YELLOW)
        _filter_preview(rule); return

    adwi_head("Gmail — Applying Rule")
    cprint(f"  {rule['description']}", GRAY)
    print()

    try:
        gh = _gmail()
        label_id = ""

        # Step 1: create/find label
        if rule["actions"]["label"]:
            cprint(f"  {GRAY}Creating/finding label '{rule['actions']['label']}'…{RESET}")
            label_id = gh.get_or_create_label(rule["actions"]["label"])
            cprint(f"  {GREEN}✓ Label ready: '{rule['actions']['label']}'{RESET}")

        # Step 2: backfill — apply to existing matching emails
        query = _filter_criteria_to_query(rule["criteria"])
        applied_count = 0
        if query:
            cprint(f"  {GRAY}Searching existing emails: {query[:60]}{RESET}")
            applied_count = gh.apply_rule_to_existing(
                query     = query,
                label_id  = label_id,
                archive   = rule["actions"]["archive"],
                mark_read = rule["actions"]["mark_read"],
                star      = rule["actions"]["star"],
            )
            if applied_count:
                cprint(f"  {GREEN}✓ Applied to {applied_count} existing email(s){RESET}")
            else:
                cprint(f"  {GRAY}No existing emails matched the criteria.{RESET}")

        # Step 3: attempt persistent Gmail native filter
        cprint(f"  {GRAY}Attempting persistent Gmail filter…{RESET}")
        filter_result = gh.create_filter_native(
            from_     = rule["criteria"].get("from_", ""),
            subject   = rule["criteria"].get("subject", ""),
            query     = rule["criteria"].get("query", ""),
            label_id  = label_id,
            archive   = rule["actions"]["archive"],
            mark_read = rule["actions"]["mark_read"],
        )
        gmail_filter_id = None
        if filter_result:
            gmail_filter_id = filter_result.get("filter_id")
            cprint(f"  {GREEN}✓ Gmail native filter created (ID: {gmail_filter_id}){RESET}")
        else:
            cprint(f"  {YELLOW}⚠ Persistent filter not created — needs gmail.settings.basic scope.{RESET}")
            cprint(f"  {GRAY}  To enable: add 'https://www.googleapis.com/auth/gmail.settings.basic'{RESET}")
            cprint(f"  {GRAY}  to SCOPES in adwi/gmail_helper.py, then run /gmail-auth.{RESET}")

        # Step 4: save locally
        from datetime import datetime
        rules = _load_gmail_rules()
        rules.append({
            "id":              f"rule_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "created_at":      datetime.now().isoformat(timespec="seconds"),
            "criteria":        rule["criteria"],
            "actions":         rule["actions"],
            "description":     rule["description"],
            "label_id":        label_id,
            "gmail_filter_id": gmail_filter_id,
            "applied_count":   applied_count,
        })
        _save_gmail_rules(rules)
        cprint(f"\n  {GREEN}✓ Rule saved locally ({len(rules)} total){RESET}")

        rule["status"] = "applied"
        _GMAIL_CTX["pending_rule"] = None

    except Exception as e:
        cprint(f"  Error applying rule: {e}", RED)


def cmd_gmail_filter_cancel(text: str = "") -> None:
    """Cancel the pending Gmail filter rule."""
    if _GMAIL_CTX.get("pending_rule"):
        _GMAIL_CTX["pending_rule"] = None
        cprint("  Rule creation cancelled.", GRAY)
    else:
        cprint("  No pending rule to cancel.", GRAY)


def cmd_gmail_filter_list(text: str = "") -> None:
    """List locally saved Gmail rules."""
    adwi_head("Gmail — Saved Rules")
    rules = _load_gmail_rules()
    if not rules:
        cprint("  No rules saved yet.", GRAY)
        cprint("  Try: 'always label invoices Finance'", GRAY)
        return
    for i, r in enumerate(rules, 1):
        created = r.get("created_at", "")[:10]
        has_nat = " 🔗 persistent" if r.get("gmail_filter_id") else ""
        applied = r.get("applied_count", 0)
        cprint(f"  {i:>2}. {BOLD}{r.get('description','')[:72]}{RESET}{has_nat}")
        cprint(f"      {GRAY}Created: {created}  |  Applied to: {applied} email(s){RESET}")
        print()
    cprint(f"  {GRAY}Total: {len(rules)} rule(s){RESET}")


# ── Gmail Phase 15: thread helpers ───────────────────────────────────────────

def _thread_latest_message(thread: dict) -> dict | None:
    """Return the last message in a thread dict, or None if empty."""
    msgs = thread.get("messages", [])
    return msgs[-1] if msgs else None


def _thread_build_context(thread: dict, max_chars: int = 3000) -> str:
    """Assemble a condensed thread string (most-recent-first with budget) for LLM prompts."""
    msgs = thread.get("messages", [])
    if not msgs:
        return ""
    parts: list[str] = []
    budget = max_chars
    for msg in reversed(msgs):
        block = (
            f"From: {msg.get('from', '')}\n"
            f"Date: {msg.get('date', '')}\n\n"
            f"{msg.get('body', '')}"
        )
        if budget <= 0:
            parts.append("[earlier messages omitted]")
            break
        parts.append(block[:budget])
        budget -= len(block)
    parts.reverse()
    return "\n\n---\n\n".join(parts)


def cmd_gmail_thread_intel(text: str = "") -> None:
    """Thread intelligence: extract action items, decisions, reply-needed, latest delta."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return

    thread = _GMAIL_CTX.get("current_thread")
    if not thread:
        em = _GMAIL_CTX.get("current_email")
        if em and em.get("thread_id"):
            try:
                gh = _gmail()
                thread = gh.get_thread(em["thread_id"])
                _GMAIL_CTX["current_thread"] = thread
            except Exception as e:
                cprint(f"  Gmail error: {e}", RED); return
        else:
            cprint("  No thread context. Open an email thread first.", YELLOW); return

    if not thread.get("messages"):
        cprint("  Thread has no messages.", YELLOW); return

    text_l = text.lower()
    if re.search(r"\baction\s+items?\b|\bto.?dos?\b|\btasks?\b", text_l):
        mode, label = "action_items", "Action Items"
    elif re.search(r"\bdecisions?\b|\bagreed?\b|\bresolved?\b|\bconclusions?\b", text_l):
        mode, label = "decisions", "Decisions"
    elif re.search(r"\bquestions?\s+(?:waiting|outstanding|for\s+me|pending)\b|\bwaiting\s+on\s+me\b", text_l):
        mode, label = "questions", "Open Questions"
    elif re.search(r"\b(?:do\s+I\s+owe|should\s+I\s+reply|is\s+a\s+reply\s+needed|reply\s+needed|need\s+to\s+respond)\b", text_l):
        mode, label = "reply_needed", "Reply Analysis"
    elif re.search(r"\bwhat\s+changed\b|\blatest\s+(?:reply|message|update|delta)\b|\blast\s+(?:reply|message|update)\b|\bsummarize\b.{0,20}\blatest\b", text_l):
        mode, label = "latest_delta", "Latest Update"
    else:
        mode, label = "summary", "Thread Intelligence"

    adwi_head(f"Gmail — {label}: {thread['subject'][:45]}")
    subject = thread["subject"]
    count   = thread["count"]
    thread_ctx = _thread_build_context(thread)

    if mode == "latest_delta":
        latest = _thread_latest_message(thread)
        if not latest:
            cprint("  Thread is empty.", YELLOW); return
        prompt = (
            f"Thread subject: {subject} ({count} messages)\n\n"
            f"Latest message:\nFrom: {latest.get('from','')}\nDate: {latest.get('date','')}\n\n"
            f"{latest.get('body','')[:1500]}\n\n"
            "Summarize what changed or was added in this latest message. "
            "What is new compared to what came before? Be specific and concise (3-5 sentences)."
        )
    elif mode == "reply_needed":
        latest = _thread_latest_message(thread)
        last_from = (latest.get("from", "") if latest else "").lower()
        last_is_mine = "suneel" in last_from or "suneeluhcl" in last_from
        extra = "\nNote: the last message appears to be FROM Suneel." if last_is_mine else ""
        prompt = (
            f"Thread subject: {subject} ({count} messages)\n\n"
            f"Thread:\n{thread_ctx}\n\n"
            "Determine if Suneel owes a reply. Consider:\n"
            "- Was the last message sent BY Suneel or TO Suneel?\n"
            "- Are there unanswered questions directed at Suneel?\n"
            "- Is the thread concluded or still open?\n"
            f"Answer YES (reply needed) or NO (no reply needed), then explain in 2-3 sentences.{extra}"
        )
    elif mode == "action_items":
        prompt = (
            f"Thread subject: {subject} ({count} messages)\n\n"
            f"Thread:\n{thread_ctx}\n\n"
            "List all action items and to-dos mentioned in this thread. "
            "For each, note who is responsible and any deadline. "
            "Format as a bullet list. If none exist, say 'No action items found.'"
        )
    elif mode == "decisions":
        prompt = (
            f"Thread subject: {subject} ({count} messages)\n\n"
            f"Thread:\n{thread_ctx}\n\n"
            "List all decisions, agreements, or conclusions reached in this thread. "
            "Format as a bullet list. If none exist, say 'No decisions found.'"
        )
    elif mode == "questions":
        prompt = (
            f"Thread subject: {subject} ({count} messages)\n\n"
            f"Thread:\n{thread_ctx}\n\n"
            "List all open questions that are waiting for a response from Suneel specifically. "
            "Format as a bullet list. If none, say 'No open questions found.'"
        )
    else:
        prompt = (
            f"Thread subject: {subject} ({count} messages)\n\n"
            f"Thread:\n{thread_ctx}\n\n"
            "Provide a structured analysis:\n"
            "1. Key decisions made\n"
            "2. Action items and owners\n"
            "3. Open questions\n"
            "4. Does Suneel owe a reply? (yes/no + reason)\n"
            "Be concise and practical."
        )

    stream_local(
        prompt,
        system="You are Adwi, Suneel's AI assistant, analyzing an email thread. Be practical and concise."
    )
    _GMAIL_CTX["thread_intel"] = {"mode": mode, "subject": subject}


def cmd_gmail_forward(text: str = "") -> None:
    """Forward the current email to a new recipient. Shows preview; waits for explicit send."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return

    em = _GMAIL_CTX.get("current_email")
    if not em:
        cprint("  No current email — open an email first, then say 'forward to X'.", YELLOW); return

    adwi_head("Gmail — Forward Draft")

    # Extract recipient name/email after "to"
    to_m = re.search(
        r"\b(?:forward|fwd)\b.{0,25}\bto\s+([\w][\w\s.@+-]{1,40}?)(?:\s+(?:with|saying|and|cc|including|about)|[.,?]|$)",
        text, re.I
    )
    if not to_m:
        cprint("  Who should I forward this to?  e.g. 'forward to Rahul'", YELLOW); return
    to_raw = to_m.group(1).strip()

    resolved, candidates = _gmail_resolve_recipient(to_raw)
    if candidates:
        cprint(f"  '{to_raw}' is ambiguous — {len(candidates)} matches:", YELLOW)
        for i, c in enumerate(candidates, 1):
            cprint(f"    {i}. {c.get('display','')} <{c['email']}>", "")
        cprint("  Say 'forward to <full email>' to be explicit.", YELLOW); return
    if not resolved:
        cprint(f"  Could not resolve '{to_raw}' to an email address.", YELLOW)
        cprint("  Try 'forward to rahul@example.com' with the full email address.", YELLOW); return
    to_email = resolved

    # Detect intro instruction
    want_summary = bool(re.search(r"\bwith\s+(?:a\s+)?(?:summary|brief\s+note|note|intro|context)\b", text, re.I))
    intro_m = re.search(r"\b(?:saying|mentioning|adding|with\s+a\s+note\s+that)\b\s+(.+?)(?:[.,?]|$)", text, re.I)
    intro_instruction = intro_m.group(1).strip() if intro_m else ""

    cprint(f"  {GRAY}Preparing forward draft…{RESET}")

    intro_body = ""
    if want_summary:
        summary_prompt = (
            f"Write a brief 1-2 sentence intro for a forwarded email.\n"
            f"Original subject: {em.get('subject', '')}\n"
            f"Original body:\n{em.get('body', '')[:600]}\n\n"
            "Output only the intro paragraph. No greeting, no signature."
        )
        intro_body = _llm_generate(
            summary_prompt,
            system="You are drafting a brief forward intro for Suneel. Be concise. No greeting or signature."
        )
    elif intro_instruction:
        intro_prompt = (
            f"Write a 1-2 sentence forward intro based on this instruction: {intro_instruction}\n"
            "No greeting or signature. Just the intro."
        )
        intro_body = _llm_generate(
            intro_prompt,
            system="You are drafting a brief forward intro for Suneel. Be concise. No greeting or signature."
        )

    try:
        gh = _gmail()
        draft_ctx = gh.create_draft_forward(
            to            = to_email,
            subject       = em.get("subject", "(no subject)"),
            original_from = em.get("from", ""),
            original_date = em.get("date", ""),
            original_body = em.get("body", "")[:2000],
            intro_body    = intro_body,
        )
        _GMAIL_CTX["draft"] = draft_ctx
        _gmail_draft_preview(draft_ctx)
    except Exception as e:
        cprint(f"  Error creating forward draft: {e}", RED)


def cmd_gmail_list_category(name: str) -> None:
    """List emails in a Gmail category: promotions, spam, social, updates, forums."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return
    label = _GMAIL_CATEGORY_MAP.get(name.lower().strip(), name.upper())
    adwi_head(f"Gmail — {name.lower()}")
    try:
        gh = _gmail()
        emails = gh.list_category(category=label, max_results=10)
        if not emails:
            cprint(f"  No emails in {name}.", GRAY); return
        cprint(f"  {len(emails)} in {label}", GRAY)
        print()
        for i, em in enumerate(emails, 1):
            sender = em["from"].split("<")[0].strip()[:30]
            cprint(f"  {i:>2}. {BOLD}{em['subject'][:55]}{RESET}", "")
            cprint(f"      {GRAY}From: {sender:<30}  {em['date'][:16]}{RESET}", "")
            cprint(f"      {DIM}{em['snippet'][:90]}{RESET}", "")
            print()
        _GMAIL_IDS.clear();     _GMAIL_IDS.extend(e["id"] for e in emails)
        _GMAIL_SUBJECTS.clear(); _GMAIL_SUBJECTS.extend(e["subject"] for e in emails)
        _GMAIL_CTX["thread_ids"] = [e.get("thread_id","") for e in emails]
        _GMAIL_CTX["candidates"] = list(emails)
        _GMAIL_CTX["pending"]    = None  # clear any pending action from previous context
        print(f"  {GRAY}/gmail-read <n> · /gmail-archive · /gmail-trash · /gmail-mark-read{RESET}")
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)


def cmd_gmail_summarize(query: str = "") -> None:
    """LLM-summarize the current email or thread; or search then summarize."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Not authorized. Run: /gmail-auth", YELLOW); return
    try:
        gh = _gmail()
        want_thread = bool(re.search(r"\bthread|conversation\b", query, re.I))

        # Build a clean search string by stripping meta-words
        _meta = r"\b(summarize|summary|tldr|tl;dr|thread|conversation|email|message|this|that|it|the|of|a|an)\b"
        clean_q = re.sub(_meta, "", query, flags=re.I).strip(" ,.-")

        # If a search term is given, fetch the email/thread first
        if clean_q:
            emails = gh.list_emails(max_results=3, query=clean_q)
            if not emails:
                cprint(f"  No emails found for: {clean_q}", YELLOW); return
            em = gh.read_email(emails[0]["id"])
            _GMAIL_CTX["current_email"] = em
            if want_thread and em.get("thread_id"):
                _GMAIL_CTX["current_thread"] = gh.get_thread(em["thread_id"])

        # Summarize thread if available and wanted
        if want_thread and _GMAIL_CTX.get("current_thread"):
            thread = _GMAIL_CTX["current_thread"]
            msgs_text = "\n\n---\n\n".join(
                f"From: {m['from']}\nDate: {m['date']}\n\n{m['body'][:700]}"
                for m in thread["messages"]
            )
            adwi_head(f"Thread summary: {thread['subject'][:55]}")
            stream_local(
                f"Summarize this email thread:\nSubject: {thread['subject']}\n\n{msgs_text}\n\n"
                "Who said what, key decisions, action items. Concise.",
                system="You are Adwi summarizing an email thread for Suneel. Be practical and brief."
            )
        elif _GMAIL_CTX.get("current_email"):
            em = _GMAIL_CTX["current_email"]
            adwi_head(f"Email summary: {em.get('subject','')[:55]}")
            stream_local(
                f"Summarize this email:\nFrom: {em.get('from','')}\nSubject: {em.get('subject','')}\n"
                f"Date: {em.get('date','')}\n\n{em.get('body','')[:3000]}\n\n"
                "Key points and any action needed. 3-4 sentences.",
                system="You are Adwi summarizing an email for Suneel. Be concise and practical."
            )
        else:
            cprint("  No email context. Open an email first, or say 'summarize email from X'.", YELLOW)
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)



# ── Gmail Phase 2: preview → confirm mutation helpers ─────────────────────────

def _gmail_time_to_query(text: str) -> str:
    """Convert natural-language time phrases in text to a Gmail search modifier."""
    t = text.lower()
    m = re.search(r"older\s+than\s+(\d+)\s+(day|week|month)s?", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "week":  n *= 7
        elif unit == "month": n *= 30
        return f"older_than:{n}d"
    if re.search(r"older\s+than\s+a\s+week", t):  return "older_than:7d"
    if re.search(r"older\s+than\s+a\s+month", t): return "older_than:30d"
    if re.search(r"\byesterday\b", t):             return "after:yesterday before:today"
    if re.search(r"\blast\s+week\b", t):           return "older_than:1d newer_than:7d"
    if re.search(r"\bthis\s+week\b", t):           return "newer_than:7d"
    if re.search(r"\bthis\s+month\b", t):          return "newer_than:30d"
    if re.search(r"\btoday\b", t):                 return "newer_than:1d"
    return ""


def _gmail_resolve_candidates(text: str) -> tuple:
    """
    Resolve candidate emails for a bulk mutation from text + session context.
    Priority: category keyword → from/about query → session candidates.
    Returns (email_dict_list, description_str).
    """
    gh = _gmail()
    cat_m   = re.search(r"\b(promotions?|promo|promos?|promotional|newsletters?|social|updates?|forums?|spam)\b", text, re.I)
    from_m  = re.search(r"\bfrom\s+(\w[\w\s.@]{0,25}?)(?:\s+about|\s+older|\s+in\b|[?.,]|$)", text, re.I)
    about_m = re.search(r"\babout\s+(.+?)(?:\s+from|\s+older|[?.,]|$)", text, re.I)
    time_q  = _gmail_time_to_query(text)
    ref_words = bool(re.search(r"\b(all|those|these|them|that|it|the\s+(?:ones?|emails?|messages?))\b", text, re.I))

    if cat_m:
        label = _GMAIL_CATEGORY_MAP.get(cat_m.group(1).lower(), "INBOX")
        query = f"label:{label}"
        if time_q:  query += f" {time_q}"
        if from_m:  query += f" from:{from_m.group(1).strip()}"
        emails = gh.list_emails(max_results=_GMAIL_MAX_CANDIDATES, query=query, inbox_only=False)
        desc = f"{cat_m.group(1)}" + (f" {time_q}" if time_q else "")
        return emails[:_GMAIL_MAX_CANDIDATES], desc

    if from_m or about_m:
        parts = []
        if from_m:  parts.append(f"from:{from_m.group(1).strip()}")
        if about_m: parts.append(about_m.group(1).strip())
        if time_q:  parts.append(time_q)
        q = " ".join(parts)
        emails = gh.list_emails(max_results=_GMAIL_MAX_CANDIDATES, query=q, inbox_only=False)
        return emails[:_GMAIL_MAX_CANDIDATES], q

    if _GMAIL_CTX.get("candidates") and ref_words:
        cands = _GMAIL_CTX["candidates"]
        return cands[:_GMAIL_MAX_CANDIDATES], "current selection"

    if _GMAIL_IDS:
        dicts = [{"id": mid, "subject": subj, "from": "", "date": ""}
                 for mid, subj in zip(_GMAIL_IDS, _GMAIL_SUBJECTS)]
        return dicts[:_GMAIL_MAX_CANDIDATES], "current selection"

    return [], "no candidates — list emails first"


def _gmail_show_preview(action: str, candidates: list, desc: str) -> None:
    """Render a preview box for a pending Gmail mutation and set _GMAIL_CTX['pending']."""
    count = len(candidates)
    action_label = {
        "archive":     "Archive",
        "trash":       "Move to Trash",
        "mark_read":   "Mark Read",
        "mark_unread": "Mark Unread",
    }.get(action, action.title())
    W = 60
    title = f"{action_label}  {count} email{'s' if count != 1 else ''}  —  {desc}"[:W-2]
    cprint(f"\n  ┌{'─'*W}┐", GRAY)
    cprint(f"  │  {BOLD}{title:<{W-2}}{RESET}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    for em in candidates[:5]:
        subj = (em.get("subject") or "(no subject)")[:W-4]
        cprint(f"  │  {DIM}{subj:<{W-4}}{RESET}│")
    if count > 5:
        more = f"… {count-5} more"
        cprint(f"  │  {GRAY}{more:<{W-4}}{RESET}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    hint = "Type 'confirm' to apply · 'cancel' to abort"
    cprint(f"  │  {YELLOW}{hint:<{W-2}}{RESET}│")
    cprint(f"  └{'─'*W}┘\n", GRAY)
    _GMAIL_CTX["pending"] = {
        "action":      action,
        "ids":         [e["id"] for e in candidates],
        "count":       count,
        "description": f"{action_label} {count} email{'s' if count != 1 else ''} — {desc}",
    }


def _cmd_gmail_mutate_preview(action: str, text: str) -> None:
    """Shared logic: resolve candidates, show preview, set pending."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return
    action_labels = {"archive": "Archive", "trash": "Move to Trash",
                     "mark_read": "Mark Read", "mark_unread": "Mark Unread"}
    adwi_head(f"Gmail — {action_labels.get(action, action)}")
    try:
        candidates, desc = _gmail_resolve_candidates(text)
        if not candidates:
            cprint("  No emails found. List emails first or specify a category/sender.", YELLOW)
            return
        _gmail_show_preview(action, candidates, desc)
    except Exception as e:
        cprint(f"  Error: {e}", RED)


def cmd_gmail_archive(text: str = "") -> None:
    """Preview candidates for archive, then wait for 'confirm'."""
    _cmd_gmail_mutate_preview("archive", text)


def cmd_gmail_trash_emails(text: str = "") -> None:
    """Preview candidates for trash, then wait for 'confirm'."""
    _cmd_gmail_mutate_preview("trash", text)


def cmd_gmail_mark_read(text: str = "") -> None:
    """Preview candidates for mark-as-read, then wait for 'confirm'."""
    _cmd_gmail_mutate_preview("mark_read", text)


def cmd_gmail_mark_unread(text: str = "") -> None:
    """Preview candidates for mark-as-unread, then wait for 'confirm'."""
    _cmd_gmail_mutate_preview("mark_unread", text)


def cmd_gmail_confirm() -> None:
    """Execute the pending Gmail mutation after user says 'confirm'."""
    pending = _GMAIL_CTX.get("pending")
    if not pending:
        cprint("  No pending Gmail action. Run archive/trash/mark-read first.", YELLOW)
        return
    action = pending["action"]
    ids    = pending["ids"]
    desc   = pending["description"]
    adwi_head(f"Gmail — Executing: {desc}")
    try:
        gh = _gmail()
        if action == "archive":
            n = gh.archive_messages(ids)
        elif action == "trash":
            n = gh.trash_messages(ids)
        elif action == "mark_read":
            n = gh.mark_read(ids)
        elif action == "mark_unread":
            n = gh.mark_unread(ids)
        else:
            cprint(f"  Unknown action: {action}", RED); return
        _GMAIL_CTX["last_mutation"] = {
            "action": action, "ids": ids, "count": n, "description": desc,
        }
        _GMAIL_CTX["pending"]    = None
        _GMAIL_CTX["candidates"] = []
        _GMAIL_IDS.clear()
        _GMAIL_SUBJECTS.clear()
        verb = _GMAIL_ACTION_PAST.get(action, "processed")
        cprint(f"  ✓ Done — {n} email{'s' if n != 1 else ''} {verb}.", GREEN)
        cprint(f"  {GRAY}(Say 'undo' to reverse this.){RESET}")
    except Exception as e:
        cprint(f"  Error during {action}: {e}", RED)
        if "Insufficient" in str(e) or "scope" in str(e).lower() or "403" in str(e):
            cprint("  Scope error — run /gmail-auth to re-authorize with gmail.modify scope.", YELLOW)


def cmd_gmail_cancel() -> None:
    """Cancel a pending Gmail mutation."""
    pending = _GMAIL_CTX.get("pending")
    if not pending:
        if _GMAIL_CTX.get("draft"):
            cprint("  No pending Gmail action to cancel.", GRAY)
            cprint("  (You have an active draft — say 'cancel draft' to discard it.)", YELLOW)
        else:
            cprint("  No pending Gmail action.", GRAY)
        return
    desc = pending.get("description", "pending action")
    _GMAIL_CTX["pending"] = None
    cprint(f"  Cancelled: {desc}", GRAY)


def cmd_gmail_undo() -> None:
    """Undo the last confirmed archive, trash, mark-read, or mark-unread operation."""
    last = _GMAIL_CTX.get("last_mutation")
    if not last:
        cprint("  Nothing to undo — no Gmail action has been confirmed this session.", GRAY)
        return
    action = last["action"]
    ids    = last["ids"]
    n      = last["count"]
    desc   = last["description"]
    _UNDO_VERB = {
        "archive":     "unarchived",
        "trash":       "restored from trash",
        "mark_read":   "marked as unread",
        "mark_unread": "marked as read",
    }
    verb = _UNDO_VERB.get(action, "restored")
    adwi_head(f"Gmail — Undo: {desc}")
    cprint(f"  Reversing: {n} email{'s' if n != 1 else ''} will be {verb}.", YELLOW)
    try:
        gh = _gmail()
        if action == "archive":
            gh.unarchive_messages(ids)
        elif action == "trash":
            gh.untrash_messages(ids)
        elif action == "mark_read":
            gh.mark_unread(ids)
        elif action == "mark_unread":
            gh.mark_read(ids)
        else:
            cprint(f"  Undo not supported for action: {action}", RED); return
        _GMAIL_CTX["last_mutation"] = None
        cprint(f"  ✓ Undone — {n} email{'s' if n != 1 else ''} {verb}.", GREEN)
    except Exception as e:
        cprint(f"  Undo failed: {e}", RED)
        if "403" in str(e) or "scope" in str(e).lower():
            cprint("  Scope error — run /gmail-auth to re-authorize.", YELLOW)


# ── Gmail Phase 3: draft / send commands ─────────────────────────────────────

def _gmail_draft_preview(draft_ctx: dict) -> None:
    """Render a draft preview box from a draft context dict."""
    W = 60
    mode      = draft_ctx.get("mode", "compose").title()
    to        = (draft_ctx.get("to") or "")[:W-11]
    cc        = draft_ctx.get("cc") or ""
    bcc       = draft_ctx.get("bcc") or ""
    subject   = (draft_ctx.get("subject") or "")[:W-11]
    body      = (draft_ctx.get("body") or "").strip()
    out_atts  = draft_ctx.get("outbound_attachments") or []
    lines     = body.splitlines()
    cprint(f"\n  ┌{'─'*W}┐", GRAY)
    cprint(f"  │  {BOLD}Draft {mode:<{W-10}}{RESET}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    cprint(f"  │  {CYAN}To:{RESET}      {to:<{W-11}}{RESET}│")
    if cc:
        cprint(f"  │  {CYAN}CC:{RESET}      {cc[:W-11]:<{W-11}}{RESET}│")
    if bcc:
        cprint(f"  │  {CYAN}BCC:{RESET}     {bcc[:W-11]:<{W-11}}{RESET}│")
    cprint(f"  │  {CYAN}Subject:{RESET} {subject:<{W-11}}{RESET}│")
    for a in out_atts:
        fname = a.get("filename", "?")[:W-11]
        sz    = _human_size(a.get("size", 0)) if a.get("size") else ""
        label = f"{fname}  {sz}".strip()
        cprint(f"  │  {CYAN}\U0001f4ce{RESET}      {label[:W-11]:<{W-11}}{RESET}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    for ln in lines[:8]:
        cprint(f"  │  {DIM}{ln[:W-4]:<{W-4}}{RESET}│")
    if len(lines) > 8:
        more = f"… {len(lines)-8} more lines"
        cprint(f"  │  {GRAY}{more:<{W-4}}{RESET}│")
    cprint(f"  ├{'─'*W}┤", GRAY)
    hint = "Type 'send it' to send · 'cancel the draft' to discard"
    cprint(f"  │  {YELLOW}{hint:<{W-2}}{RESET}│")
    cprint(f"  └{'─'*W}┘\n", GRAY)


def cmd_gmail_draft_reply(text: str = "") -> None:
    """Draft a reply to the current email. LLM generates body; shows preview; waits for send."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return
    em = _GMAIL_CTX.get("current_email")
    if not em:
        cprint("  No current email — open an email first, then say 'reply saying X'.", YELLOW); return
    adwi_head("Gmail — Draft Reply")

    # Detect context-aware mode: "reply to the latest ask", "draft a follow-up"
    is_context_mode = bool(re.search(
        r"\b(?:latest\s+(?:ask|question|request)|follow.?up|based\s+on\s+(?:the\s+)?thread|reply\s+to\s+the\s+thread)\b",
        text, re.I
    ))

    if is_context_mode:
        thread = _GMAIL_CTX.get("current_thread")
        if not thread or not thread.get("messages"):
            cprint("  No thread context. Load the thread first with 'show the thread'.", YELLOW); return
        cprint(f"  {GRAY}Analyzing thread for latest ask…{RESET}")
        thread_ctx = _thread_build_context(thread, max_chars=2500)
        prompt = (
            f"Thread subject: {thread['subject']}\n\n"
            f"Thread:\n{thread_ctx}\n\n"
            "1. Identify the most recent unanswered question or request directed at Suneel.\n"
            "2. Write a concise, professional reply addressing it.\n"
            "Output ONLY the reply body text. No subject line. No explanation."
        )
        body = _llm_generate(
            prompt,
            system="You are drafting a reply for Suneel. Identify the latest ask in the thread and reply to it. Output only the email body. Be brief and professional."
        )
        if not body or body.startswith("[LLM error"):
            cprint(f"  Could not generate reply: {body}", RED); return
        try:
            gh        = _gmail()
            to        = em.get("from", "")
            subject   = em.get("subject", "(no subject)")
            msg_hdr   = em.get("message_id", "")
            thread_id = em.get("thread_id", "")
            draft_ctx = gh.create_draft_reply(
                reply_to_msg_id   = em["id"],
                message_id_header = msg_hdr,
                thread_id         = thread_id,
                to                = to,
                subject           = subject,
                body              = body,
            )
            _GMAIL_CTX["draft"] = draft_ctx
            _gmail_draft_preview(draft_ctx)
        except Exception as e:
            cprint(f"  Error creating draft: {e}", RED)
        return

    # Standard instruction-based path
    instruction = re.sub(
        r"^\s*(?:draft\s+a?\s*)?(?:reply|response|write\s+back)\s*(?:saying|that|with|to\s+(?:it|this|that))?\s*",
        "", text, flags=re.I
    ).strip()
    if not instruction:
        cprint("  What should the reply say?  e.g. 'reply saying I can do Friday'", YELLOW); return
    cprint(f"  {GRAY}Generating draft…{RESET}")
    prompt = (
        f"Write a concise professional email reply.\n"
        f"Original email:\n"
        f"  From: {em.get('from','')}\n"
        f"  Subject: {em.get('subject','')}\n"
        f"  Body:\n{em.get('body','')[:800]}\n\n"
        f"Reply instruction: {instruction}\n\n"
        f"Output ONLY the email body text. No subject line. Start directly with the reply content."
    )
    body = _llm_generate(prompt, system="You are drafting a professional email reply for Suneel. Output only the email body. Be brief and natural.")
    if not body or body.startswith("[LLM error"):
        cprint(f"  Could not generate reply body: {body}", RED); return
    try:
        gh        = _gmail()
        to        = em.get("from", "")
        subject   = em.get("subject", "(no subject)")
        msg_hdr   = em.get("message_id", "")
        thread_id = em.get("thread_id", "")
        draft_ctx = gh.create_draft_reply(
            reply_to_msg_id   = em["id"],
            message_id_header = msg_hdr,
            thread_id         = thread_id,
            to                = to,
            subject           = subject,
            body              = body,
        )
        _GMAIL_CTX["draft"] = draft_ctx
        _gmail_draft_preview(draft_ctx)
    except Exception as e:
        cprint(f"  Error creating draft: {e}", RED)


def cmd_gmail_compose(text: str = "") -> None:
    """Compose a new email draft with contact-name resolution and CC/BCC support."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return
    adwi_head("Gmail — Compose Draft")
    # Extract TO — stops at cc/bcc keyword or saying/about
    # Pattern 1: "email Rahul saying" / "message Priya about"
    to_m = re.search(
        r"\b(?:email|message)\s+([\w][\w\s.]{0,30}?)"
        r"(?:\s+(?:and\s+)?(?:cc|bcc)\b|\s+(?:saying|about|that|to\s+say|regarding))",
        text, re.I
    )
    # Pattern 2: "compose/write/draft/send an email to Rahul saying" (fallback)
    if not to_m:
        to_m = re.search(
            r"\bto\s+([\w][\w\s.@]{0,30}?)"
            r"(?:\s+(?:and\s+)?(?:cc|bcc)\b|\s+(?:saying|about|that|to\s+say|regarding)|$)",
            text, re.I
        )
    # Extract CC
    cc_m = re.search(
        r"\b(?:and\s+)?cc\s+([\w][\w\s.]{0,30}?)"
        r"(?:\s+(?:and\s+)?bcc\b|\s+(?:saying|about|that|to\s+say)|$)",
        text, re.I
    )
    # Extract BCC
    bcc_m = re.search(
        r"\bbcc\s+([\w][\w\s.]{0,30}?)"
        r"(?:\s+(?:saying|about|that|to\s+say)|$)",
        text, re.I
    )
    # Extract instruction
    inst_m = re.search(r"\b(?:saying|about|that|to\s+say|regarding)\s+(.+?)(?:[?.]|$)", text, re.I)

    to_raw      = to_m.group(1).strip() if to_m else ""
    cc_raw      = cc_m.group(1).strip() if cc_m else ""
    bcc_raw     = bcc_m.group(1).strip() if bcc_m else ""
    instruction = inst_m.group(1).strip() if inst_m else re.sub(
        r"^(?:compose|write|draft|email|message)\b.{0,25}?\s+", "", text, flags=re.I).strip()

    if not to_raw:
        to_raw = input(f"  {YELLOW}To (name or email):{RESET} ").strip()
        if not to_raw:
            cprint("  Cancelled.", GRAY); return

    # Resolve CC/BCC inline (no multi-stage disambiguation — direct ask on ambiguity)
    cc_resolved = ""
    bcc_resolved = ""
    if cc_raw:
        cc_resolved = _gmail_resolve_inline(cc_raw)
        if cc_resolved:
            cprint(f"  {GRAY}CC: {cc_resolved}{RESET}")
        else:
            cprint(f"  {YELLOW}Could not resolve CC '{cc_raw}'{RESET}")
            cc_input = input(f"  {YELLOW}CC email (or blank to skip):{RESET} ").strip()
            cc_resolved = cc_input if "@" in cc_input else ""
    if bcc_raw:
        bcc_resolved = _gmail_resolve_inline(bcc_raw)
        if bcc_resolved:
            cprint(f"  {GRAY}BCC: {bcc_resolved}{RESET}")
        else:
            cprint(f"  {YELLOW}Could not resolve BCC '{bcc_raw}'{RESET}")
            bcc_input = input(f"  {YELLOW}BCC email (or blank to skip):{RESET} ").strip()
            bcc_resolved = bcc_input if "@" in bcc_input else ""

    # Resolve TO — full flow with disambiguation
    cprint(f"  {GRAY}Looking up {to_raw!r}…{RESET}")
    resolved, candidates = _gmail_resolve_recipient(to_raw)
    if resolved:
        if not instruction:
            instruction = input(f"  {YELLOW}What should the email say?{RESET} ").strip()
            if not instruction:
                cprint("  Cancelled.", GRAY); return
        _gmail_do_compose(resolved, _derive_subject(text, instruction), instruction,
                          cc=cc_resolved, bcc=bcc_resolved)
    elif candidates:
        cprint(f"\n  Multiple contacts named {to_raw!r}:", YELLOW)
        for i, c in enumerate(candidates, 1):
            cnt_str = f"  ({c['count']} messages)" if c.get("count") else ""
            cprint(f"  {i}. {c['display']} <{c['email']}>{cnt_str}", "")
        cprint(f"\n  {YELLOW}Type a number to choose{RESET}")
        if not instruction:
            instruction = input(f"  {YELLOW}What should the email say?{RESET} ").strip()
        _GMAIL_CTX["pending_recipient"] = {
            "name":        to_raw,
            "instruction": instruction,
            "candidates":  candidates,
            "mode":        "compose",
            "subject":     _derive_subject(text, instruction),
            "cc":          cc_resolved,
            "bcc":         bcc_resolved,
        }
    else:
        cprint(f"  No contacts found for {to_raw!r} in your Gmail history.", YELLOW)
        email = input(f"  {YELLOW}Enter email address:{RESET} ").strip()
        if not email or "@" not in email:
            cprint("  Need a valid email address. Cancelled.", YELLOW); return
        if not instruction:
            instruction = input(f"  {YELLOW}What should the email say?{RESET} ").strip()
            if not instruction:
                cprint("  Cancelled.", GRAY); return
        _gmail_do_compose(email, _derive_subject(text, instruction), instruction,
                          cc=cc_resolved, bcc=bcc_resolved)



# ── Gmail Phase 14: smart subject extraction helper ─────────────────────────────

def _derive_subject(text: str, instruction: str) -> str:
    """
    Phase 14: Derive a concise email subject from the compose prompt.
    Priority: explicit about/re/regarding topic phrase → cleaned title-case.
    Fallback: first significant words of the instruction.
    """
    tl = text.lower()

    # Pattern 1: "about X saying/to say/to tell/that/mentioning" → X is the topic
    m = re.search(
        r"\babout\s+([\w][\w\s,.'/-]{1,55}?)"
        r"(?=\s+(?:saying|to\s+say|to\s+tell|that\s+I|mentioning|and\s+I\b))",
        text, re.I
    )
    if m:
        return _clean_subject_phrase(m.group(1))

    # Pattern 2: "re:? X" (stops at saying/about-2 or end of phrase)
    m = re.search(
        r"\bre:?\s+([\w][\w\s,.'/-]{1,55}?)(?=\s+(?:saying|and\s+I|to\s+say)|[.,?]|$)",
        text, re.I
    )
    if m:
        return _clean_subject_phrase(m.group(1))

    # Pattern 3: "regarding X"
    m = re.search(
        r"\bregarding\s+([\w][\w\s,.'/-]{1,55}?)(?=\s+(?:saying|and\s+I)|[.,?]|$)",
        text, re.I
    )
    if m:
        return _clean_subject_phrase(m.group(1))

    # Pattern 4: bare "about X" (no saying — takes until punctuation or end)
    m = re.search(
        r"\babout\s+([\w][\w\s,.'/-]{2,50})(?=[.,?]|$)",
        text, re.I
    )
    if m:
        return _clean_subject_phrase(m.group(1))

    # Fallback: strip filler from instruction, take first ~55 chars
    filler = r"^\s*(?:I\s+want\s+to|please\s+|can\s+you\s+|just\s+|i\s+need\s+to\s+)"
    cleaned = re.sub(filler, "", instruction, flags=re.I).strip()
    return cleaned[:55].rstrip(".,?! ") or instruction[:55].rstrip(".,?! ")


def _clean_subject_phrase(phrase: str) -> str:
    """Trim, strip leading articles, limit length, title-case if short."""
    phrase = phrase.strip().rstrip(".,?! ")
    # Strip leading article
    phrase = re.sub(r"^(?:the|a|an)\s+", "", phrase, flags=re.I).strip()
    phrase = phrase[:55].rstrip(".,?! ")
    # Title-case only if 4 words or fewer (avoids mangling long phrases)
    words = phrase.split()
    if len(words) <= 4:
        return " ".join(w.capitalize() if w.lower() not in {"the","a","an","of","to","in","at","and","or","for","on","by"} or i == 0 else w for i, w in enumerate(words))
    return phrase


# ── Gmail Phase 4: contact resolution + draft rewrite helpers ─────────────────

def _extract_rewrite_instruction(text: str) -> str:
    """Strip compose meta-preamble from a rewrite instruction string."""
    cleaned = re.sub(
        r"^\s*(?:make|rewrite|revise|edit|update)\s+(?:it|the\s+(?:draft|reply|email|message)|this)?\s*(?:to\s+(?:be\s+)?|more\s+)?",
        "", text, flags=re.I
    ).strip()
    cleaned = re.sub(
        r"\s+(?:in|to)\s+(?:the\s+)?(?:draft|reply|email|message)\s*$",
        "", cleaned, flags=re.I
    ).strip()
    return cleaned or text.strip()


def _gmail_resolve_inline(name_or_email: str) -> str:
    """
    Lightweight resolution for CC/BCC recipients — no disambiguation flow.
    Returns resolved email string, or "" if unresolvable.
    """
    name_or_email = name_or_email.strip()
    if not name_or_email:
        return ""
    if "@" in name_or_email:
        return name_or_email
    # Self-reference: "me", "myself"
    if re.match(r"^(?:me|myself|my\s+self)$", name_or_email, re.I):
        try:
            return _gmail().get_my_email()
        except Exception:
            return ""
    # Check in-session cache
    cache_key = name_or_email.lower()
    cached = _GMAIL_CTX["contacts"].get(cache_key)
    if cached:
        return cached["email"]
    # Resolve via Gmail history — auto-pick single match; return "" on ambiguity
    try:
        candidates = _gmail().resolve_contact(name_or_email)
    except Exception:
        return ""
    if len(candidates) == 1:
        _GMAIL_CTX["contacts"][cache_key] = {
            "email":   candidates[0]["email"],
            "display": candidates[0].get("display", ""),
        }
        return candidates[0]["email"]
    return ""  # Multiple matches → caller will ask for direct email entry


def _gmail_resolve_recipient(name_or_email: str) -> tuple:
    """
    Resolve a recipient name to email addresses using Gmail history + session cache.
    Returns (resolved_str_or_None, candidates_list).
    resolved_str is set when exactly one match is found (and the result is cached).
    candidates_list is non-empty when the match is ambiguous.
    """
    if "@" in name_or_email:
        return name_or_email, []
    # Check in-session cache first
    cache_key = name_or_email.lower().strip()
    cached = _GMAIL_CTX["contacts"].get(cache_key)
    if cached:
        cprint(f"  {GRAY}✓ Cached: {cached['display']} <{cached['email']}>{RESET}")
        return cached["email"], []
    try:
        gh         = _gmail()
        candidates = gh.resolve_contact(name_or_email)
    except Exception as e:
        cprint(f"  {GRAY}Contact lookup failed: {e}{RESET}")
        return None, []
    if len(candidates) == 1:
        # Cache the successful single-match resolution
        _GMAIL_CTX["contacts"][cache_key] = {
            "email":   candidates[0]["email"],
            "display": candidates[0].get("display", candidates[0]["email"]),
        }
        return candidates[0]["email"], []
    elif len(candidates) > 1:
        return None, candidates
    return None, []


def _gmail_do_compose(to: str, subject: str, instruction: str,
                       cc: str = "", bcc: str = "") -> None:
    """Core draft-creation step after recipient is fully resolved."""
    cprint(f"  {GRAY}Generating draft…{RESET}")
    prompt = (
        f"Write a concise professional email.\n"
        f"To: {to}\n"
        f"Content instruction: {instruction}\n\n"
        f"Output ONLY the email body text. No subject line. Be natural and brief."
    )
    body = _llm_generate(
        prompt,
        system="You are drafting a professional email for Suneel. Output only the body text, no subject line."
    )
    if not body or body.startswith("[LLM error"):
        cprint(f"  Could not generate draft: {body}", RED); return
    try:
        gh        = _gmail()
        draft_ctx = gh.create_draft_compose(to=to, subject=subject, body=body, cc=cc, bcc=bcc)
        _GMAIL_CTX["draft"] = draft_ctx
        _gmail_draft_preview(draft_ctx)
    except Exception as e:
        cprint(f"  Error creating draft: {e}", RED)


# ── Gmail Phase 6: attachment helpers ─────────────────────────────────────────

def _gmail_attachment_text(path: Path, max_chars: int = 6000) -> str:
    """Extract readable text from a saved attachment for LLM summarization."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".log", ".rst", ".eml"}:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception:
            return ""
    if suffix in IMAGE_EXTS:
        return ""  # caller handles image branch via analyze_image()
    # PDF / DOCX / XLSX / PPTX / EPUB → markitdown (available in venv)
    try:
        from markitdown import MarkItDown
        result = MarkItDown().convert(str(path))
        return (result.text_content or "")[:max_chars]
    except Exception:
        return ""


def _gmail_pick_attachment(text: str) -> dict | None:
    """
    Select one attachment from _GMAIL_CTX["attachments"] by ordinal, mime-type
    hint, or filename substring. Auto-selects if only one attachment exists.
    Returns the matching dict or None.
    """
    atts = _GMAIL_CTX.get("attachments", [])
    if not atts:
        return None
    if len(atts) == 1:
        return atts[0]
    low = text.lower()
    # Ordinal keywords
    ordinals = {
        "first": 0, "1st": 0, "1": 0,
        "second": 1, "2nd": 1, "2": 1,
        "third": 2, "3rd": 2, "3": 2,
        "fourth": 3, "4th": 3, "4": 3,
    }
    for word, idx in ordinals.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            if idx < len(atts):
                return atts[idx]
    # Mime-type hints
    mime_hints = [
        ("pdf",         "application/pdf"),
        ("word",        "application/vnd.openxmlformats-officedocument.wordprocessingml"),
        ("excel",       "application/vnd.openxmlformats-officedocument.spreadsheetml"),
        ("spreadsheet", "application/vnd.openxmlformats-officedocument.spreadsheetml"),
        ("csv",         "text/csv"),
        ("zip",         "application/zip"),
        ("image",       "image/"),
        ("photo",       "image/"),
        ("picture",     "image/"),
    ]
    for hint, mime_prefix in mime_hints:
        if hint in low:
            for att in atts:
                if att.get("mime_type", "").lower().startswith(mime_prefix):
                    return att
    # Filename substring match — any word 3+ chars appearing in filename
    for att in atts:
        fname = att.get("filename", "").lower()
        for word in re.findall(r"\w{3,}", low):
            if word in fname:
                return att
    return None


# ── Gmail Phase 7: outbound attachment helpers ────────────────────────────────

_ATTACH_SAFE_EXTS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv",
    ".txt", ".md", ".pptx", ".ppt", ".epub", ".rtf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".zip",
}
_ATTACH_MAX_MB = 20  # reject files larger than this


def _gmail_resolve_attach_file(text: str) -> tuple:
    """
    Resolve a natural-language file reference to a local safe file for attachment.
    Returns (resolved_Path_or_None, candidates_list).
    Checks safe_to_read() on every candidate — blocked/secret files are excluded.
    """
    low = text.lower()

    # "that saved attachment" / "the saved attachment" → reuse Phase 6 saved file
    if (re.search(r"\b(?:that|the|saved)\b", low) and
            re.search(r"\battachment\b", low)):
        ca = _GMAIL_CTX.get("current_attachment") or {}
        sp = ca.get("saved_path", "")
        if sp and Path(sp).exists():
            ok, _ = safe_to_read(sp)
            if ok:
                return Path(sp), []

    # Strip meta-words to extract the search query
    query = re.sub(r"^\s*(?:attach|add|include)\s+(?:the\s+|a\s+)?", "", text, flags=re.I).strip()
    query = re.sub(r"\s+(?:to|from|in|at)\s+(?:this|the)\s+(?:draft|email|message|reply)\s*$",
                   "", query, flags=re.I).strip()
    query = re.sub(
        r"\b(?:the\s+)?(?:file|document|pdf|spreadsheet|image|invoice|report|attachment|deck|photo|picture)\b",
        "", query, flags=re.I
    ).strip().lower()

    if not query:
        return None, []

    # Search safe directories in priority order
    search_dirs = [
        ATTACH_SAVE_DIR,
        HOME / "Downloads",
        NOTES,
        BASE / "docs",
        BASE / "obsidian-vault",
    ]
    candidates: list[Path] = []
    seen: set[str] = set()
    for d in search_dirs:
        if not d.exists():
            continue
        ok_dir, _ = safe_to_read(d)
        if not ok_dir:
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() not in _ATTACH_SAFE_EXTS:
                continue
            if str(f) in seen:
                continue
            ok_f, _ = safe_to_read(f)
            if not ok_f:
                continue
            try:
                sz = f.stat().st_size
            except OSError:
                continue
            if sz > _ATTACH_MAX_MB * 1024 * 1024:
                continue
            if query in f.name.lower():
                candidates.append(f)
                seen.add(str(f))

    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates[:8]


def cmd_gmail_attach_file(text: str = "") -> None:
    """Attach a local file to the current draft (safe path check; updates Gmail draft)."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft. Compose or reply first, then attach.", YELLOW); return

    resolved, candidates = _gmail_resolve_attach_file(text)

    if resolved is None and not candidates:
        cprint("  No matching safe file found.", YELLOW)
        cprint(f"  Say '/gmail-attach <path>' with an explicit path, or check ~/SuneelWorkSpace/gmail-attachments/", GRAY)
        return

    if resolved is None and candidates:
        # Disambiguation
        cprint(f"  {len(candidates)} files match — choose one:", YELLOW)
        for i, p in enumerate(candidates, 1):
            try:
                sz = _human_size(p.stat().st_size)
            except OSError:
                sz = "?"
            cprint(f"  {i}. {p.name}  {GRAY}({sz}  {p.parent}){RESET}")
        _GMAIL_CTX["pending_attach"] = [
            {"path": str(p), "filename": p.name,
             "size": p.stat().st_size if p.exists() else 0}
            for p in candidates
        ]
        cprint(f"\n  {YELLOW}Type a number to attach, or '/gmail-attach <full-path>'{RESET}")
        return

    _do_attach_file(resolved)


def _do_attach_file(path: Path) -> None:
    """Attach a verified safe Path to the current draft and update Gmail."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft.", YELLOW); return

    ok, reason = safe_to_read(path)
    if not ok:
        cprint(f"  Cannot attach: {reason}", RED); return

    try:
        sz = path.stat().st_size
    except OSError as e:
        cprint(f"  Cannot read file: {e}", RED); return

    if sz > _ATTACH_MAX_MB * 1024 * 1024:
        cprint(f"  File too large ({_human_size(sz)}). Max per-file limit is {_ATTACH_MAX_MB} MB.", RED); return

    adwi_head("Gmail — Attach File")
    cprint(f"  File: {path.name}  {GRAY}({_human_size(sz)}  {path.parent}){RESET}", "")

    out_atts = draft.setdefault("outbound_attachments", [])
    # Avoid duplicate
    if any(a["path"] == str(path) for a in out_atts):
        cprint(f"  Already attached: {path.name}", YELLOW); return

    out_atts.append({"path": str(path), "filename": path.name, "size": sz})
    att_paths = [a["path"] for a in out_atts]

    try:
        gh = _gmail()
        gh.update_draft(
            draft["draft_id"], draft["to"], draft["subject"], draft["body"],
            thread_id=draft.get("thread_id"),
            message_id_header=draft.get("message_id", ""),
            cc=draft.get("cc") or "",
            bcc=draft.get("bcc") or "",
            attachments=att_paths,
        )
        cprint(f"  ✓ Attached: {path.name}", GREEN)
    except Exception as e:
        cprint(f"  {YELLOW}Gmail draft update failed ({e}) — attachment recorded locally.{RESET}")

    _gmail_draft_preview(draft)
    _GMAIL_CTX["pending_attach"] = None


def cmd_gmail_remove_attachment(text: str = "") -> None:
    """Remove an outbound attachment from the current draft by name or ordinal."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft.", YELLOW); return
    out_atts = draft.get("outbound_attachments") or []
    if not out_atts:
        cprint("  No attachments on current draft.", GRAY); return

    # Select attachment to remove by ordinal or filename substring
    low = text.lower()
    ordinals = {"first": 0, "1st": 0, "1": 0, "second": 1, "2nd": 1, "2": 1,
                "third": 2, "3rd": 2, "3": 2}
    chosen_idx = None
    for word, idx in ordinals.items():
        if re.search(rf"\b{re.escape(word)}\b", low) and idx < len(out_atts):
            chosen_idx = idx; break

    if chosen_idx is None:
        # Match by filename substring
        for i, a in enumerate(out_atts):
            fname_words = re.findall(r"\w{2,}", a.get("filename", "").lower())
            query_words = re.findall(r"\w{3,}", low)
            if any(qw in " ".join(fname_words) for qw in query_words):
                chosen_idx = i; break

    if chosen_idx is None:
        if len(out_atts) == 1:
            chosen_idx = 0
        else:
            cprint("  Which attachment?", YELLOW)
            for i, a in enumerate(out_atts, 1):
                sz = _human_size(a.get("size", 0)) if a.get("size") else "?"
                cprint(f"  {i}. {a.get('filename','?')}  {GRAY}({sz}){RESET}")
            cprint(f"  {YELLOW}Say 'remove attachment 1', 'remove the PDF', etc.{RESET}")
            return

    removed = out_atts.pop(chosen_idx)
    adwi_head("Gmail — Remove Attachment")
    cprint(f"  Removed: {removed.get('filename','?')}", GRAY)
    try:
        gh = _gmail()
        gh.update_draft(
            draft["draft_id"], draft["to"], draft["subject"], draft["body"],
            thread_id=draft.get("thread_id"),
            message_id_header=draft.get("message_id", ""),
            cc=draft.get("cc") or "",
            bcc=draft.get("bcc") or "",
            attachments=[a["path"] for a in out_atts],
        )
        cprint(f"  ✓ Draft updated.", GREEN)
    except Exception as e:
        cprint(f"  {YELLOW}Gmail draft update failed ({e}) — local preview updated.{RESET}")
    _gmail_draft_preview(draft)


def cmd_gmail_attach_choice(selection: int) -> None:
    """Handle bare-number selection from attachment file disambiguation list."""
    candidates = _GMAIL_CTX.get("pending_attach") or []
    if not candidates:
        cprint("  No active file disambiguation.", GRAY); return
    idx = selection - 1
    if idx < 0 or idx >= len(candidates):
        cprint(f"  Please choose a number between 1 and {len(candidates)}.", YELLOW); return
    chosen = candidates[idx]
    _GMAIL_CTX["pending_attach"] = None
    _do_attach_file(Path(chosen["path"]))


def cmd_gmail_recipient_choice(selection: int) -> None:
    """Handle a bare-number selection from recipient disambiguation list."""
    pr = _GMAIL_CTX.get("pending_recipient")
    if not pr:
        cprint("  No active recipient disambiguation.", GRAY); return
    candidates = pr.get("candidates", [])
    idx = selection - 1
    if idx < 0 or idx >= len(candidates):
        cprint(f"  Please choose a number between 1 and {len(candidates)}.", YELLOW); return
    chosen  = candidates[idx]
    to      = chosen["email"]
    display = chosen.get("display", to.split("@")[0])
    # Populate in-session cache so subsequent emails to same person are instant
    cache_key = (pr.get("name") or "").lower().strip()
    if cache_key:
        _GMAIL_CTX["contacts"][cache_key] = {"email": to, "display": display}
    cprint(f"  ✓ Recipient: {display} <{to}>", GREEN)
    _GMAIL_CTX["pending_recipient"] = None
    instruction = pr.get("instruction", "")
    subject     = pr.get("subject") or _derive_subject(instruction, instruction)
    cc          = pr.get("cc", "")
    bcc         = pr.get("bcc", "")
    if not instruction:
        instruction = input(f"  {YELLOW}What should the email say?{RESET} ").strip()
        if not instruction:
            cprint("  Cancelled.", GRAY); return
        subject = _derive_subject(instruction, instruction)
    _gmail_do_compose(to, subject, instruction, cc=cc, bcc=bcc)


def cmd_gmail_add_cc(text: str = "") -> None:
    """Add a CC recipient to the current draft, update Gmail draft in-place, show preview."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft. Create one first with 'compose an email to X'.", YELLOW); return
    # Extract name/email from text: strip leading "add cc " / "cc "
    cc_raw = re.sub(r"^\s*(?:add\s+)?cc\s+", "", text, flags=re.I).strip()
    cc_raw = re.sub(r"\s+(?:to\s+(?:the\s+)?(?:draft|email|message))\s*$", "", cc_raw, flags=re.I).strip()
    if not cc_raw:
        cc_raw = input(f"  {YELLOW}CC (name or email):{RESET} ").strip()
        if not cc_raw:
            cprint("  Cancelled.", GRAY); return
    resolved = _gmail_resolve_inline(cc_raw)
    if not resolved:
        cprint(f"  Could not resolve '{cc_raw}'.", YELLOW)
        resolved = input(f"  {YELLOW}CC email address:{RESET} ").strip()
        if not resolved or "@" not in resolved:
            cprint("  Cancelled.", YELLOW); return
    adwi_head("Gmail — Add CC")
    existing_cc = draft.get("cc") or ""
    new_cc = f"{existing_cc}, {resolved}".strip(", ") if existing_cc else resolved
    try:
        gh = _gmail()
        gh.update_draft(
            draft["draft_id"], draft["to"], draft["subject"], draft["body"],
            thread_id=draft.get("thread_id"),
            message_id_header=draft.get("message_id", ""),
            cc=new_cc,
            bcc=draft.get("bcc") or "",
            attachments=[a["path"] for a in draft.get("outbound_attachments") or []],
        )
    except Exception as e:
        cprint(f"  {YELLOW}Gmail draft update failed ({e}) — CC added locally.{RESET}")
    _GMAIL_CTX["draft"]["cc"] = new_cc
    cprint(f"  ✓ CC: {new_cc}", GREEN)
    _gmail_draft_preview(_GMAIL_CTX["draft"])


def cmd_gmail_add_bcc(text: str = "") -> None:
    """Add a BCC recipient to the current draft, update Gmail draft in-place, show preview."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft. Create one first with 'compose an email to X'.", YELLOW); return
    bcc_raw = re.sub(r"^\s*(?:add\s+)?bcc\s+", "", text, flags=re.I).strip()
    bcc_raw = re.sub(r"\s+(?:to\s+(?:the\s+)?(?:draft|email|message))\s*$", "", bcc_raw, flags=re.I).strip()
    if not bcc_raw:
        bcc_raw = input(f"  {YELLOW}BCC (name or email):{RESET} ").strip()
        if not bcc_raw:
            cprint("  Cancelled.", GRAY); return
    resolved = _gmail_resolve_inline(bcc_raw)
    if not resolved:
        cprint(f"  Could not resolve '{bcc_raw}'.", YELLOW)
        resolved = input(f"  {YELLOW}BCC email address:{RESET} ").strip()
        if not resolved or "@" not in resolved:
            cprint("  Cancelled.", YELLOW); return
    adwi_head("Gmail — Add BCC")
    existing_bcc = draft.get("bcc") or ""
    new_bcc = f"{existing_bcc}, {resolved}".strip(", ") if existing_bcc else resolved
    try:
        gh = _gmail()
        gh.update_draft(
            draft["draft_id"], draft["to"], draft["subject"], draft["body"],
            thread_id=draft.get("thread_id"),
            message_id_header=draft.get("message_id", ""),
            cc=draft.get("cc") or "",
            bcc=new_bcc,
            attachments=[a["path"] for a in draft.get("outbound_attachments") or []],
        )
    except Exception as e:
        cprint(f"  {YELLOW}Gmail draft update failed ({e}) — BCC added locally.{RESET}")
    _GMAIL_CTX["draft"]["bcc"] = new_bcc
    cprint(f"  ✓ BCC: {new_bcc}", GREEN)
    _gmail_draft_preview(_GMAIL_CTX["draft"])


def cmd_gmail_list_attachments(text: str = "") -> None:
    """List attachments on the current email or thread."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return
    try:
        gh = _gmail()
        want_thread = bool(re.search(r"\bthread|conversation\b", text, re.I))
        atts, source_name = [], ""

        if want_thread and _GMAIL_CTX.get("current_thread"):
            t = _GMAIL_CTX["current_thread"]
            atts = gh.list_thread_attachments(t["thread_id"])
            source_name = t.get("subject", "thread")[:55]
        elif _GMAIL_CTX.get("current_email"):
            em = _GMAIL_CTX["current_email"]
            atts = gh.list_attachments(em["id"])
            source_name = em.get("subject", "email")[:55]
        else:
            cprint("  No current email. Open one first, then say 'show attachments'.", YELLOW)
            return

        if not atts:
            cprint(f"  No attachments on: {source_name}", YELLOW); return

        _GMAIL_CTX["attachments"] = atts
        adwi_head(f"Attachments — {source_name}")
        for i, att in enumerate(atts, 1):
            size_str = _human_size(att["size"]) if att.get("size") else "?"
            cprint(f"  {i}. {att['filename']}", CYAN)
            cprint(f"     {GRAY}{att['mime_type']}  {size_str}{RESET}")
        hint = "save the first attachment · save the PDF · summarize the attachment"
        cprint(f"\n  {YELLOW}{hint}{RESET}")
    except Exception as e:
        cprint(f"  Gmail error: {e}", RED)


def cmd_gmail_save_attachment(text: str = "") -> None:
    """Save a selected attachment from the current email to the workspace."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return

    # Auto-populate if not yet listed
    if not _GMAIL_CTX.get("attachments"):
        em = _GMAIL_CTX.get("current_email")
        if not em:
            cprint("  No current email. Open one first.", YELLOW); return
        try:
            _GMAIL_CTX["attachments"] = _gmail().list_attachments(em["id"])
        except Exception as e:
            cprint(f"  Could not list attachments: {e}", RED); return

    atts = _GMAIL_CTX.get("attachments", [])
    if not atts:
        cprint("  No attachments on this email.", YELLOW); return

    att = _gmail_pick_attachment(text)
    if att is None:
        if len(atts) > 1:
            cprint(f"  {len(atts)} attachments found — be more specific:", YELLOW)
            for i, a in enumerate(atts, 1):
                cprint(f"  {i}. {a['filename']}  {GRAY}({_human_size(a.get('size',0))}){RESET}")
            return
        att = atts[0]

    adwi_head("Gmail — Save Attachment")
    cprint(f"  File: {att['filename']}", CYAN)
    cprint(f"  Type: {att['mime_type']}  Size: {_human_size(att.get('size', 0))}", GRAY)
    try:
        saved = _gmail().save_attachment(
            att["message_id"], att["attachment_id"], att["filename"], ATTACH_SAVE_DIR
        )
        att["saved_path"] = str(saved)
        _GMAIL_CTX["current_attachment"] = att
        cprint(f"  ✓ Saved: {saved}", GREEN)
        # "open the PDF" — open with macOS default app
        if re.search(r"\bopen\b", text, re.I):
            import subprocess as _sub
            _sub.run(["open", str(saved)], check=False)
        cprint(f"  {GRAY}Say 'summarize the attachment' to read and summarize it.{RESET}")
    except Exception as e:
        cprint(f"  Save failed: {e}", RED)


def cmd_gmail_summarize_attachment(text: str = "") -> None:
    """Save (if needed) and LLM-summarize a text-extractable attachment."""
    token = HOME / "SuneelWorkSpace" / "secrets" / "gmail-token.json"
    if not token.exists():
        cprint("  Gmail not authorized — run /gmail-auth first", RED); return

    # Auto-populate if not yet listed
    if not _GMAIL_CTX.get("attachments"):
        em = _GMAIL_CTX.get("current_email")
        if not em:
            cprint("  No current email. Open one first.", YELLOW); return
        try:
            _GMAIL_CTX["attachments"] = _gmail().list_attachments(em["id"])
        except Exception as e:
            cprint(f"  Could not list attachments: {e}", RED); return

    atts = _GMAIL_CTX.get("attachments", [])
    if not atts:
        cprint("  No attachments on this email.", YELLOW); return

    att = _gmail_pick_attachment(text)
    if att is None:
        if len(atts) > 1:
            cprint(f"  {len(atts)} attachments — be more specific:", YELLOW)
            for i, a in enumerate(atts, 1):
                cprint(f"  {i}. {a['filename']}  {GRAY}({_human_size(a.get('size',0))}){RESET}")
            return
        att = atts[0]

    adwi_head(f"Gmail — Summarize: {att['filename']}")

    # Save if not already done
    saved_path_str = att.get("saved_path")
    saved_path = Path(saved_path_str) if (saved_path_str and Path(saved_path_str).exists()) else None
    if not saved_path:
        cprint(f"  {GRAY}Saving {att['filename']}…{RESET}")
        try:
            saved_path = _gmail().save_attachment(
                att["message_id"], att["attachment_id"], att["filename"], ATTACH_SAVE_DIR
            )
            att["saved_path"] = str(saved_path)
            _GMAIL_CTX["current_attachment"] = att
            cprint(f"  ✓ Saved: {saved_path}", GREEN)
        except Exception as e:
            cprint(f"  Save failed: {e}", RED); return

    # Images → existing analyze_image
    if saved_path.suffix.lower() in IMAGE_EXTS:
        analyze_image(str(saved_path)); return

    # Extract text
    cprint(f"  {GRAY}Extracting text…{RESET}")
    text_content = _gmail_attachment_text(saved_path)
    if not text_content:
        cprint(f"  Cannot extract readable text from this file ({att['mime_type']}).", YELLOW)
        cprint(f"  File saved at: {saved_path}", GRAY)
        return

    cprint(f"  {GRAY}Summarizing…{RESET}")
    stream_local(
        f"Summarize the following document from an email attachment.\n"
        f"Filename: {att['filename']}\n\n"
        f"{text_content}\n\n"
        f"Give key points, numbers, dates, and any action items. Be concise.",
        system="You are Adwi summarizing an email attachment for Suneel. Be practical and brief."
    )


def cmd_gmail_rewrite_draft(text: str = "") -> None:
    """Rewrite the current draft body per instruction, update Gmail draft, show new preview."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft. Create one with 'reply saying X' or 'compose an email to X'.", YELLOW); return
    instruction = _extract_rewrite_instruction(text)
    if not instruction or len(instruction) < 3:
        instruction = input(f"  {YELLOW}Rewrite instruction (e.g. 'shorter', 'more professional'):{RESET} ").strip()
        if not instruction:
            cprint("  Cancelled.", GRAY); return
    adwi_head("Gmail — Rewrite Draft")
    cprint(f"  {GRAY}Rewriting: {instruction!r}…{RESET}")
    current_body = draft.get("body", "")
    prompt = (
        f"Rewrite this email body according to the instruction.\n"
        f"IMPORTANT: Preserve all specific dates, names, commitments, and facts unless the instruction explicitly says to change them.\n\n"
        f"Original email body:\n{current_body}\n\n"
        f"Rewrite instruction: {instruction}\n\n"
        f"Output ONLY the rewritten email body. No subject line. No explanation."
    )
    new_body = _llm_generate(
        prompt,
        system=(
            "You are rewriting an email draft for Suneel. "
            "Apply the tone/length/style instruction faithfully. "
            "Preserve all factual content (dates, commitments, names). "
            "Output only the new body text. No subject line."
        )
    )
    if not new_body or new_body.startswith("[LLM error"):
        cprint(f"  Rewrite failed: {new_body}", RED); return
    # Update draft in Gmail — preserve existing CC/BCC and outbound attachments
    try:
        gh       = _gmail()
        draft_id = draft["draft_id"]
        gh.update_draft(
            draft_id, draft["to"], draft["subject"], new_body,
            thread_id=draft.get("thread_id"),
            message_id_header=draft.get("message_id", ""),
            cc=draft.get("cc") or "",
            bcc=draft.get("bcc") or "",
            attachments=[a["path"] for a in draft.get("outbound_attachments") or []],
        )
    except Exception as e:
        cprint(f"  {YELLOW}Gmail draft update failed ({e}) — preview reflects new content.{RESET}")
    # Always update local context and show preview
    _GMAIL_CTX["draft"]["body"] = new_body
    cprint(f"  ✓ Draft rewritten", GREEN)
    _gmail_draft_preview(_GMAIL_CTX["draft"])


def cmd_gmail_update_subject(text: str = "") -> None:
    """Phase 14: Rewrite/update the subject line of the current draft."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft. Create one with 'compose an email to X' or 'reply saying X'.", YELLOW); return

    # Extract instruction: strip subject-meta preamble
    instruction = re.sub(
        r"^\s*(?:rewrite|update|change|improve|fix|make|give\s+me|write)\s+(?:the\s+)?(?:a\s+)?(?:better|clearer|shorter|stronger|good|clear|new|different|more\s+professional\s+)?subject(?:\s+line)?\s*(?:to\s+be\s+|to\s+|as\s+)?",
        "", text, flags=re.I
    ).strip()
    # If instruction is "to X" (literal new subject specified), use X directly
    literal_m = re.match(r"^(?:to|as)\s+['\"]?(.+?)['\"]?\s*$", instruction, re.I)
    if literal_m:
        new_subject = literal_m.group(1).strip().rstrip(".,?!")
    else:
        # LLM-generate a better subject from current body context + instruction
        adwi_head("Gmail — Update Subject")
        current_body   = draft.get("body", "")
        current_subject = draft.get("subject", "(no subject)")
        guidance = instruction if instruction else "Write a clear, concise subject line for this email."
        cprint(f"  {GRAY}Generating better subject…{RESET}")
        prompt = (
            f"Current email subject: {current_subject}\n\n"
            f"Email body:\n{current_body[:600]}\n\n"
            f"Task: {guidance}\n\n"
            f"Output ONLY the subject line text. No quotes, no 'Subject:', no explanation."
        )
        new_subject = _llm_generate(
            prompt,
            system="You are improving an email subject line. Output only the subject line text, nothing else.",
            max_tokens=60,
        ).strip().rstrip(".,?!")
        if not new_subject or new_subject.startswith("[LLM error"):
            cprint(f"  Could not generate subject: {new_subject}", RED); return

    old_subject = draft.get("subject", "(no subject)")
    adwi_head("Gmail — Update Subject")
    cprint(f"  Was:  {GRAY}{old_subject}{RESET}", "")
    cprint(f"  New:  {YELLOW}{new_subject}{RESET}", "")
    ans = input(f"  {YELLOW}Use this subject? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Kept original subject.", GRAY); return

    try:
        gh = _gmail()
        gh.update_draft(
            draft["draft_id"], draft["to"], new_subject, draft.get("body", ""),
            thread_id=draft.get("thread_id"),
            message_id_header=draft.get("message_id", ""),
            cc=draft.get("cc") or "",
            bcc=draft.get("bcc") or "",
            attachments=[a["path"] for a in draft.get("outbound_attachments") or []],
        )
    except Exception as exc:
        cprint(f"  {YELLOW}Gmail update failed ({exc}) — preview reflects new subject.{RESET}")
    _GMAIL_CTX["draft"]["subject"] = new_subject
    cprint(f"  {GREEN}✓ Subject updated.{RESET}")
    _gmail_draft_preview(_GMAIL_CTX["draft"])


def cmd_gmail_show_draft() -> None:
    """Show the current pending draft."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft. Use 'reply saying X' or 'compose an email to X'.", YELLOW); return
    adwi_head("Gmail — Current Draft")
    _gmail_draft_preview(draft)


def cmd_gmail_send_draft() -> None:
    """Send the current pending draft after one inline confirmation."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        if _GMAIL_CTX.get("pending"):
            cprint("  No draft to send. Did you mean 'confirm' to apply your pending Gmail action?", YELLOW)
        else:
            cprint("  No draft. Create one with 'reply saying X' or 'compose an email to X'.", YELLOW)
        return
    draft_id = draft.get("draft_id")
    to       = draft.get("to", "")
    cc       = draft.get("cc") or ""
    bcc      = draft.get("bcc") or ""
    subject  = draft.get("subject", "")
    adwi_head("Gmail — Send Draft")
    cprint(f"  To:      {to}", "")
    if cc:  cprint(f"  CC:      {cc}", "")
    if bcc: cprint(f"  BCC:     {bcc}", "")
    cprint(f"  Subject: {subject}", "")
    ans = input(f"  {YELLOW}Send this email? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Cancelled — draft still saved in Gmail.", GRAY); return
    try:
        gh     = _gmail()
        result = gh.send_draft(draft_id)
        # Capture last_sent before clearing draft (Phase 11: follow-up reminders use this)
        _GMAIL_CTX["last_sent"] = {
            "thread_id":    result.get("threadId", ""),
            "message_id":   result.get("id", ""),
            "to":           to,
            "subject":      subject,
            "sent_at_iso":  datetime.now().isoformat(timespec="seconds"),
            "sent_at_ms":   int(datetime.now().timestamp() * 1000),
        }
        _GMAIL_CTX["draft"] = None
        cprint(f"  ✓ Sent (id: {result.get('id','?')[:16]}…)", GREEN)
        cprint("  Tip: say 'remind me if no reply in 3 days' to set a follow-up reminder.", GRAY)
    except Exception as e:
        cprint(f"  Send failed: {e}", RED)
        if "403" in str(e) or "scope" in str(e).lower() or "Insufficient" in str(e):
            cprint("  Scope issue — run /gmail-auth to re-authorize with gmail.modify.", YELLOW)


def cmd_gmail_cancel_draft() -> None:
    """Cancel and delete the current pending draft from Gmail."""
    draft = _GMAIL_CTX.get("draft")
    if not draft:
        cprint("  No current draft.", GRAY); return
    draft_id = draft.get("draft_id")
    to       = (draft.get("to") or "")[:50]
    subject  = (draft.get("subject") or "")[:50]
    adwi_head("Gmail — Cancel Draft")
    cprint(f"  Draft to: {to} — Subject: {subject}", GRAY)
    ans = input(f"  {YELLOW}Delete this draft? (y/n){RESET} ").strip().lower()
    if ans not in ("y", "yes"):
        cprint("  Kept.", GRAY); return
    try:
        if draft_id:
            gh = _gmail()
            gh.delete_draft(draft_id)
    except Exception as e:
        cprint(f"  Error deleting draft from Gmail: {e}", RED)
    finally:
        _GMAIL_CTX["draft"] = None  # Always clear local state
        cprint("  Draft cancelled.", GRAY)


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


# ── Voice I/O commands (Pillar C) ────────────────────────────────────────────
def cmd_voice_in() -> None:
    """Record mic, transcribe with faster-whisper, dispatch as natural language."""
    adwi_head("Voice input — speak now")
    try:
        from adwi.voice import cmd_voice_in_impl
    except ImportError:
        try:
            import importlib.util, sys as _sys
            spec = importlib.util.spec_from_file_location("voice", ADWI_DIR / "voice.py")
            _mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mod)
            cmd_voice_in_impl = _mod.cmd_voice_in_impl
        except Exception as e:
            cprint(f"  Voice module unavailable: {e}", RED)
            return
    text = cmd_voice_in_impl()
    if text:
        cprint(f"\n  Heard: {CYAN}{text}{RESET}", "")
        dispatch_natural(text)
    else:
        cprint("  No speech detected.", YELLOW)


def cmd_voice_out(text: str = "") -> None:
    """Synthesize text to speech via piper-tts and play via afplay."""
    if not text.strip():
        text = input(f"  {CYAN}Text to speak:{RESET} ").strip()
    if not text:
        return
    adwi_head("Voice output")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("voice", ADWI_DIR / "voice.py")
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
        _mod.cmd_voice_out_impl(text)
        cprint("  Done.", GREEN)
    except Exception as e:
        cprint(f"  TTS unavailable: {e}", RED)


def cmd_voice_brief() -> None:
    """Read the morning brief aloud via piper-tts."""
    brief = Path.home() / "Desktop" / "morning_brief.md"
    if not brief.exists():
        cprint("  No morning brief found at ~/Desktop/morning_brief.md", YELLOW)
        return
    content = brief.read_text(encoding="utf-8")
    # Strip markdown headers/bullets for cleaner speech
    clean = re.sub(r"^#+\s*", "", content, flags=re.M)
    clean = re.sub(r"^[-*]\s*", "", clean, flags=re.M)
    clean = re.sub(r"`[^`]*`", "", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    cmd_voice_out(clean[:3000])  # cap to avoid 20-min sessions


# ── Aliases for preserved commands (/gemini, /owui) ──────────────────────────
# ── Pillar B: Remote access + Home Assistant ──────────────────────────────────
def cmd_remote_status() -> None:
    """Show Tailscale, cloudflared, and Home Assistant connectivity."""
    adwi_head("Remote Access Status")

    # Tailscale
    try:
        import json as _json
        r = subprocess.run(["tailscale", "status", "--json"],
                          capture_output=True, text=True, timeout=5)
        ts = _json.loads(r.stdout)
        my_ip = ts.get("TailscaleIPs", ["—"])[0]
        peers = len(ts.get("Peer", {}))
        cprint(f"  ✓ Tailscale:         {my_ip}  ({peers} peers)", GREEN)
    except Exception:
        cprint(f"  ✗ Tailscale:         not connected", YELLOW)

    # Cloudflared
    cf_status = subprocess.run(
        ["docker", "ps", "--filter", "name=suneel-cloudflared", "--format", "{{.Status}}"],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    if cf_status and "Up" in cf_status:
        cprint(f"  ✓ Cloudflare Tunnel: {cf_status}", GREEN)
    else:
        cprint(f"  ✗ Cloudflare Tunnel: not running", YELLOW)

    # Home Assistant
    if HA_TOKEN:
        try:
            req = urllib.request.Request(
                f"{HA_URL}/api/",
                headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.load(r)
            cprint(f"  ✓ Home Assistant:    {HA_URL} — {data.get('message', 'ok')}", GREEN)
        except Exception as e:
            cprint(f"  ✗ Home Assistant:    {HA_URL} — {e}", YELLOW)
    else:
        cprint(f"  ⚠ Home Assistant:    token not set (see iphone-control-plane.md)", YELLOW)

    # Remote access URLs
    if TAILSCALE_IP:
        cprint(f"\n  Remote access (via Tailscale from iPhone):", CYAN, bold=True)
        cprint(f"    Open WebUI:         http://{TAILSCALE_IP}:3000", GRAY)
        cprint(f"    Home Assistant:     http://{TAILSCALE_IP}:8123", GRAY)
        cprint(f"    n8n:                http://{TAILSCALE_IP}:5678", GRAY)
        cprint(f"    Phoenix traces:     http://{TAILSCALE_IP}:6006", GRAY)


def cmd_ha(query: str = "") -> None:
    """Query Home Assistant API. Usage: /ha <entity_id|state|services>"""
    if not HA_TOKEN:
        adwi_say("Home Assistant token not set. Add HOME_ASSISTANT_TOKEN to config/.env\n"
                 "Get it from: http://localhost:8123 → Profile → Security → Long-Lived Access Tokens")
        return
    if not query:
        query = "states"

    # Map friendly queries to HA API endpoints
    endpoint_map = {
        "state": "states",
        "states": "states",
        "services": "services",
        "config": "config",
        "events": "events",
        "history": "history/period",
        "logbook": "logbook",
        "status": "config",
    }
    ep = endpoint_map.get(query.lower(), f"states/{query}")
    url = f"{HA_URL}/api/{ep}"

    adwi_head(f"Home Assistant — {ep}")
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        if isinstance(data, list):
            cprint(f"  {len(data)} entities", CYAN)
            for item in data[:20]:
                if isinstance(item, dict):
                    eid   = item.get("entity_id", "")
                    state = item.get("state", "")
                    name  = item.get("attributes", {}).get("friendly_name", eid)
                    cprint(f"  {name:<30} {state}", GRAY)
            if len(data) > 20:
                cprint(f"  … and {len(data)-20} more", GRAY)
        else:
            adwi_say(json.dumps(data, indent=2)[:1000])
    except urllib.error.HTTPError as e:
        cprint(f"  HA API error: {e.code} {e.reason}", RED)
    except Exception as e:
        cprint(f"  Error: {e}", RED)


def cmd_notify(message: str = "", title: str = "Adwi") -> None:
    """Push a notification to iPhone via HA. Usage: /notify <message>"""
    if not HA_TOKEN:
        adwi_say("HOME_ASSISTANT_TOKEN not set in config/.env")
        return
    if not message:
        message = input(f"  {CYAN}Notification message:{RESET} ").strip()
    if not message:
        return
    payload = json.dumps({
        "message": message,
        "title": title,
        "data": {"push": {"sound": "default"}},
    }).encode()
    req = urllib.request.Request(
        f"{HA_URL}/api/services/notify/mobile_app_the_suns_iphone",
        data=payload,
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=8)
        cprint(f"  ✓ Notification sent: {message}", GREEN)
    except Exception as e:
        cprint(f"  ✗ Failed: {e}", RED)


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
    intent  = intent_data.get("intent", "chat")
    target  = intent_data.get("target")
    args    = intent_data.get("arguments") or {}
    analysis = intent_data.get("analysis", "")

    # SimLab eval hook — completely inert unless ADWI_EVAL_OUTPUT_JSON is set
    # by the EvalRunner. Never executes in production (env var never set there).
    _simlab_out = os.environ.get("ADWI_EVAL_OUTPUT_JSON")
    if _simlab_out:
        try:
            with open(_simlab_out, "w", encoding="utf-8") as _sf:
                json.dump({
                    "intent":     intent,
                    "confidence": intent_data.get("confidence", 0),
                    "args":       args,
                    "analysis":   analysis[:200],
                }, _sf)
        except Exception:
            pass

    # Clear the thinking indicator
    print("    ", end="\r", flush=True)

    # Emit Chain-of-Intent analysis to OTEL span for observability
    if analysis:
        with _otel_span("dispatch_natural.analysis", {
            "nlu.analysis": analysis[:300],
            "nlu.intent": intent,
            "nlu.confidence": str(intent_data.get("confidence", "")),
        }):
            pass

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
        cmd_disk_usage(args.get("path") or target)
    elif intent == "large_files":
        # Prefer structured slot; fall back to text regex for robustness
        if args.get("size_mb"):
            min_mb = int(args["size_mb"])
        else:
            m = re.search(r"(\d+)\s*(gb|mb|g|m)\b", text, re.I)
            min_mb = int(m.group(1)) * (1024 if m.group(2).lower() in ("gb","g") else 1) if m else 200
        cmd_large_files(args.get("path") or target, min_mb=min_mb)
    elif intent == "old_files":
        if args.get("days"):
            days = int(args["days"])
        else:
            m = re.search(r"(\d+)\s*(year|month|day)", text, re.I)
            days = int(m.group(1)) * (365 if "year" in m.group(2) else 30 if "month" in m.group(2) else 1) if m else 365
        cmd_old_files(args.get("path") or target, days=days)
    elif intent == "duplicates":
        cmd_find_duplicates(target)
    elif intent == "organize":
        cmd_organize_suggest(target)
    elif intent == "cleanup":
        cmd_cleanup_suggest(target)
    elif intent == "file_read":
        p = args.get("path") or target
        if p:
            cmd_read_file(p)
        else:
            path_str = input(f"  {CYAN}Which file to read?{RESET} ").strip()
            if path_str: cmd_read_file(path_str)
    elif intent == "file_search":
        q = args.get("query") or target or text
        cmd_file_search(q)
    elif intent == "file_list":
        cmd_list_folder(args.get("path") or target or str(HOME))
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
    elif intent == "fix_error":
        # User pasted a runtime error/traceback — route to cmd_fix_error
        cmd_fix_error(args.get("query") or target or text)
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
        q = (args.get("query") or target or
             re.sub(r"^(search the web for|web search|google|search online for|look up online|find online)\s*", "", text, flags=re.I).strip())
        cmd_web_search(q or text)
    elif intent == "obsidian_search":
        q = (args.get("query") or target or
             re.sub(r"^(obsidian|vault|my notes?|open|read|show)\s*", "", text, flags=re.I).strip())
        cmd_obsidian_search(q or text)
    elif intent == "browse":
        url = args.get("url") or target or text
        cmd_browse(url)
    elif intent == "github_visibility":
        cmd_github_visibility(text)
    elif intent == "github_connected":
        cmd_github_connected()
    elif intent == "git_status":
        cmd_git("status")
    elif intent == "generate_image":
        desc = (args.get("description") or target or
                re.sub(r"^(generate|create|draw|make|design)\s*(an?\s*)?(image|picture|photo|illustration|artwork)\s*(of|showing|with)?\s*", "", text, flags=re.I).strip())
        cmd_generate_image(desc or text)
    elif intent == "run_code":
        code = _extract_code(text)
        cmd_run_python(code or text)
    elif intent == "benchmark":
        cmd_benchmark()
    elif intent == "memory_scan":
        cmd_memory_scan()
    elif intent == "memory_recall":
        q = (args.get("query") or target or
             re.sub(r"^(remember|recall|what do you know about)\s*", "", text, flags=re.I).strip())
        cmd_memory_recall(q)
    elif intent == "memory_stats":
        cmd_memory_stats()
    elif intent == "route":
        q = (args.get("query") or target or
             re.sub(r"^(route|which tool).{0,30}?\s", "", text, flags=re.I).strip())
        cmd_route(q)
    elif intent == "gmail_open":
        from_m  = re.search(r"\bfrom\s+(\w[\w\s.@]{0,30}?)(?:\s+about|\s+today|\s+yesterday|[?.]|$)", text, re.I)
        about_m = re.search(r"\babout\s+(.+?)(?:\s+from|\s+today|\s+yesterday|[?.]|$)", text, re.I)
        time_m  = re.search(r"\b(today|yesterday|this week|last week|this month)\b", text, re.I)
        parts = []
        if from_m:  parts.append(f"from:{from_m.group(1).strip()}")
        if about_m: parts.append(about_m.group(1).strip())
        if time_m:
            t = time_m.group(1).lower()
            if t == "today":               parts.append("newer_than:1d")
            elif t == "yesterday":         parts.append("after:yesterday before:today")
            elif "week" in t:              parts.append("newer_than:7d")
            elif t == "this month":        parts.append("newer_than:30d")
        query_str = " ".join(parts) or (args.get("query") or "")
        cmd_gmail_open(query_str)
    elif intent == "gmail_thread":
        about_m = re.search(r"\babout\s+(.+?)(?:\s+from|\s+today|[?.]|$)", text, re.I)
        from_m  = re.search(r"\bfrom\s+(\w[\w\s]{0,20}?)(?:\s+about|[?.]|$)", text, re.I)
        if about_m:      cmd_gmail_thread(about_m.group(1).strip())
        elif from_m:     cmd_gmail_thread(f"from:{from_m.group(1).strip()}")
        else:            cmd_gmail_thread()
    elif intent == "gmail_summarize":
        want_thread = bool(re.search(r"\bthread|conversation\b", text, re.I))
        _meta = r"\b(summarize|tldr|tl;dr|summary|thread|conversation|of|a|an|the|my)\b"
        clean = re.sub(_meta, "", text, flags=re.I).strip(" ,.-")
        # Strip action words that aren't content
        clean = re.sub(r"\b(email|mail|message|this|that|it)\b", "", clean, flags=re.I).strip(" ,.-")
        # Preserve "from:X" and "about:X" qualifiers
        from_m  = re.search(r"\bfrom\s+(\w[\w\s.]{0,25}?)(?:\s+about|[?.]|$)", text, re.I)
        about_m = re.search(r"\babout\s+(.+?)(?:\s+from|[?.]|$)", text, re.I)
        if from_m:       cmd_gmail_summarize(f"from:{from_m.group(1).strip()}" + (" thread" if want_thread else ""))
        elif about_m:    cmd_gmail_summarize(about_m.group(1).strip() + (" thread" if want_thread else ""))
        elif clean:      cmd_gmail_summarize(clean + (" thread" if want_thread else ""))
        else:            cmd_gmail_summarize("thread" if want_thread else "")
    elif intent == "gmail_list_category":
        m = re.search(r"\b(promotions?|promo|promotional|newsletters?|social|updates?|forums?|spam)\b", text, re.I)
        cmd_gmail_list_category(m.group(1) if m else "promotions")
    elif intent == "gmail_archive":
        cmd_gmail_archive(text)
    elif intent == "gmail_trash":
        cmd_gmail_trash_emails(text)
    elif intent == "gmail_mark_read":
        cmd_gmail_mark_read(text)
    elif intent == "gmail_mark_unread":
        cmd_gmail_mark_unread(text)
    elif intent == "gmail_confirm":
        # Context-aware: confirm pending mutation (Phase 2) OR send pending draft (Phase 3)
        if _GMAIL_CTX.get("pending"):
            cmd_gmail_confirm()
        elif _GMAIL_CTX.get("draft"):
            cmd_gmail_send_draft()
        else:
            cprint("  No pending Gmail action or draft to confirm.", YELLOW)
    elif intent == "gmail_cancel":
        cmd_gmail_cancel()
    elif intent == "gmail_undo":
        cmd_gmail_undo()
    elif intent == "gmail_draft_reply":
        instruction = re.sub(
            r"^\s*(?:draft\s+a?\s*)?(?:reply|response|write\s+back)\s*(?:saying|that|with|to\s+(?:it|this|that))?\s*",
            "", text, flags=re.I
        ).strip() or text
        cmd_gmail_draft_reply(instruction)
    elif intent == "gmail_compose":
        cmd_gmail_compose(text)
    elif intent == "gmail_show_draft":
        cmd_gmail_show_draft()
    elif intent == "gmail_send_draft":
        cmd_gmail_send_draft()
    elif intent == "gmail_cancel_draft":
        cmd_gmail_cancel_draft()
    elif intent == "gmail_rewrite_draft":
        cmd_gmail_rewrite_draft(text)
    elif intent == "gmail_update_subject":
        cmd_gmail_update_subject(text)
    elif intent == "gmail_add_cc":
        cmd_gmail_add_cc(text)
    elif intent == "gmail_add_bcc":
        cmd_gmail_add_bcc(text)
    elif intent == "gmail_attach_file":
        cmd_gmail_attach_file(text)
    elif intent == "gmail_remove_attachment":
        cmd_gmail_remove_attachment(text)
    elif intent == "gmail_triage":
        cmd_gmail_triage(text)
    elif intent == "gmail_schedule_send":
        cmd_gmail_schedule_send(text)
    elif intent == "gmail_list_scheduled":
        cmd_gmail_list_scheduled()
    elif intent == "gmail_cancel_scheduled_send":
        cmd_gmail_cancel_scheduled_send(text)
    elif intent == "gmail_reschedule_send":
        cmd_gmail_reschedule_send(text)
    elif intent == "gmail_open_scheduled_draft":
        cmd_gmail_open_scheduled_draft(text)
    elif intent == "gmail_extract_tasks":
        cmd_gmail_extract_tasks(text)
    elif intent == "gmail_tasks_save":
        cmd_gmail_tasks_save(text)
    elif intent == "gmail_tasks_remind":
        cmd_gmail_tasks_remind(text)
    elif intent == "gmail_followup_reminder":
        cmd_gmail_followup_reminder(text)
    elif intent == "gmail_list_followups":
        cmd_gmail_list_followups()
    elif intent == "gmail_cancel_followup":
        cmd_gmail_cancel_followup(text)
    elif intent == "gmail_list_drafts":
        cmd_gmail_list_drafts(text)
    elif intent == "gmail_open_draft":
        cmd_gmail_open_draft(text)
    elif intent == "gmail_delete_draft":
        cmd_gmail_delete_draft(text)
    elif intent == "gmail_thread_intel":
        cmd_gmail_thread_intel(text)
    elif intent == "gmail_forward":
        cmd_gmail_forward(text)
    elif intent == "gmail_filter_build":
        cmd_gmail_filter_build(text)
    elif intent == "gmail_filter_apply":
        cmd_gmail_filter_apply(text)
    elif intent == "gmail_filter_cancel":
        cmd_gmail_filter_cancel(text)
    elif intent == "gmail_filter_list":
        cmd_gmail_filter_list(text)
    elif intent == "gmail_list_attachments":
        cmd_gmail_list_attachments(text)
    elif intent == "gmail_save_attachment":
        cmd_gmail_save_attachment(text)
    elif intent == "gmail_summarize_attachment":
        cmd_gmail_summarize_attachment(text)
    elif intent == "gmail_read":
        if re.search(r"\bthis\s+(email|mail|message)\b", text, re.I):
            frag = re.sub(r".*?\bthis\s+(email|mail|message)\s*", "", text, flags=re.I).strip()
            if frag and _GMAIL_SUBJECTS:
                for idx, subj in enumerate(_GMAIL_SUBJECTS):
                    if frag[:30].lower() in subj.lower():
                        cmd_gmail_read(str(idx + 1)); break
                else:
                    cmd_gmail_read("1")
            else:
                cmd_gmail_read("1")
        else:
            m_num = re.search(r"\b#?(\d{1,2})\b", text)
            if m_num:
                cmd_gmail_read(m_num.group(1))
            elif re.search(r"\b(latest|newest|first|top|most\s+recent)\b", text, re.I):
                cmd_gmail_read("1")
            else:
                cmd_gmail_read("1")
    elif intent == "gmail":
        # Prefer structured query slot from LLM; fall back to text heuristics
        structured_q = args.get("query")
        if structured_q:
            cmd_gmail(query=structured_q)
        else:
            is_question = bool(re.search(r"\b(is|are|how many|do i have|connected|working)\b", text, re.I))
            from_match  = re.search(r"\bfrom\s+(\w[\w\s]{0,30}?)(?:\s+about|\s+today|\s+yesterday|[?.]|$)", text, re.I)
            about_match = re.search(r"\babout\s+(.+?)(?:\s+from|\s+today|\s+yesterday|[?.]|$)", text, re.I)
            unread      = "unread" in text.lower()
            today       = "today"     in text.lower()
            yesterday   = "yesterday" in text.lower()
            # Combine qualifiers: "unread emails from Rahul" → from + unread filter
            if from_match:
                q = f"from:{from_match.group(1).strip()}"
                if unread: q = f"is:unread {q}"
                cmd_gmail(query=q)
            elif about_match and not is_question:
                q = about_match.group(1).strip()
                if unread: q = f"is:unread {q}"
                cmd_gmail(query=q)
            elif unread:    cmd_gmail(query="is:unread")
            elif today:     cmd_gmail(query="newer_than:1d")
            elif yesterday: cmd_gmail(query="after:yesterday before:today")
            else:           cmd_gmail()
    elif intent == "memory_context":
        q = (args.get("query") or target or
             re.sub(r"^(memory context|context for|show context)\s*", "", text, flags=re.I).strip())
        cmd_memory_context(q)
    elif intent == "nightly_status":
        cmd_nightly_status()
    elif intent == "nightly_run":
        cmd_nightly_run()
    elif intent == "patch_adwi":
        hint = (args.get("query") or args.get("target") or
                re.sub(r"^(patch|fix|repair|heal)\s*(adwi)?\s*", "", text, flags=re.I).strip())
        cmd_patch_adwi(hint)
    elif intent == "doctor":
        cmd_doctor()
    elif intent == "exa_search":
        q = (args.get("query") or target or
             re.sub(r"^(exa|search exa)\s*", "", text, flags=re.I).strip())
        cmd_exa_search(q)
    elif intent == "tavily_search":
        q = (args.get("query") or target or
             re.sub(r"^(tavily|search tavily)\s*", "", text, flags=re.I).strip())
        cmd_tavily_search(q)
    elif intent == "firecrawl":
        cmd_firecrawl(args.get("url") or args.get("query") or target or "")
    elif intent == "obsidian_read":
        cmd_obsidian_read(args.get("path") or args.get("query") or target or "")
    elif intent == "obsidian_write":
        cmd_obsidian_write(args.get("path") or args.get("query") or target or "")
    elif intent == "obsidian_daily":
        cmd_obsidian_daily()
    elif intent == "backup_now":
        cmd_backup_now()
    elif intent == "backup_status":
        cmd_backup_status()
    elif intent == "backup_log":
        cmd_backup_log()
    elif intent == "voice_in":
        cmd_voice_in()
    elif intent == "voice_out":
        q = (args.get("query") or args.get("description") or target or
             re.sub(r"^(speak|say|read aloud|voice out)\s*", "", text, flags=re.I).strip())
        cmd_voice_out(q)
    elif intent == "extract_ideas":
        cmd_extract_ideas(args.get("path") or args.get("query") or target or "")
    elif intent == "trusted_roots":
        cmd_trusted_roots()
    elif intent == "eval_routing":
        cmd_eval_routing()
    elif intent == "eval_adwi":
        cmd_eval_adwi()
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
_SHELL_CMD_RE = re.compile(
    r"^(export|cd|pwd|rm|mv|cp|mkdir|chmod|chown|sudo|brew|pip|npm|yarn|bash|zsh|curl|wget|killall|kill|unset|alias|which|printenv)\s",
    re.I,
)
# `source` only looks like a shell command when followed by a path (/, ~, .) — not "source code"
_SOURCE_CMD_RE = re.compile(r"^source\s+[/~.]", re.I)

def handle(line: str) -> bool:
    global _SESSION_MAX_TURNS
    line = line.strip()
    if not line: return True
    low = line.lower()

    # Phase 4: recipient disambiguation — bare digit selection when pending_recipient is set
    if _GMAIL_CTX.get("pending_recipient") and re.match(r'^[1-9]$', line):
        cmd_gmail_recipient_choice(int(line))
        return True

    # Phase 7: outbound-attachment file disambiguation — bare digit when pending_attach is set
    if _GMAIL_CTX.get("pending_attach") and re.match(r'^[1-9]$', line):
        cmd_gmail_attach_choice(int(line))
        return True

    # Detect shell commands typed by mistake into the adwi prompt
    if _SHELL_CMD_RE.match(line) or _SOURCE_CMD_RE.match(line):
        cmd_word = line.split()[0]
        adwi_say(
            f"That looks like a shell command (`{cmd_word}`). "
            f"Adwi can't run shell environment commands directly — "
            f"please run it in your terminal instead.\n\n"
            f"  $ {line}"
        )
        return True

    # Exit
    if line in ["/exit","/quit","/bye","exit","quit"]:
        print(f"\n{CYAN}Adwi:{RESET} Bye, Suneel. 👋\n"); return False

    # Clear screen
    if line.lower() in ("clear", "/clear", "cls", "/cls"):
        import subprocess as _sp; _sp.run("clear", shell=True); return True

    # ── Session context management ────────────────────────────────────────────
    if line in ("/clear-context", "/new-session", "/reset-context"):
        _SESSION_HISTORY.clear()
        cprint(f"  ✓ Session context cleared — starting fresh.", GREEN)
        return True
    if line == "/session-history":
        if not _SESSION_HISTORY:
            cprint("  No session history yet.", GRAY)
        else:
            cprint(f"\n  Session history — {len(_SESSION_HISTORY)//2} turn(s)  "
                   f"(max {_SESSION_MAX_TURNS}):\n", CYAN)
            for i, msg in enumerate(_SESSION_HISTORY):
                role  = "You" if msg["role"] == "user" else "Adwi"
                color = YELLOW if msg["role"] == "user" else CYAN
                body  = msg["content"][:120].replace("/no_think\n", "")
                dots  = "…" if len(msg["content"]) > 120 else ""
                cprint(f"  {color}{role}:{RESET} {body}{dots}", "")
        return True
    if line.startswith("/context-size "):
        try:
            n = int(line.split()[1])
            if 1 <= n <= 100:
                _SESSION_MAX_TURNS = n
                cprint(f"  ✓ Session context window set to {n} turns.", GREEN)
            else:
                cprint("  Out of range — use 1–100.", YELLOW)
        except ValueError:
            cprint("  Usage: /context-size <number>  (e.g. /context-size 20)", YELLOW)
        return True

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
        task = line[8:].strip()
        adwi_head(f"Reason Engine → {task[:60]}")
        try:
            import importlib.util as _ilu
            _rspec = _ilu.spec_from_file_location("reason_engine", ADWI_DIR / "reason_engine.py")
            _rmod  = _ilu.module_from_spec(_rspec)
            _rspec.loader.exec_module(_rmod)
            adwi_say(_rmod.run_reason(task, interactive=True))
        except Exception as _re:
            activity_warning(f"Reason engine unavailable ({_re}), falling back to cloud")
            adwi_say(call_cloud(
                f"Complex reasoning request from Suneel:\n\n{task}\n\n"
                "Think step by step. Flag risks. Be specific."
            ) if _cloud_ok() else stream_local(task))
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
    elif line.startswith("/gmail-open "): cmd_gmail_open(line[12:].strip())
    elif line == "/gmail-thread": cmd_gmail_thread()
    elif line.startswith("/gmail-thread "): cmd_gmail_thread(line[14:].strip())
    elif line == "/gmail-summarize": cmd_gmail_summarize()
    elif line.startswith("/gmail-summarize "): cmd_gmail_summarize(line[17:].strip())
    elif line == "/gmail-promos": cmd_gmail_list_category("promotions")
    elif line == "/gmail-spam": cmd_gmail_list_category("spam")
    elif line == "/gmail-social": cmd_gmail_list_category("social")
    elif line.startswith("/gmail-category "): cmd_gmail_list_category(line[16:].strip())
    elif line == "/gmail-archive": cmd_gmail_archive("")
    elif line.startswith("/gmail-archive "): cmd_gmail_archive(line[15:].strip())
    elif line == "/gmail-trash": cmd_gmail_trash_emails("")
    elif line.startswith("/gmail-trash "): cmd_gmail_trash_emails(line[13:].strip())
    elif line == "/gmail-mark-read": cmd_gmail_mark_read("")
    elif line.startswith("/gmail-mark-read "): cmd_gmail_mark_read(line[17:].strip())
    elif line == "/gmail-mark-unread": cmd_gmail_mark_unread("")
    elif line.startswith("/gmail-mark-unread "): cmd_gmail_mark_unread(line[19:].strip())
    elif line in ("/gmail-confirm", "/confirm"): cmd_gmail_confirm()
    elif line == "/gmail-cancel": cmd_gmail_cancel()
    elif line == "/gmail-undo": cmd_gmail_undo()
    elif line == "/gmail-draft-reply": cmd_gmail_draft_reply("")
    elif line.startswith("/gmail-draft-reply "): cmd_gmail_draft_reply(line[19:].strip())
    elif line == "/gmail-thread-intel": cmd_gmail_thread_intel("")
    elif line.startswith("/gmail-thread-intel "): cmd_gmail_thread_intel(line[20:].strip())
    elif line == "/gmail-forward": cmd_gmail_forward("")
    elif line.startswith("/gmail-forward "): cmd_gmail_forward(line[15:].strip())
    elif line == "/gmail-rule": cmd_gmail_filter_build("")
    elif line.startswith("/gmail-rule "): cmd_gmail_filter_build(line[12:].strip())
    elif line == "/gmail-rule-apply": cmd_gmail_filter_apply("")
    elif line == "/gmail-rule-cancel": cmd_gmail_filter_cancel("")
    elif line == "/gmail-rules": cmd_gmail_filter_list("")
    elif line == "/gmail-compose": cmd_gmail_compose("")
    elif line.startswith("/gmail-compose "): cmd_gmail_compose(line[15:].strip())
    elif line == "/gmail-show-draft": cmd_gmail_show_draft()
    elif line == "/gmail-send-draft": cmd_gmail_send_draft()
    elif line == "/gmail-cancel-draft": cmd_gmail_cancel_draft()
    elif line == "/gmail-rewrite": cmd_gmail_rewrite_draft("")
    elif line.startswith("/gmail-rewrite "): cmd_gmail_rewrite_draft(line[15:].strip())
    elif line == "/gmail-update-subject": cmd_gmail_update_subject("")
    elif line.startswith("/gmail-update-subject "): cmd_gmail_update_subject(line[22:].strip())
    elif line == "/gmail-add-cc": cmd_gmail_add_cc("")
    elif line.startswith("/gmail-add-cc "): cmd_gmail_add_cc(line[14:].strip())
    elif line == "/gmail-add-bcc": cmd_gmail_add_bcc("")
    elif line.startswith("/gmail-add-bcc "): cmd_gmail_add_bcc(line[15:].strip())
    elif line == "/gmail-attachments": cmd_gmail_list_attachments("")
    elif line.startswith("/gmail-attachments "): cmd_gmail_list_attachments(line[19:].strip())
    elif line == "/gmail-save-attachment": cmd_gmail_save_attachment("")
    elif line.startswith("/gmail-save-attachment "): cmd_gmail_save_attachment(line[23:].strip())
    elif line == "/gmail-summarize-attachment": cmd_gmail_summarize_attachment("")
    elif line.startswith("/gmail-summarize-attachment "): cmd_gmail_summarize_attachment(line[28:].strip())
    elif line == "/gmail-attach": cmd_gmail_attach_file("")
    elif line.startswith("/gmail-attach "): cmd_gmail_attach_file(line[14:].strip())
    elif line == "/gmail-remove-attachment": cmd_gmail_remove_attachment("")
    elif line.startswith("/gmail-remove-attachment "): cmd_gmail_remove_attachment(line[25:].strip())
    elif line == "/gmail-triage": cmd_gmail_triage("")
    elif line.startswith("/gmail-triage "): cmd_gmail_triage(line[14:].strip())
    elif line.startswith("/gmail-schedule "): cmd_gmail_schedule_send(line[16:].strip())
    elif line == "/gmail-scheduled": cmd_gmail_list_scheduled()
    elif line == "/gmail-cancel-scheduled": cmd_gmail_cancel_scheduled_send("")
    elif line.startswith("/gmail-cancel-scheduled "): cmd_gmail_cancel_scheduled_send(line[24:].strip())
    elif line == "/gmail-reschedule": cmd_gmail_reschedule_send("")
    elif line.startswith("/gmail-reschedule "): cmd_gmail_reschedule_send(line[18:].strip())
    elif line == "/gmail-open-scheduled": cmd_gmail_open_scheduled_draft("")
    elif line.startswith("/gmail-open-scheduled "): cmd_gmail_open_scheduled_draft(line[22:].strip())
    elif line == "/gmail-extract-tasks": cmd_gmail_extract_tasks("")
    elif line.startswith("/gmail-extract-tasks "): cmd_gmail_extract_tasks(line[21:].strip())
    elif line == "/gmail-tasks-save": cmd_gmail_tasks_save("")
    elif line == "/gmail-tasks-remind": cmd_gmail_tasks_remind("")
    elif line.startswith("/gmail-followup "): cmd_gmail_followup_reminder(line[16:].strip())
    elif line == "/gmail-followup": cmd_gmail_followup_reminder("")
    elif line == "/gmail-followups": cmd_gmail_list_followups()
    elif line == "/gmail-cancel-followup": cmd_gmail_cancel_followup("")
    elif line.startswith("/gmail-cancel-followup "): cmd_gmail_cancel_followup(line[23:].strip())
    elif line == "/gmail-drafts": cmd_gmail_list_drafts("")
    elif line.startswith("/gmail-drafts "): cmd_gmail_list_drafts(line[14:].strip())
    elif line == "/gmail-open-draft": cmd_gmail_open_draft("")
    elif line.startswith("/gmail-open-draft "): cmd_gmail_open_draft(line[18:].strip())
    elif line == "/gmail-delete-draft": cmd_gmail_delete_draft("")
    elif line.startswith("/gmail-delete-draft "): cmd_gmail_delete_draft(line[20:].strip())
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
    # ── Voice I/O (Pillar C) ──
    elif line in ("/voice-in", "/voice", "/listen"): cmd_voice_in()
    elif line.startswith("/voice-out "): cmd_voice_out(line[11:].strip())
    elif line == "/voice-out": cmd_voice_out()
    elif line == "/voice-brief": cmd_voice_brief()
    # ── Pillar B: Remote / HA ──
    elif line in ("/remote-status", "/remote", "/tailscale"): cmd_remote_status()
    elif line.startswith("/ha "): cmd_ha(line[4:].strip())
    elif line == "/ha": cmd_ha()
    elif line.startswith("/notify "): cmd_notify(line[8:].strip())
    elif line == "/notify": cmd_notify()
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

    @kb.add("escape", "enter")   # Option+Enter / Alt+Enter on Mac → newline
    def newline(e): e.current_buffer.insert_text("\n")

    @kb.add("c-d")
    def ctrl_d(e):
        if e.current_buffer.text.strip():
            e.current_buffer.validate_and_handle()
        else:
            raise EOFError

    style = Style.from_dict({
        # Prompt
        "prompt":                                "#00bcd4 bold",
        # Status bar
        "bottom-toolbar":                        "bg:#111111 #555555",
        # Completion dropdown
        "completion-menu.completion":            "bg:#1c1c2e #9090cc",
        "completion-menu.completion.current":    "bg:#00bcd4 #000000 bold",
        # Meta column (right-side description)
        "completion-menu.meta.completion":       "bg:#111122 #555577",
        "completion-menu.meta.completion.current": "bg:#008fa8 #ddeeff",
        # Scrollbar
        "scrollbar.background":                  "bg:#1c1c2e",
        "scrollbar.button":                      "bg:#00bcd4",
    })

    toolbar = (
        "  /  = command menu  ·  Tab = complete  ·  ↑↓ = history  ·  "
        "Option+Enter = newline  ·  /help  ·  /exit"
    )

    return PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        key_bindings=kb,
        style=style,
        multiline=True,
        prompt_continuation=lambda *a: "  … ",
        bottom_toolbar=HTML(f"<b>{toolbar}</b>"),
        mouse_support=False,
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
        complete_in_thread=True,   # run completion in background thread → no input lag
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

# ── Slash-command completion registry ────────────────────────────────────────
# Two-pass build:
#   Pass 1 — HELP string  → rich descriptions (source of truth for docs)
#   Pass 2 — CLI source   → picks up every elif branch not yet in HELP
# Result is always complete and stays in sync automatically.
def _build_slash_commands() -> dict[str, tuple[str, str]]:
    """Return {'/cmd': ('description', '/cmd [args]')}."""
    out: dict[str, tuple[str, str]] = {}

    # Pass 1: HELP string → commands with descriptions
    for line in HELP.splitlines():
        stripped = line.strip()
        if not stripped.startswith("/"):
            continue
        parts = re.split(r"\s{2,}", stripped, maxsplit=1)
        if len(parts) < 2:
            continue
        cmd_part, desc = parts[0].strip(), parts[1].strip()
        for token in re.findall(r"/[\w/-]+", cmd_part):
            if token not in out:
                out[token] = (desc, cmd_part)

    # Pass 2: scan the CLI source for elif branches not covered by HELP
    # Matches:  elif line == "/cmd"   and  elif line.startswith("/cmd")
    try:
        src = Path(__file__).read_text(encoding="utf-8")
        for m in re.finditer(r'(?:line == |startswith\()"(/[\w/-]+)', src):
            cmd = m.group(1)
            if cmd not in out:
                # Humanise the command name as a fallback description
                desc = cmd.lstrip("/").replace("-", " ").title()
                out[cmd] = (desc, cmd)
    except Exception:
        pass

    return out

SLASH_COMMANDS: dict[str, tuple[str, str]] = _build_slash_commands()

def _fuzzy_score(query: str, target: str) -> int:
    """
    Return a relevance score for how well `query` matches `target` (0 = no match).

    Algorithm (substring-based — no false-positive subsequence noise):
      100  prefix match: target starts with query
       50  substring match: query appears anywhere inside target
        0  no match

    Within each tier, word-boundary matches get +10 so e.g. "/back" ranks
    "/backup-now" above "/rag-index" even if both contain the chars.
    """
    if not query:
        return 50  # empty partial → show all
    if query not in target:
        return 0
    score = 100 if target.startswith(query) else 50
    # Bonus: match starts on a word boundary (after '-' or at position 0)
    idx = target.index(query)
    if idx == 0 or target[idx - 1] == "-":
        score += 10
    return score


class SlashCommandCompleter(Completer):
    """
    Dropdown completer that activates the instant the input line starts with '/'.

    Behaviour:
    - Typing '/'      → shows all commands (alphabetical)
    - Typing '/mem'   → /memory-recall, /memory-scan (prefix → substring order)
    - Typing '/back'  → /backup-* commands
    - Typing '/mem r' → no completions (argument space started)
    - Tab / ↑↓        → navigate and accept
    """

    def get_completions(self, document: "_PTDocument", complete_event):  # type: ignore[override]
        text = document.text_before_cursor

        # Only activate when the input line itself starts with '/'
        if not text.startswith("/"):
            return

        partial = text[1:].lower()

        # Stop completing once the user starts typing arguments
        if " " in partial:
            return

        # Score every command and collect matches
        scored: list[tuple[int, str]] = []
        for cmd in SLASH_COMMANDS:
            s = _fuzzy_score(partial, cmd[1:].lower())
            if s > 0:
                scored.append((s, cmd))

        # Best score first; ties broken alphabetically
        scored.sort(key=lambda x: (-x[0], x[1]))

        for _, cmd in scored:
            desc, usage = SLASH_COMMANDS[cmd]
            display_extra = usage[len(cmd):].strip()
            display_text  = cmd + (f" {display_extra}" if display_extra else "")
            yield Completion(
                text=cmd,
                start_position=-len(text),    # replace entire '/partial' typed so far
                display=display_text,
                display_meta=desc[:58],
            )


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
        # Slash command pass-through: adwi /notify "msg" or adwi /ha states
        if flag.startswith("/"):
            cmd_line = " ".join(sys.argv[1:])
            handle(cmd_line)
            return

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
