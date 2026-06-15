#!/usr/bin/env python3
"""
adwi-evolution-loop.py — Autonomous Overnight Self-Evolution Engine
Runs entirely unattended. Four sequential phases:

  Phase 1  CRAWL      Ultra-wide home-dir Q&A indexing  → ~/.adwi/knowledge.db
  Phase 2  EVOLVE     Tool gap analysis + sandboxed install + micro-test
  Phase 3  SCRIPTS    LLM-generated utility scripts, auto-tested, auto-registered
  Phase 4  REPORT     Evolution manifest + morning brief → ~/Desktop

HARD SECURITY BLOCKS (never read regardless of any instruction):
  ~/.ssh  ~/.gnupg  ~/Library/Keychains  ~/Library/Passwords
  ~/.aws  ~/.kube  ~/.config/gcloud  ~/.azure  ~/.netrc  ~/.npmrc
  Any *.pem *.p12 *.pfx *.key id_rsa id_ed25519

Everything else in the home directory is fair game for indexing.
Tool installations are sandboxed to ~/.adwi/plugins/ — no sudo, no core OS changes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RUN NOW (detached):
    nohup python3 ~/SuneelWorkSpace/adwi-evolution-loop.py \\
          > /tmp/adwi-evolution.log 2>&1 &
    echo "PID $! — monitor: tail -f /tmp/adwi-evolution.log"

Morning output:
    ~/Desktop/adwi-evolution-report-YYYY-MM-DD.md
    ~/.adwi/knowledge.db     (SQLite vector store)
    ~/.adwi/plugins.json     (registered plugin manifest)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ═══════════════════════════════════════════════════════════════════════════════
# SELF-BOOTSTRAP — install any missing helpers before main imports
# ═══════════════════════════════════════════════════════════════════════════════

import subprocess
import sys
import os

def _pip(*pkgs: str) -> bool:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "--quiet", *pkgs],
            capture_output=True, timeout=180,
        )
        return r.returncode == 0
    except Exception:
        return False

# Try chromadb — fall back to built-in SQLite store if unavailable
HAVE_CHROMA = False
try:
    import chromadb  # type: ignore
    HAVE_CHROMA = True
except ImportError:
    if _pip("chromadb"):
        try:
            import chromadb  # type: ignore
            HAVE_CHROMA = True
        except ImportError:
            pass

# ── Standard-library imports (always available) ───────────────────────────────
import hashlib
import json
import math
import re
import shutil
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

HOME          = Path.home()
ADWI_HOME     = HOME / ".adwi"
PLUGINS_DIR   = ADWI_HOME / "plugins"
SCRIPTS_DIR   = PLUGINS_DIR / "scripts"
DB_PATH       = ADWI_HOME / "knowledge.db"
MANIFEST_PATH = ADWI_HOME / "plugins.json"
CHECKPOINT    = ADWI_HOME / "crawl-checkpoint.json"
LOG_PATH      = Path("/tmp/adwi-evolution.log")
DESKTOP       = HOME / "Desktop"

OLLAMA_URL   = "http://127.0.0.1:11434"
QA_MODEL     = "adwi:latest"          # Qwen3 MoE 30B — primary reasoning
EMBED_MODEL  = "nomic-embed-text"     # 274MB, already installed
FAST_MODEL   = "qwen3:0.6b"           # instant classification / small tasks

RUNTIME_HOURS    = 7
QUESTIONS_PER_CHUNK = 3
CHUNK_CHARS      = 2400
CHUNK_OVERLAP    = 150
MAX_FILE_BYTES   = 160_000
MIN_FILE_BYTES   = 60

# Files/dirs that will NEVER be read — credential and key material
HARD_BLOCKED: list = [
    HOME / ".ssh",
    HOME / ".gnupg",
    HOME / "Library" / "Keychains",
    HOME / "Library" / "Passwords",
    HOME / "Library" / "Application Support" / "Google" / "Chrome",
    HOME / "Library" / "Application Support" / "Firefox",
    HOME / "Library" / "Application Support" / "com.apple.Safari",
    HOME / "Library" / "Application Support" / "Keychain",
    HOME / ".aws",
    HOME / ".kube",
    HOME / ".azure",
    HOME / ".config" / "gcloud",
    HOME / ".netrc",
    HOME / ".npmrc",
    HOME / "SuneelWorkSpace" / "secrets",
]
HARD_BLOCKED_NAMES = {
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    ".netrc", ".npmrc", "credentials", "token.json",
}
HARD_BLOCKED_EXTS = {".pem", ".p12", ".pfx", ".key", ".crt", ".cer", ".der", ".p8"}
SECRET_PATTERN = re.compile(
    r"(password|passwd|private.?key|api.?key|secret.?key|access.?token"
    r"|bearer|authorization|aws_secret|github_token|openai_api)\s*[=:]\s*\S+",
    re.I,
)

# Directory names that are pure noise (binaries, cache, build artifacts)
SKIP_DIR_NAMES = {
    "__pycache__", "node_modules", ".git", "venv", ".venv", "env",
    "dist", "build", ".next", ".nuxt", "coverage", ".mypy_cache",
    ".pytest_cache", ".tox", "target", "*.egg-info",
    "open-webui-data", "n8n-data", "qdrant-data", "searxng-data",
    "ollama-blobs", "Caches", "DerivedData", "Pods",
    "xcuserdata", ".Trash", "models",
}

# Binary / media extensions — no LLM value
SKIP_EXTS = {
    ".dmg", ".pkg", ".app", ".ipa", ".dSYM",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic", ".heif",
    ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".aac", ".flac", ".wav",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    ".so", ".dylib", ".o", ".a", ".pyc", ".pyo",
    ".gguf", ".bin", ".safetensors", ".onnx", ".pt", ".pth", ".model",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".ico", ".svg",  # SVG is text but adds noise
    ".db", ".sqlite", ".sqlite3",  # don't re-index databases
}

TARGET_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".cpp", ".c", ".h", ".hpp", ".rb", ".swift", ".kt", ".scala",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".md", ".txt", ".rst", ".adoc",
    ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".conf",
    ".html", ".css", ".scss", ".less",
    ".sql", ".graphql", ".proto",
    ".env.example",  # example env files only, not real ones
    ".dockerfile", ".Dockerfile",
    ".makefile", ".Makefile",
}

# Roots to crawl (in priority order)
SCAN_ROOTS = [
    HOME / "SuneelWorkSpace",
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
    HOME / ".config",
]
SCAN_EXTRA_FILES = [
    HOME / ".zsh_history",
    HOME / ".zshrc",
    HOME / ".bashrc",
    HOME / ".gitconfig",
    HOME / ".gitignore_global",
]

# ─── Curated tool catalog ─────────────────────────────────────────────────────
# Entries with "cmd" key → test by running the command.
# Entries with "imp" key  → test by python -c "import <imp>".
# All brew installs go to /opt/homebrew (no root needed on Apple Silicon).
# All pip installs use --user flag.

BREW_TOOLS = [
    {"name": "jq",         "bin": "jq",        "test": ["jq","--version"],        "desc": "JSON processor for Ollama API output parsing"},
    {"name": "yq",         "bin": "yq",        "test": ["yq","--version"],        "desc": "YAML/JSON/XML inline processor"},
    {"name": "ripgrep",    "bin": "rg",        "test": ["rg","--version"],        "desc": "10x faster grep — searches workspace in ms"},
    {"name": "fd",         "bin": "fd",        "test": ["fd","--version"],        "desc": "Intuitive find replacement with .gitignore support"},
    {"name": "fzf",        "bin": "fzf",       "test": ["fzf","--version"],       "desc": "Fuzzy finder — powers interactive shell history"},
    {"name": "bat",        "bin": "bat",       "test": ["bat","--version"],       "desc": "cat with syntax highlighting and git annotations"},
    {"name": "eza",        "bin": "eza",       "test": ["eza","--version"],       "desc": "Modern ls with tree view and git status"},
    {"name": "delta",      "bin": "delta",     "test": ["delta","--version"],     "desc": "Syntax-highlighted git diff pager for code review"},
    {"name": "lazygit",    "bin": "lazygit",   "test": ["lazygit","--version"],   "desc": "Terminal UI for git — commit/branch/rebase visually"},
    {"name": "hyperfine",  "bin": "hyperfine", "test": ["hyperfine","--version"], "desc": "Accurate command benchmarking with statistics"},
    {"name": "tokei",      "bin": "tokei",     "test": ["tokei","--version"],     "desc": "Count lines of code by language in seconds"},
    {"name": "dust",       "bin": "dust",      "test": ["dust","--version"],      "desc": "Disk usage analyzer — finds what's eating storage"},
    {"name": "bottom",     "bin": "btm",       "test": ["btm","--version"],       "desc": "GPU/CPU/memory/process monitor with graphs"},
    {"name": "procs",      "bin": "procs",     "test": ["procs","--version"],     "desc": "Modern ps — color-coded process tree view"},
    {"name": "httpie",     "bin": "http",      "test": ["http","--version"],      "desc": "Human-friendly HTTP client for testing Ollama APIs"},
    {"name": "tldr",       "bin": "tldr",      "test": ["tldr","--version"],      "desc": "Community-maintained simplified man pages"},
    {"name": "tree",       "bin": "tree",      "test": ["tree","--version"],      "desc": "Print directory trees — for architectural diagrams"},
    {"name": "jless",      "bin": "jless",     "test": ["jless","--version"],     "desc": "Interactive JSON pager — navigate large API responses"},
    {"name": "zoxide",     "bin": "zoxide",    "test": ["zoxide","--version"],    "desc": "Smart cd — jumps to frequently-used dirs instantly"},
    {"name": "just",       "bin": "just",      "test": ["just","--version"],      "desc": "Command runner — project-scoped Makefile alternative"},
    {"name": "gron",       "bin": "gron",      "test": ["gron","--version"],      "desc": "Flatten JSON to greppable lines then rebuild"},
    {"name": "mkcert",     "bin": "mkcert",    "test": ["mkcert","--version"],    "desc": "Trusted local HTTPS certs for Open WebUI dev"},
]

PIP_TOOLS = [
    {"name": "rich",         "imp": "rich",      "desc": "Beautiful terminal tables, panels, syntax for Adwi"},
    {"name": "httpx",        "imp": "httpx",     "desc": "Async HTTP client — replaces requests in async agents"},
    {"name": "typer",        "imp": "typer",     "desc": "Build Adwi sub-CLIs from Python type hints"},
    {"name": "ruff",         "cmd": ["ruff","--version"], "desc": "10-100x faster Python linter — replaces flake8+pylint"},
    {"name": "black",        "cmd": ["black","--version"], "desc": "Uncompromising formatter for Adwi auto-generated code"},
    {"name": "watchdog",     "imp": "watchdog",  "desc": "File system events — power live-reload in watchers"},
    {"name": "schedule",     "imp": "schedule",  "desc": "In-process cron — schedule Adwi tasks without launchd"},
    {"name": "psutil",       "imp": "psutil",    "desc": "CPU/memory/disk/process stats from Python"},
    {"name": "GitPython",    "imp": "git",       "desc": "Git repo access from Python — power Adwi backup ops"},
    {"name": "PyYAML",       "imp": "yaml",      "desc": "YAML parser — read/write docker-compose, config files"},
    {"name": "pydantic",     "imp": "pydantic",  "desc": "Runtime type validation for Adwi data models"},
    {"name": "click",        "imp": "click",     "desc": "Composable CLI framework — power Adwi sub-commands"},
    {"name": "tqdm",         "imp": "tqdm",      "desc": "Progress bars for overnight learning loops"},
    {"name": "aiohttp",      "imp": "aiohttp",   "desc": "Async HTTP server/client — power local API endpoints"},
    {"name": "pygments",     "imp": "pygments",  "desc": "Syntax highlighting — used by Adwi code display"},
    {"name": "tabulate",     "imp": "tabulate",  "desc": "ASCII tables — format model comparison results"},
    {"name": "tenacity",     "imp": "tenacity",  "desc": "Retry library with exponential backoff for Ollama calls"},
    {"name": "loguru",       "imp": "loguru",    "desc": "Structured logging with rotation — replace print() logging"},
    {"name": "python-dotenv","imp": "dotenv",    "desc": "Load .env files for Adwi secrets management"},
    {"name": "orjson",       "imp": "orjson",    "desc": "10x faster JSON — critical for embedding pipeline speed"},
]

# LLM-generated utility scripts: (slug, task description for the model)
SCRIPT_TASKS = [
    (
        "workspace_map",
        "Write a complete Python script (no imports outside stdlib) that scans "
        "~/SuneelWorkSpace, builds a structured JSON map of all directories and "
        "files with their sizes and types, and writes it to "
        "~/.adwi/workspace-map.json. The script must be runnable as "
        "'python3 script.py' with exit code 0 on success.",
    ),
    (
        "todo_harvester",
        "Write a complete Python script (stdlib only) that recursively scans "
        "~/SuneelWorkSpace for TODO/FIXME/HACK/XXX/BUG comments in all text "
        "files, groups them by file, and writes a markdown report to "
        "~/.adwi/todo-report.md. Exit code 0 on success, non-zero on error.",
    ),
    (
        "import_graph",
        "Write a complete Python script (stdlib only) that scans all .py files "
        "under ~/SuneelWorkSpace, extracts their import statements, and produces "
        "a dependency graph in DOT format saved to ~/.adwi/import-graph.dot "
        "and a human-readable summary at ~/.adwi/import-summary.md. Exit 0 on success.",
    ),
    (
        "model_benchmark",
        "Write a Python script (stdlib only) that sends 5 standardized prompts "
        "to Ollama at http://127.0.0.1:11434 using both 'adwi:latest' and "
        "'qwen3:0.6b', measures tokens/second for each, and writes a comparison "
        "table to ~/.adwi/model-benchmark.md. Exit 0 on success.",
    ),
    (
        "log_summarizer",
        "Write a Python script (stdlib only) that reads all *.md and *.log files "
        "in ~/.adwi/ and ~/SuneelWorkSpace/notes/, extracts the most recent 100 "
        "lines from each, and asks Ollama (adwi:latest, http://127.0.0.1:11434) "
        "to write a one-paragraph summary of Adwi's recent activity. Saves the "
        "summary to ~/.adwi/activity-summary.md. Exit 0 on success.",
    ),
]

# ═══════════════════════════════════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════════════════════════════════

for _d in [ADWI_HOME, PLUGINS_DIR, SCRIPTS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

START_TIME = datetime.now()
DEADLINE   = START_TIME + timedelta(hours=RUNTIME_HOURS)

_LOG_FH = None

def _open_log():
    global _LOG_FH
    if _LOG_FH is None:
        _LOG_FH = open(LOG_PATH, "a", buffering=1, encoding="utf-8")

def log(msg: str, level: str = "INFO"):
    _open_log()
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}][{level}] {msg}"
    print(line, flush=True)
    _LOG_FH.write(line + "\n")

def out_of_time() -> bool:
    return datetime.now() >= DEADLINE

def budget_str() -> str:
    rem = max(0, (DEADLINE - datetime.now()).total_seconds())
    h, m = divmod(int(rem), 3600)
    return f"{h}h{m:02d}m left"


# ═══════════════════════════════════════════════════════════════════════════════
# SQLITE KNOWLEDGE STORE
# ═══════════════════════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    path       TEXT NOT NULL,
    idx        INTEGER NOT NULL,
    text       TEXT NOT NULL,
    hash       TEXT NOT NULL UNIQUE,
    embedding  TEXT
);
CREATE TABLE IF NOT EXISTS qa (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    path       TEXT NOT NULL,
    chunk_id   INTEGER,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    hash       TEXT NOT NULL UNIQUE,
    embedding  TEXT
);
CREATE INDEX IF NOT EXISTS ix_c_path ON chunks(path);
CREATE INDEX IF NOT EXISTS ix_q_path ON qa(path);
"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:28]


def _cos(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class KDB:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def chunk_exists(self, h: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM chunks WHERE hash=?", (h,)).fetchone())

    def insert_chunk(self, path: str, idx: int, text: str, emb: list) -> int:
        h = _sha(text)
        try:
            cur = self.conn.execute(
                "INSERT INTO chunks (ts,path,idx,text,hash,embedding) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(), path, idx, text, h,
                 json.dumps(emb) if emb else None),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            row = self.conn.execute("SELECT id FROM chunks WHERE hash=?", (h,)).fetchone()
            return row[0] if row else -1

    def insert_qa(self, path: str, cid: int, q: str, a: str, emb: list):
        h = _sha(q + a)
        try:
            self.conn.execute(
                "INSERT INTO qa (ts,path,chunk_id,question,answer,hash,embedding) "
                "VALUES (?,?,?,?,?,?,?)",
                (datetime.now().isoformat(), path, cid, q, a, h,
                 json.dumps(emb) if emb else None),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def qa_exists(self, q: str, a: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM qa WHERE hash=?", (_sha(q+a),)).fetchone())

    def stats(self) -> dict:
        return {
            "chunks":   self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "qa":       self.conn.execute("SELECT COUNT(*) FROM qa").fetchone()[0],
            "files":    self.conn.execute("SELECT COUNT(DISTINCT path) FROM chunks").fetchone()[0],
        }

    def sample_qa(self, n: int = 10) -> list:
        rows = self.conn.execute(
            "SELECT question, path FROM qa ORDER BY RANDOM() LIMIT ?", (n,)
        ).fetchall()
        return [{"q": r[0], "path": r[1]} for r in rows]

    def search(self, qemb: list, k: int = 5) -> list:
        rows = self.conn.execute(
            "SELECT question,answer,path,embedding FROM qa WHERE embedding IS NOT NULL LIMIT 8000"
        ).fetchall()
        scored = []
        for q, a, p, ej in rows:
            try:
                sim = _cos(qemb, json.loads(ej))
                if sim > 0.15:
                    scored.append({"q": q, "a": a, "path": p, "score": sim})
            except Exception:
                pass
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    def files_by_depth(self) -> list:
        rows = self.conn.execute(
            "SELECT path, COUNT(*) n FROM chunks GROUP BY path ORDER BY n DESC LIMIT 30"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def close(self):
        self.conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# OLLAMA HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _post(endpoint: str, payload: dict, timeout: int = 240) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{OLLAMA_URL}{endpoint}", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ollama_ok() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=4)
        return True
    except Exception:
        return False


def wait_ollama(secs: int = 90) -> bool:
    for _ in range(secs // 3):
        if ollama_ok():
            return True
        time.sleep(3)
    return False


def embed(text: str, retries: int = 3) -> list:
    for i in range(retries):
        try:
            r = _post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text[:4000]}, timeout=20)
            v = r.get("embedding", [])
            if v:
                return v
        except Exception as e:
            if i < retries - 1:
                time.sleep(2 ** i)
            else:
                log(f"embed failed: {e}", "WARN")
    return []


def generate_qa(chunk: str, path: str, n: int = QUESTIONS_PER_CHUNK) -> list:
    ext  = Path(path).suffix.lstrip(".")
    lang = {
        "py":"Python","js":"JavaScript","ts":"TypeScript","go":"Go","rs":"Rust",
        "java":"Java","cpp":"C++","c":"C","rb":"Ruby","swift":"Swift","kt":"Kotlin",
        "sh":"Shell","bash":"Bash","sql":"SQL","md":"Markdown","yaml":"YAML","toml":"TOML",
    }.get(ext, "source code")

    prompt = (
        f"You are a principal engineer conducting a deep technical review of this "
        f"{lang} file.\nFILE: {Path(path).name}\n\n"
        f"```{ext}\n{chunk[:2500]}\n```\n\n"
        f"Generate exactly {n} advanced Q&A pairs that a senior engineer deeply "
        f"familiar with this codebase would ask. Focus on:\n"
        f"  - Non-obvious design tradeoffs and their consequences\n"
        f"  - Edge cases, failure modes, concurrency gotchas\n"
        f"  - Performance characteristics and memory behavior\n"
        f"  - Security implications and trust boundaries\n"
        f"  - How this connects to the rest of the system\n\n"
        f"Every answer must be 3-6 sentences demonstrating expert understanding.\n"
        f"Return ONLY a JSON array, no prose, no code fences:\n"
        f'[{{"q":"...","a":"..."}}]'
    )
    for attempt in range(3):
        try:
            resp = _post("/api/generate", {
                "model": QA_MODEL, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.72, "num_predict": 2400,
                            "top_p": 0.92, "repeat_penalty": 1.1},
            }, timeout=210)
            raw = resp.get("response", "").strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.M)
            raw = re.sub(r"\s*```\s*$",       "", raw, flags=re.M)
            m   = re.search(r"\[[\s\S]*?\]", raw)
            if not m:
                objs = re.findall(r'\{[^{}]+\}', raw)
                raw  = "[" + ",".join(objs) + "]" if objs else "[]"
            else:
                raw = m.group(0)
            pairs = json.loads(raw)
            valid = [p for p in pairs
                     if isinstance(p, dict)
                     and len(p.get("q","")) > 20
                     and len(p.get("a","")) > 40]
            if valid:
                return valid[:n]
        except (json.JSONDecodeError, ValueError):
            time.sleep(3)
        except Exception as e:
            log(f"generate_qa attempt {attempt+1}: {e}", "WARN")
            time.sleep(6)
    return []


def generate_script(task_desc: str, slug: str) -> str:
    """Ask the model to write a complete, runnable Python utility script."""
    prompt = (
        f"Write a complete, production-quality Python script for this task:\n\n"
        f"{task_desc}\n\n"
        f"REQUIREMENTS:\n"
        f"  - Use only Python stdlib (no pip installs inside the script)\n"
        f"  - Must run with: python3 {slug}.py\n"
        f"  - Exit with code 0 on success, non-zero on failure\n"
        f"  - Include robust try/except with meaningful error messages to stderr\n"
        f"  - Do NOT include any interactive input() calls\n"
        f"  - Create output directories if they don't exist\n\n"
        f"Return ONLY the complete Python script — no explanation, no markdown fences."
    )
    try:
        resp = _post("/api/generate", {
            "model": QA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.3, "num_predict": 3000},
        }, timeout=300)
        raw = resp.get("response", "").strip()
        raw = re.sub(r"^```python\s*", "", raw, flags=re.M)
        raw = re.sub(r"^```\s*$",      "", raw, flags=re.M)
        return raw.strip()
    except Exception as e:
        log(f"generate_script({slug}) failed: {e}", "WARN")
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# PATH SAFETY
# ═══════════════════════════════════════════════════════════════════════════════

def is_hard_blocked(path: Path) -> bool:
    """Returns True if path is under any credential/key location."""
    try:
        rp = path.resolve()
    except Exception:
        return True
    for blocked in HARD_BLOCKED:
        try:
            rp.relative_to(blocked.resolve())
            return True
        except ValueError:
            pass
    if path.name in HARD_BLOCKED_NAMES:
        return True
    if path.suffix.lower() in HARD_BLOCKED_EXTS:
        return True
    # Skip real .env files (but allow .env.example)
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return True
    return False


def is_skip_dir(path: Path) -> bool:
    return path.name in SKIP_DIR_NAMES or path.name.startswith(".")  and path.name in {
        ".ollama", ".npm", ".cache", ".gradle", ".m2", ".ivy2",
        ".android", ".Trash", ".DS_Store",
    }


def is_indexable(path: Path) -> bool:
    if not path.is_file():
        return False
    if is_hard_blocked(path):
        return False
    if path.suffix.lower() in SKIP_EXTS:
        return False
    if path.suffix.lower() not in TARGET_EXTS and path.name not in {
        ".zshrc", ".bashrc", ".gitconfig", ".zsh_history", "Makefile",
        "Dockerfile", "Procfile", ".editorconfig",
    }:
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return MIN_FILE_BYTES <= size <= MAX_FILE_BYTES


def redact(text: str) -> str:
    """Scrub any credential-looking values before storing."""
    return SECRET_PATTERN.sub(r"\1=[REDACTED]", text)


# ═══════════════════════════════════════════════════════════════════════════════
# CRAWL ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def crawl_all() -> list:
    files = []
    seen  = set()

    def _add(p: Path):
        rp = str(p.resolve())
        if rp not in seen and is_indexable(p):
            seen.add(rp)
            files.append(p)

    # Scan directory roots
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if out_of_time():
                break
            if path.is_dir():
                # Prune blocked and noisy dirs
                if is_hard_blocked(path):
                    continue
                if any(skip in path.parts for skip in SKIP_DIR_NAMES):
                    continue
            else:
                _add(path)

    # Add explicit individual files
    for f in SCAN_EXTRA_FILES:
        if f.exists():
            _add(f)

    log(f"Crawl complete: {len(files)} indexable files found")
    return files


def chunk_file(path: Path) -> list:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    raw = redact(raw)
    chunks, idx, start = [], 0, 0
    while start < len(raw):
        end = min(start + CHUNK_CHARS, len(raw))
        if end < len(raw):
            nl = raw.rfind("\n", start + CHUNK_CHARS // 2, end)
            if nl > 0:
                end = nl + 1
        piece = raw[start:end].strip()
        if piece:
            chunks.append((idx, piece))
            idx += 1
        start = max(end - CHUNK_OVERLAP, start + 1)
        if start >= len(raw) - 40:
            break
    return chunks


# ═══════════════════════════════════════════════════════════════════════════════
# CHECKPOINT
# ═══════════════════════════════════════════════════════════════════════════════

def load_checkpoint() -> set:
    if CHECKPOINT.exists():
        try:
            return set(json.loads(CHECKPOINT.read_text()).get("done", []))
        except Exception:
            pass
    return set()


def save_checkpoint(done: set):
    try:
        CHECKPOINT.write_text(json.dumps({"done": list(done), "ts": datetime.now().isoformat()}))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — KNOWLEDGE INDEXING
# ═══════════════════════════════════════════════════════════════════════════════

def knowledge_phase(db: KDB) -> dict:
    log("=" * 60)
    log("PHASE 1: ULTRA-WIDE KNOWLEDGE INDEXING")
    log("=" * 60)

    all_files  = crawl_all()
    done       = load_checkpoint()
    todo       = [f for f in all_files if str(f) not in done]
    hourly_log = []
    pass_n     = 1

    log(f"  {len(all_files)} files found, {len(todo)} to process ({len(done)} already done)")

    phase_qa     = 0
    phase_chunks = 0
    hour_mark    = datetime.now() + timedelta(hours=1)

    while not out_of_time():
        if not todo:
            pass_n += 1
            done = set()
            todo = all_files
            log(f"All files indexed — starting pass {pass_n} for Q&A variants ({budget_str()})")

        for file_path in list(todo):
            if out_of_time():
                break

            chunks = chunk_file(file_path)
            if not chunks:
                done.add(str(file_path)); todo.remove(file_path)
                continue

            fp_str   = str(file_path)
            new_qa   = 0
            new_chk  = 0

            for cidx, ctext in chunks:
                if out_of_time():
                    break
                ch = _sha(ctext)
                if not db.chunk_exists(ch):
                    cemb = embed(ctext)
                    cid  = db.insert_chunk(fp_str, cidx, ctext, cemb)
                    new_chk      += 1
                    phase_chunks += 1
                else:
                    row = db.conn.execute("SELECT id FROM chunks WHERE hash=?", (ch,)).fetchone()
                    cid = row[0] if row else -1

                pairs = generate_qa(ctext, fp_str)
                for p in pairs:
                    q, a = p.get("q",""), p.get("a","")
                    if q and a and not db.qa_exists(q, a):
                        qemb = embed(f"Q: {q}\nA: {a}")
                        db.insert_qa(fp_str, cid, q, a, qemb)
                        new_qa   += 1
                        phase_qa += 1

                time.sleep(0.35)

            try:
                rel = file_path.relative_to(HOME)
            except ValueError:
                rel = file_path
            log(f"[P{pass_n}] {rel}  +{new_chk}chk +{new_qa}qa  total={db.stats()['qa']}  {budget_str()}")

            done.add(fp_str)
            todo.remove(file_path)
            save_checkpoint(done)

            now = datetime.now()
            if now >= hour_mark:
                s = db.stats()
                entry = f"{now.strftime('%H:%M')} — {s['files']}files {s['chunks']}chunks {s['qa']}Q&A"
                hourly_log.append(entry)
                log(f"  ── HOURLY: {entry} ──")
                hour_mark = now + timedelta(hours=1)

    s = db.stats()
    log(f"Phase 1 complete: {s['files']} files, {s['chunks']} chunks, {s['qa']} Q&A pairs")
    return {"files": s["files"], "chunks": s["chunks"], "qa": s["qa"],
            "passes": pass_n, "hourly": hourly_log}


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — AUTONOMOUS TOOL EVOLUTION
# ═══════════════════════════════════════════════════════════════════════════════

def _which(binary: str) -> bool:
    return shutil.which(binary) is not None


def _can_import(module: str) -> bool:
    r = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True, timeout=8,
    )
    return r.returncode == 0


def _run_silent(cmd: list, timeout: int = 120, cwd: str = None) -> tuple:
    env = {**os.environ,
           "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "HOME": str(HOME),
           "HOMEBREW_NO_AUTO_UPDATE": "1",
           "HOMEBREW_NO_ENV_HINTS": "1",
           "PIP_QUIET": "1"}
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=env, cwd=cwd,
        )
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, str(e)


def scan_installed() -> dict:
    """Return dict of {tool_name: True/False} for all catalog entries."""
    installed = {}
    for t in BREW_TOOLS:
        installed[f"brew:{t['name']}"] = _which(t["bin"])
    for t in PIP_TOOLS:
        if "imp" in t:
            installed[f"pip:{t['name']}"] = _can_import(t["imp"])
        elif "cmd" in t:
            installed[f"pip:{t['name']}"] = _which(t["cmd"][0])
    return installed


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            pass
    return {"brew": {}, "pip": {}, "scripts": {}, "updated": ""}


def save_manifest(m: dict):
    m["updated"] = datetime.now().isoformat()
    MANIFEST_PATH.write_text(json.dumps(m, indent=2))


def install_brew(tool: dict) -> tuple:
    """Install via Homebrew. Returns (success, log_text)."""
    name = tool["name"]
    log(f"  brew install {name}...")
    rc, out = _run_silent(
        ["/opt/homebrew/bin/brew", "install", name],
        timeout=300,
    )
    if rc == 0:
        # Verify binary is now reachable
        rc2, _ = _run_silent(tool["test"], timeout=10)
        return rc2 == 0, out
    return False, out


def install_pip(tool: dict) -> tuple:
    """Install via pip --user. Returns (success, log_text)."""
    name = tool["name"]
    log(f"  pip install --user {name}...")
    rc, out = _run_silent(
        [sys.executable, "-m", "pip", "install", "--user", "--quiet", name],
        timeout=180,
    )
    if rc == 0:
        if "imp" in tool:
            ok = _can_import(tool["imp"])
        elif "cmd" in tool:
            ok = _which(tool["cmd"][0])
        else:
            ok = True
        return ok, out
    return False, out


def write_micro_test(tool: dict, kind: str) -> Path:
    """Write a tiny test script for the tool. Returns path to test file."""
    test_path = PLUGINS_DIR / f"test_{kind}_{tool['name'].replace('-','_')}.py"

    if kind == "brew":
        cmd_json = json.dumps(tool["test"])
        src = (
            "import subprocess, sys\n"
            f"r = subprocess.run({cmd_json}, capture_output=True, timeout=10)\n"
            "sys.exit(r.returncode)\n"
        )
    else:  # pip
        if "imp" in tool:
            src = f"import {tool['imp']}\nprint('{tool['name']} OK')\n"
        else:
            cmd_json = json.dumps(tool["cmd"])
            src = (
                "import subprocess, sys\n"
                f"r = subprocess.run({cmd_json}, capture_output=True, timeout=10)\n"
                "sys.exit(r.returncode)\n"
            )

    test_path.write_text(src)
    return test_path


def run_micro_test(test_path: Path, timeout: int = 15) -> bool:
    """Run a micro-test script. Returns True if exit code is 0."""
    rc, _ = _run_silent([sys.executable, str(test_path)], timeout=timeout)
    return rc == 0


def evolution_phase() -> dict:
    log("=" * 60)
    log("PHASE 2: AUTONOMOUS TOOL EVOLUTION")
    log("=" * 60)

    manifest = load_manifest()
    report = {
        "already_installed": [],
        "newly_installed":   [],
        "failed":            [],
        "skipped":           [],
    }

    if out_of_time():
        log("Time budget exhausted before Phase 2")
        return report

    installed = scan_installed()
    log(f"  Inventory complete — checking {len(BREW_TOOLS)} brew + {len(PIP_TOOLS)} pip tools")

    # Brew tools
    for tool in BREW_TOOLS:
        if out_of_time():
            break
        key = f"brew:{tool['name']}"
        if installed.get(key):
            report["already_installed"].append(key)
            manifest["brew"][tool["name"]] = {"status": "present", "desc": tool["desc"]}
            continue

        log(f"  Missing: {key} — {tool['desc']}")
        ok, out = install_brew(tool)
        if ok:
            test_path = write_micro_test(tool, "brew")
            passed    = run_micro_test(test_path)
            if passed:
                log(f"  ✓ {key} installed and verified")
                manifest["brew"][tool["name"]] = {
                    "status": "installed", "desc": tool["desc"],
                    "test": str(test_path), "ts": datetime.now().isoformat(),
                }
                report["newly_installed"].append(key)
            else:
                log(f"  ✗ {key} micro-test failed — removing", "WARN")
                test_path.unlink(missing_ok=True)
                report["failed"].append({"tool": key, "reason": "micro-test failed"})
        else:
            log(f"  ✗ {key} install failed: {out[:200]}", "WARN")
            report["failed"].append({"tool": key, "reason": out[:200]})

        save_manifest(manifest)
        time.sleep(1)

    # Pip tools
    for tool in PIP_TOOLS:
        if out_of_time():
            break
        key = f"pip:{tool['name']}"
        if installed.get(key):
            report["already_installed"].append(key)
            manifest["pip"][tool["name"]] = {"status": "present", "desc": tool["desc"]}
            continue

        log(f"  Missing: {key} — {tool['desc']}")
        ok, out = install_pip(tool)
        if ok:
            test_path = write_micro_test(tool, "pip")
            passed    = run_micro_test(test_path)
            if passed:
                log(f"  ✓ {key} installed and verified")
                manifest["pip"][tool["name"]] = {
                    "status": "installed", "desc": tool["desc"],
                    "test": str(test_path), "ts": datetime.now().isoformat(),
                }
                report["newly_installed"].append(key)
            else:
                log(f"  ✗ {key} micro-test failed — removing", "WARN")
                test_path.unlink(missing_ok=True)
                report["failed"].append({"tool": key, "reason": "micro-test failed"})
        else:
            log(f"  ✗ {key} install failed: {out[:200]}", "WARN")
            report["failed"].append({"tool": key, "reason": out[:200]})

        save_manifest(manifest)
        time.sleep(0.5)

    log(f"Phase 2 complete: {len(report['newly_installed'])} new tools, "
        f"{len(report['failed'])} failed, {len(report['already_installed'])} already present")
    return report


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — SELF-GENERATED UTILITY SCRIPTS
# ═══════════════════════════════════════════════════════════════════════════════

def scripts_phase() -> dict:
    log("=" * 60)
    log("PHASE 3: LLM-GENERATED UTILITY SCRIPTS")
    log("=" * 60)

    manifest = load_manifest()
    report   = {"generated": [], "registered": [], "failed": []}

    if out_of_time():
        log("Time budget exhausted before Phase 3")
        return report

    for slug, task_desc in SCRIPT_TASKS:
        if out_of_time():
            break

        log(f"  Generating: {slug}")
        code = generate_script(task_desc, slug)
        if not code or len(code) < 80:
            log(f"  ✗ {slug}: model returned empty script", "WARN")
            report["failed"].append({"slug": slug, "reason": "empty response"})
            continue

        # Do not execute scripts that contain obviously dangerous patterns
        danger = re.search(
            r"\b(shutil\.rmtree|os\.remove|subprocess\.run.*rm |"
            r"format[_ ]drive|wipe|sudo|dd\s+if=)", code, re.I
        )
        if danger:
            log(f"  ✗ {slug}: dangerous pattern detected — skipped", "WARN")
            report["failed"].append({"slug": slug, "reason": f"dangerous pattern: {danger.group()}"})
            continue

        script_path = SCRIPTS_DIR / f"{slug}.py"
        script_path.write_text(code)
        report["generated"].append(slug)

        # Sandbox execute with strict timeout
        log(f"  Testing {slug}...")
        rc, out = _run_silent(
            [sys.executable, str(script_path)],
            timeout=60,
            cwd=str(ADWI_HOME),
        )

        if rc == 0:
            log(f"  ✓ {slug} passed (exit 0) — registered in manifest")
            manifest["scripts"][slug] = {
                "path": str(script_path),
                "task": task_desc[:100],
                "status": "registered",
                "ts": datetime.now().isoformat(),
            }
            report["registered"].append(slug)
        else:
            log(f"  ✗ {slug} failed (exit {rc}): {out[:300]}", "WARN")
            script_path.unlink(missing_ok=True)
            report["failed"].append({"slug": slug, "reason": out[:300]})

        save_manifest(manifest)
        time.sleep(2)

    log(f"Phase 3 complete: {len(report['registered'])}/{len(SCRIPT_TASKS)} scripts registered")
    return report


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — MORNING REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def write_report(db: KDB, p1: dict, p2: dict, p3: dict):
    manifest = load_manifest()
    runtime  = (datetime.now() - START_TIME).total_seconds() / 3600
    samples  = db.sample_qa(n=10)
    top_files = db.files_by_depth()

    report = f"""# 🧬 Adwi Evolution Report — {datetime.now().strftime("%A %B %d, %Y")}
**Completed:** {datetime.now().strftime("%I:%M %p")}  |  **Runtime:** {runtime:.1f}h

---

## 📊 Phase 1 — Knowledge Indexing

| Metric | Count |
|---|---|
| Files analyzed | **{p1.get('files',0)}** |
| Chunks indexed | **{p1.get('chunks',0)}** |
| Synthetic Q&A pairs | **{p1.get('qa',0)}** |
| Index passes | **{p1.get('passes',1)}** |
| Knowledge DB | `{DB_PATH}` |

### Deepest-Analyzed Files
"""
    for fp, n in top_files[:12]:
        try:
            rel = Path(fp).relative_to(HOME)
        except ValueError:
            rel = Path(fp)
        report += f"- `{rel}` — {n} chunk(s)\n"

    report += "\n### Hourly Indexing Log\n"
    for entry in p1.get("hourly", []):
        report += f"- {entry}\n"

    # Phase 2 results
    report += f"""
---

## 🔧 Phase 2 — Tool Evolution

| Category | Count |
|---|---|
| Tools already installed | {len(p2.get('already_installed',[]))} |
| **Newly installed & verified** | **{len(p2.get('newly_installed',[]))}** |
| Failed / rejected | {len(p2.get('failed',[]))} |

"""
    if p2.get("newly_installed"):
        report += "### Newly Installed Tools\n"
        for t in p2["newly_installed"]:
            kind, name = t.split(":", 1)
            catalog = BREW_TOOLS if kind == "brew" else PIP_TOOLS
            item = next((x for x in catalog if x["name"] == name), {})
            report += f"- **{t}** — {item.get('desc','')}\n"

    if p2.get("failed"):
        report += "\n### Failed Installations\n"
        for f in p2["failed"]:
            report += f"- `{f['tool']}`: {f['reason'][:120]}\n"

    # Phase 3 results
    report += f"""
---

## 🤖 Phase 3 — Self-Generated Scripts

| Result | Count |
|---|---|
| Generated | {len(p3.get('generated',[]))} |
| **Registered (passed micro-test)** | **{len(p3.get('registered',[]))}** |
| Failed / dangerous | {len(p3.get('failed',[]))} |

"""
    if p3.get("registered"):
        report += "### Registered Scripts\n"
        for slug in p3["registered"]:
            report += f"- `~/.adwi/plugins/scripts/{slug}.py`\n"
        report += "\nRun any of these directly:\n```bash\n"
        for slug in p3["registered"]:
            report += f"python3 ~/.adwi/plugins/scripts/{slug}.py\n"
        report += "```\n"

    # Sample questions
    report += """
---

## 💬 Ask These Right Now in Open WebUI / Adwi

*Drawn from your actual files:*

"""
    for i, s in enumerate(samples, 1):
        try:
            rel = Path(s["path"]).relative_to(HOME)
        except ValueError:
            rel = Path(s["path"])
        report += f"**{i}.** {s['q']}\n   *(`{rel}`)*\n\n"

    # Query instructions
    report += f"""
---

## 🔍 Query Your Knowledge Base

### Adwi CLI:
```
adwi
/memory-recall <question>
/rag <question>
```

### Direct Python:
```python
import json, math, sqlite3, urllib.request

def embed(text):
    body = json.dumps({{"model":"nomic-embed-text","prompt":text}}).encode()
    req  = urllib.request.Request(
        "http://127.0.0.1:11434/api/embeddings", body,
        {{"Content-Type":"application/json"}}
    )
    return json.loads(urllib.request.urlopen(req,timeout=15).read())["embedding"]

def cosine(a,b):
    d=sum(x*y for x,y in zip(a,b))
    return d/(sum(x**2 for x in a)**.5 * sum(x**2 for x in b)**.5)

db   = sqlite3.connect("{DB_PATH}")
qemb = embed("how does authentication work in this codebase?")
rows = db.execute("SELECT question,answer,path,embedding FROM qa WHERE embedding IS NOT NULL").fetchall()
hits = sorted([(cosine(qemb,json.loads(r[3])),r) for r in rows],reverse=True)[:5]
for score,(_q,_a,_p,_) in hits:
    print(f"[{{score:.3f}}] {{_q}}")
    print(f"  {{_a[:220]}}\\n")
```

---

## 📦 Plugin Manifest

Located at: `{MANIFEST_PATH}`

Run to see all registered tools:
```bash
python3 -c "import json; m=json.load(open('{MANIFEST_PATH}')); [print(k,'→',v.get('status')) for k,v in {{**m['brew'],**m['pip'],**m['scripts']}}.items()]"
```

---

*Generated by `adwi-evolution-loop.py` · Models: {QA_MODEL} + {EMBED_MODEL}*
*Good morning, Suneel! Your stack just leveled up. ☀️*
"""

    DESKTOP.mkdir(parents=True, exist_ok=True)
    date_str  = datetime.now().strftime("%Y-%m-%d")
    out_path  = DESKTOP / f"adwi-evolution-report-{date_str}.md"
    out_path.write_text(report)

    # Also save a copy inside ADWI_HOME for history
    (ADWI_HOME / f"evolution-report-{date_str}.md").write_text(report)

    log(f"Report written → {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    log("=" * 64)
    log("  ADWI AUTONOMOUS EVOLUTION LOOP")
    log(f"  Start:    {START_TIME.strftime('%H:%M:%S')}")
    log(f"  Deadline: {DEADLINE.strftime('%H:%M:%S')} ({RUNTIME_HOURS}h budget)")
    log(f"  Q&A model:   {QA_MODEL}")
    log(f"  Embed model: {EMBED_MODEL}")
    log(f"  Knowledge DB: {DB_PATH}")
    log(f"  Plugin dir:   {PLUGINS_DIR}")
    log(f"  ChromaDB:     {'available' if HAVE_CHROMA else 'not available (using SQLite fallback)'}")
    log("=" * 64)

    # Pre-flight
    log("Waiting for Ollama...")
    if not wait_ollama(90):
        log("Ollama not reachable on :11434 — start with: ollama serve", "ERROR")
        sys.exit(1)
    log("Ollama up ✓")

    test_emb = embed("warmup")
    if not test_emb:
        log(f"Embedding model {EMBED_MODEL} not responding. Pull it:", "ERROR")
        log(f"  ollama pull {EMBED_MODEL}", "ERROR")
        sys.exit(1)
    log(f"Embeddings OK — {len(test_emb)} dims ✓")

    try:
        _post("/api/generate", {
            "model": QA_MODEL, "prompt": "Reply: READY",
            "stream": False, "options": {"num_predict": 5},
        }, timeout=60)
        log(f"{QA_MODEL} OK ✓")
    except Exception as e:
        log(f"{QA_MODEL} warmup: {e} — continuing anyway", "WARN")

    db = KDB(DB_PATH)

    # Phase 1 — runs most of the night
    p1 = knowledge_phase(db)

    # Phases 2 and 3 — run in remaining time
    p2 = evolution_phase() if not out_of_time() else {}
    p3 = scripts_phase()   if not out_of_time() else {}

    # Phase 4 — always runs
    final = db.stats()
    log("=" * 64)
    log(f"ALL PHASES COMPLETE — {(datetime.now()-START_TIME).total_seconds()/3600:.2f}h elapsed")
    log(f"  DB: {final['files']} files / {final['chunks']} chunks / {final['qa']} Q&A pairs")
    log("=" * 64)

    write_report(db, p1, p2, p3)

    db.close()
    if CHECKPOINT.exists():
        CHECKPOINT.unlink()

    log("Done. Good morning! ☀️  →  open ~/Desktop/adwi-evolution-report-*.md")


if __name__ == "__main__":
    main()
