#!/usr/bin/env python3
"""
overnight_learn.py — Autonomous Self-Reflection & Knowledge Indexing Loop
Runs for 7 hours unattended: crawl → chunk → generate Q&A → embed → SQLite vector store → morning brief

ZERO pip installs required — uses only Python stdlib + Ollama's HTTP API.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO RUN (pick one and go to sleep):

  Foreground (watch it work):
      python3 ~/SuneelWorkSpace/overnight_learn.py

  Background (close lid and sleep):
      nohup python3 ~/SuneelWorkSpace/overnight_learn.py \
            > /tmp/overnight-learn.log 2>&1 &
      echo "Running as PID $! — check: tail -f /tmp/overnight-learn.log"

  tmux (safer for long runs):
      tmux new -s overnight
      python3 ~/SuneelWorkSpace/overnight_learn.py
      # Ctrl+B then D to detach safely

Check progress any time:
      tail -40 /tmp/overnight-learn.log

Output:
  ~/Desktop/morning_brief.md          ← read this when you wake up
  ~/SuneelWorkSpace/adwi/knowledge.db ← SQLite vector DB with all Q&A
  /tmp/overnight-learn.log            ← live progress log
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

WORKSPACE_DIR = Path.home() / "SuneelWorkSpace"   # root folder to scan

OLLAMA_URL   = "http://127.0.0.1:11434"
QA_MODEL     = "adwi:latest"       # Qwen3 MoE 30B — primary reasoning model
EMBED_MODEL  = "nomic-embed-text"  # 274MB, already installed
FAST_MODEL   = "qwen3:0.6b"        # fallback if adwi:latest is slow

RUNTIME_HOURS     = 7              # total runtime budget
QUESTIONS_PER_CHUNK = 3            # Q&A pairs per chunk (3 is a good balance)
CHUNK_CHARS       = 2400           # chars per chunk (fits 30B context well)
CHUNK_OVERLAP     = 150            # overlap so concepts aren't split cold

DB_PATH     = WORKSPACE_DIR / "adwi" / "knowledge.db"
DESKTOP     = Path.home() / "Desktop"
LOG_PATH    = Path("/tmp/overnight-learn.log")
CHECKPOINT  = Path("/tmp/overnight-learn-checkpoint.json")

# File types to index
TARGET_EXTS = {
    ".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".c", ".h",
    ".rb", ".swift", ".kt", ".sh", ".bash", ".zsh",
    ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini",
    ".html", ".css", ".sql",
}

# Directories to skip entirely
SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".idea", ".vscode", "open-webui-data", "n8n-data",
    "qdrant-data", "searxng-data", "ollama-blobs", ".npm", "models",
    "rag-db", "training-data", ".pytest_cache", "coverage", ".mypy_cache",
}

MAX_FILE_BYTES = 180_000   # skip files larger than ~180KB
MIN_FILE_BYTES = 80        # skip stub files

# ═══════════════════════════════════════════════════════════════════════════════

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

def time_budget_str() -> str:
    elapsed = datetime.now() - START_TIME
    remain  = DEADLINE - datetime.now()
    if remain.total_seconds() <= 0:
        return "TIME UP"
    eh, em = divmod(int(elapsed.total_seconds()), 3600)
    rh, rm = divmod(int(remain.total_seconds()), 3600)
    return f"elapsed={eh:02d}h{em:02d}m  left={rh:02d}h{rm:02d}m"


# ── SQLite vector store ───────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text  TEXT    NOT NULL,
    chunk_hash  TEXT    NOT NULL UNIQUE,
    embedding   TEXT
);
CREATE TABLE IF NOT EXISTS qa_pairs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    chunk_id    INTEGER,
    question    TEXT    NOT NULL,
    answer      TEXT    NOT NULL,
    qa_hash     TEXT    NOT NULL UNIQUE,
    embedding   TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunk_fp ON chunks  (file_path);
CREATE INDEX IF NOT EXISTS idx_qa_fp    ON qa_pairs(file_path);
CREATE INDEX IF NOT EXISTS idx_qa_cid   ON qa_pairs(chunk_id);
"""


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()[:32]


def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class KnowledgeDB:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def chunk_exists(self, h: str) -> bool:
        return bool(
            self.conn.execute("SELECT 1 FROM chunks WHERE chunk_hash=?", (h,)).fetchone()
        )

    def insert_chunk(self, file_path: str, idx: int, text: str, emb: list) -> int:
        h  = _sha(text)
        ts = datetime.now().isoformat(timespec="seconds")
        try:
            cur = self.conn.execute(
                "INSERT INTO chunks (ts,file_path,chunk_index,chunk_text,chunk_hash,embedding)"
                " VALUES (?,?,?,?,?,?)",
                (ts, file_path, idx, text, h, json.dumps(emb) if emb else None),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            row = self.conn.execute(
                "SELECT id FROM chunks WHERE chunk_hash=?", (h,)
            ).fetchone()
            return row[0] if row else -1

    def qa_exists(self, h: str) -> bool:
        return bool(
            self.conn.execute("SELECT 1 FROM qa_pairs WHERE qa_hash=?", (h,)).fetchone()
        )

    def insert_qa(self, file_path: str, chunk_id: int, q: str, a: str, emb: list):
        h  = _sha(q + a)
        ts = datetime.now().isoformat(timespec="seconds")
        try:
            self.conn.execute(
                "INSERT INTO qa_pairs (ts,file_path,chunk_id,question,answer,qa_hash,embedding)"
                " VALUES (?,?,?,?,?,?,?)",
                (ts, file_path, chunk_id, q, a, h, json.dumps(emb) if emb else None),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def stats(self) -> dict:
        c = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        q = self.conn.execute("SELECT COUNT(*) FROM qa_pairs").fetchone()[0]
        f = self.conn.execute(
            "SELECT COUNT(DISTINCT file_path) FROM chunks"
        ).fetchone()[0]
        return {"chunks": c, "qa_pairs": q, "files": f}

    def all_qa(self, limit: int = 5000) -> list:
        rows = self.conn.execute(
            "SELECT question, answer, file_path, embedding FROM qa_pairs "
            "WHERE embedding IS NOT NULL LIMIT ?", (limit,)
        ).fetchall()
        return rows

    def search(self, query_emb: list, k: int = 5, threshold: float = 0.15) -> list:
        rows = self.all_qa()
        scored = []
        for q, a, fp, emb_json in rows:
            try:
                sim = _cosine(query_emb, json.loads(emb_json))
                if sim >= threshold:
                    scored.append({"q": q, "a": a, "file": fp, "score": sim})
            except Exception:
                continue
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    def files_indexed(self) -> list:
        rows = self.conn.execute(
            "SELECT DISTINCT file_path, COUNT(*) as n "
            "FROM chunks GROUP BY file_path ORDER BY n DESC"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def sample_questions(self, n: int = 8) -> list:
        rows = self.conn.execute(
            "SELECT question, file_path FROM qa_pairs ORDER BY RANDOM() LIMIT ?", (n,)
        ).fetchall()
        return [{"q": r[0], "file": r[1]} for r in rows]

    def close(self):
        self.conn.close()


# ── Ollama helpers ────────────────────────────────────────────────────────────

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


def wait_for_ollama(max_wait_secs: int = 90) -> bool:
    for _ in range(max_wait_secs // 3):
        if ollama_ok():
            return True
        time.sleep(3)
    return False


def embed(text: str, retries: int = 3) -> list:
    for attempt in range(retries):
        try:
            resp = _post(
                "/api/embeddings",
                {"model": EMBED_MODEL, "prompt": text[:4000]},
                timeout=25,
            )
            v = resp.get("embedding", [])
            if v:
                return v
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                log(f"embed() failed: {e}", "WARN")
    return []


def generate_qa(chunk_text: str, file_path: str, n: int = QUESTIONS_PER_CHUNK) -> list:
    """Call QA_MODEL to generate n complex Q&A pairs from a code chunk."""
    ext = Path(file_path).suffix.lstrip(".")
    lang = {
        "py": "Python", "js": "JavaScript", "ts": "TypeScript",
        "go": "Go", "rs": "Rust", "java": "Java", "cpp": "C++",
        "c": "C", "rb": "Ruby", "swift": "Swift", "kt": "Kotlin",
        "sh": "Shell script", "bash": "Bash", "sql": "SQL",
        "md": "Markdown documentation", "yaml": "YAML config",
        "toml": "TOML config", "json": "JSON config",
    }.get(ext, "source code")

    prompt = (
        f"You are a principal engineer doing a deep code review of this {lang} file.\n"
        f"FILE: {Path(file_path).name}\n\n"
        f"```{ext}\n{chunk_text[:2600]}\n```\n\n"
        f"Generate exactly {n} advanced technical Q&A pairs that a senior engineer "
        f"would want to know. Focus on:\n"
        f"  - Non-obvious design decisions and their tradeoffs\n"
        f"  - Edge cases, failure modes, and gotchas\n"
        f"  - Performance characteristics and complexity\n"
        f"  - Security implications if any\n"
        f"  - How this code interacts with surrounding systems\n\n"
        f"DO NOT ask basic 'what does this do' questions. Every answer must be "
        f"3-5 sentences and demonstrate expert-level understanding.\n\n"
        f"Return ONLY a JSON array — no prose, no markdown fences:\n"
        f'[{{"q":"...","a":"..."}},{{"q":"...","a":"..."}}]'
    )

    for attempt in range(3):
        try:
            resp = _post(
                "/api/generate",
                {
                    "model": QA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.75,
                        "num_predict": 2200,
                        "top_p": 0.92,
                        "repeat_penalty": 1.1,
                    },
                },
                timeout=200,
            )
            raw = resp.get("response", "").strip()

            # Strip any accidental markdown fences
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)

            # Extract the JSON array from the response
            m = re.search(r"\[[\s\S]*?\]", raw)
            if not m:
                # Try to find individual objects and reconstruct
                objs = re.findall(r'\{[^{}]+\}', raw)
                if objs:
                    raw = "[" + ",".join(objs) + "]"
                else:
                    raise ValueError("No JSON array found in response")
            else:
                raw = m.group(0)

            pairs = json.loads(raw)
            valid = [
                p for p in pairs
                if isinstance(p, dict)
                and isinstance(p.get("q"), str) and len(p["q"]) > 20
                and isinstance(p.get("a"), str) and len(p["a"]) > 40
            ]
            if valid:
                return valid[:n]

        except (json.JSONDecodeError, ValueError) as e:
            log(f"  JSON parse (attempt {attempt+1}/3): {e}", "WARN")
            time.sleep(3)
        except urllib.error.URLError as e:
            log(f"  Ollama timeout (attempt {attempt+1}/3): {e}", "WARN")
            time.sleep(8)
        except Exception as e:
            log(f"  generate_qa error (attempt {attempt+1}/3): {e}", "WARN")
            if attempt < 2:
                time.sleep(5)

    return []


# ── Synthetic synthesis pass (cross-file) ────────────────────────────────────

def synthesize_architecture(file_samples: list) -> str:
    """Ask the model to synthesize architectural insights from multiple files."""
    context = "\n\n---\n\n".join(
        f"FILE: {s['file']}\n```\n{s['text'][:600]}\n```"
        for s in file_samples[:6]
    )
    prompt = (
        f"You have analyzed these {len(file_samples)} files from a developer's workspace:\n\n"
        f"{context}\n\n"
        f"Provide a 5-paragraph architectural synthesis covering:\n"
        f"1. Overall system design patterns you observe\n"
        f"2. Data flow and component relationships\n"
        f"3. Key abstractions and their responsibilities\n"
        f"4. Technical debt or improvement opportunities\n"
        f"5. What a new engineer needs to understand first\n\n"
        f"Be specific — mention actual file names, function names, and patterns you saw."
    )
    try:
        resp = _post(
            "/api/generate",
            {
                "model": QA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.6, "num_predict": 1500},
            },
            timeout=240,
        )
        return resp.get("response", "").strip()
    except Exception as e:
        log(f"Architecture synthesis failed: {e}", "WARN")
        return ""


# ── File crawling and chunking ────────────────────────────────────────────────

def crawl_workspace(root: Path) -> list:
    files = []
    for path in sorted(root.rglob("*")):
        if out_of_time():
            break
        if not path.is_file():
            continue
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if path.suffix.lower() not in TARGET_EXTS:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < MIN_FILE_BYTES or size > MAX_FILE_BYTES:
            continue
        files.append(path)
    log(f"Crawled {root}: {len(files)} eligible files")
    return files


def chunk_text(text: str) -> list:
    """Split text into overlapping chunks. Returns list of (index, text) tuples."""
    chunks = []
    idx    = 0
    start  = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        # Try to break at a newline for semantic cleanliness
        if end < len(text):
            nl = text.rfind("\n", start + CHUNK_CHARS // 2, end)
            if nl > 0:
                end = nl + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append((idx, piece))
            idx += 1
        next_start = end - CHUNK_OVERLAP
        if next_start <= start:
            next_start = start + 1
        if next_start >= len(text) - 40:
            break
        start = next_start
    return chunks


# ── Checkpoint persistence ────────────────────────────────────────────────────

def load_checkpoint() -> set:
    if CHECKPOINT.exists():
        try:
            data = json.loads(CHECKPOINT.read_text())
            return set(data.get("done", []))
        except Exception:
            pass
    return set()


def save_checkpoint(done: set):
    try:
        CHECKPOINT.write_text(json.dumps({
            "done": list(done),
            "ts": datetime.now().isoformat(),
        }))
    except Exception:
        pass


# ── Morning brief ─────────────────────────────────────────────────────────────

def write_morning_brief(db: KnowledgeDB, arch_synthesis: str, hourly_log: list):
    s         = db.stats()
    all_files = db.files_indexed()
    samples   = db.sample_questions(n=8)
    runtime   = (datetime.now() - START_TIME).total_seconds() / 3600

    # File breakdown by extension
    by_ext: dict = {}
    for fp, _ in all_files:
        ext = Path(fp).suffix.lstrip(".") or "other"
        by_ext[ext] = by_ext.get(ext, 0) + 1

    # Top 15 files by chunk depth
    top_files = all_files[:15]

    brief = f"""# 🌅 Overnight Learning Complete — Morning Brief
**Date:** {datetime.now().strftime("%A, %B %d %Y")}
**Finished at:** {datetime.now().strftime("%I:%M %p")}
**Total runtime:** {runtime:.1f} hours

---

## 📊 What Was Built Overnight

| Metric | Result |
|---|---|
| Files deeply analyzed | **{s['files']}** |
| Text chunks indexed | **{s['chunks']}** |
| Synthetic Q&A pairs generated | **{s['qa_pairs']}** |
| Total knowledge items in DB | **{s['chunks'] + s['qa_pairs']}** |
| Vector database location | `{DB_PATH}` |

The knowledge database is now queryable via Adwi's `/memory-recall` or
directly via semantic search (see query example at the bottom).

---

## 📁 Files Indexed by Type

"""
    for ext, count in sorted(by_ext.items(), key=lambda x: -x[1]):
        brief += f"- **`.{ext}`** — {count} file(s)\n"

    brief += "\n---\n\n## 🔍 Deepest Analysis (most chunks extracted)\n\n"
    for fp, n_chunks in top_files:
        try:
            rel = Path(fp).relative_to(WORKSPACE_DIR)
        except ValueError:
            rel = Path(fp)
        brief += f"- `{rel}` — {n_chunks} chunk(s)\n"

    if len(all_files) > 15:
        brief += f"\n*…and {len(all_files) - 15} more files*\n"

    if arch_synthesis:
        brief += f"""
---

## 🏗️ Architectural Synthesis

*Generated by {QA_MODEL} after analyzing the codebase as a whole:*

{arch_synthesis}
"""

    brief += "\n---\n\n## 💬 Ask These Questions Right Now\n\n"
    brief += "*These were generated from your actual code — copy/paste into Open WebUI:*\n\n"
    for i, item in enumerate(samples, 1):
        try:
            rel = Path(item['file']).relative_to(WORKSPACE_DIR)
        except ValueError:
            rel = Path(item['file'])
        brief += f"**{i}.** {item['q']}\n"
        brief += f"   *(from `{rel}`)*\n\n"

    brief += f"""
---

## 🔧 How to Use Your New Knowledge Base

### Option A — Adwi CLI (immediate):
```
adwi                        # start adwi
/memory-recall <question>   # semantic search over all Q&A
/rag <question>             # RAG search over notes + indexed files
```

### Option B — Direct query script (paste in terminal):
```python
import json, math, sqlite3, urllib.request

def embed(text):
    body = json.dumps({{"model":"nomic-embed-text","prompt":text}}).encode()
    req  = urllib.request.Request(
        "http://127.0.0.1:11434/api/embeddings", body,
        {{"Content-Type":"application/json"}}
    )
    return json.loads(urllib.request.urlopen(req, timeout=15).read())["embedding"]

def cosine(a, b):
    dot = sum(x*y for x,y in zip(a,b))
    return dot / (math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(x*x for x in b)))

db   = sqlite3.connect("{DB_PATH}")
q    = "How does the NLU dispatcher classify user intents?"
qemb = embed(q)
rows = db.execute("SELECT question,answer,file_path,embedding FROM qa_pairs WHERE embedding IS NOT NULL").fetchall()
hits = sorted([(cosine(qemb,json.loads(r[3])),r) for r in rows],reverse=True)[:5]
for score,(question,answer,fp,_) in hits:
    print(f"[{{score:.3f}}] {{question}}")
    print(f"  {{answer[:200]}}\\n")
```

### Option C — Open WebUI knowledge upload:
Run `/rag-index` inside Adwi to sync the new Q&A into the Open WebUI
knowledge base for persistent model enrichment.

---

## 📋 Hourly Progress Log

"""
    for entry in hourly_log:
        brief += f"- {entry}\n"

    brief += f"\n---\n*Generated by `overnight_learn.py` · {QA_MODEL} · {EMBED_MODEL}*\n"
    brief += f"*Good morning, Suneel! Your AI is now significantly smarter about your codebase. ☀️*\n"

    DESKTOP.mkdir(parents=True, exist_ok=True)
    out = DESKTOP / "morning_brief.md"
    out.write_text(brief, encoding="utf-8")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    log("=" * 64)
    log("  OVERNIGHT SELF-REFLECTION & KNOWLEDGE INDEXING LOOP")
    log(f"  Workspace : {WORKSPACE_DIR}")
    log(f"  Q&A model : {QA_MODEL}  (Qwen3 MoE 30B)")
    log(f"  Embed model: {EMBED_MODEL}")
    log(f"  Budget    : {RUNTIME_HOURS} hours  (deadline: {DEADLINE.strftime('%H:%M:%S')})")
    log(f"  Output DB : {DB_PATH}")
    log("=" * 64)

    # ── Pre-flight ────────────────────────────────────────────────────────────
    log("Waiting for Ollama...")
    if not wait_for_ollama(90):
        log("Ollama not reachable on port 11434 — is it running?", "ERROR")
        log("Start it with: ollama serve", "ERROR")
        sys.exit(1)
    log("Ollama is up ✓")

    # Verify embedding model is available
    log(f"Warming up {EMBED_MODEL}...")
    test_emb = embed("test embedding warmup")
    if not test_emb:
        log(f"Embedding model {EMBED_MODEL} not responding — pull it first:", "ERROR")
        log(f"  ollama pull {EMBED_MODEL}", "ERROR")
        sys.exit(1)
    log(f"Embedding model OK — {len(test_emb)} dimensions ✓")

    # Verify Q&A model
    log(f"Warming up {QA_MODEL}...")
    try:
        _post("/api/generate", {
            "model": QA_MODEL, "prompt": "Reply with: READY",
            "stream": False, "options": {"num_predict": 5}
        }, timeout=60)
        log(f"{QA_MODEL} OK ✓")
    except Exception as e:
        log(f"{QA_MODEL} warmup failed: {e}", "WARN")
        log(f"Continuing anyway — will retry on first real call")

    # ── Setup ─────────────────────────────────────────────────────────────────
    db          = KnowledgeDB(DB_PATH)
    done_files  = load_checkpoint()
    hourly_log  = []
    file_samples_for_synthesis = []   # a few raw chunks for cross-file analysis

    hour_marker = START_TIME + timedelta(hours=1)

    # ── Phase 1: Crawl ────────────────────────────────────────────────────────
    log("\nPhase 1: Workspace crawl...")
    all_files = crawl_workspace(WORKSPACE_DIR)

    if not all_files:
        log("No eligible files found in workspace — check WORKSPACE_DIR setting", "ERROR")
        sys.exit(1)

    pass_number    = 1
    total_qa_ever  = 0
    total_chunks_ever = 0

    while not out_of_time():
        # Build the todo list for this pass
        todo = [f for f in all_files if str(f) not in done_files]

        if not todo:
            # All files done — start another pass with fresh Q&A generation
            pass_number += 1
            done_files = set()
            todo = all_files
            log(f"\n{'='*40}")
            log(f"Pass {pass_number} starting ({time_budget_str()})")
            log(f"All {len(all_files)} files indexed — generating fresh Q&A variants...")
            log(f"{'='*40}")

        files_this_pass = 0
        qa_this_pass    = 0

        for file_path in todo:
            if out_of_time():
                break

            try:
                rel = file_path.relative_to(WORKSPACE_DIR)
            except ValueError:
                rel = file_path

            # ── Phase 2: Chunk ────────────────────────────────────────────────
            try:
                raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                log(f"  skip {rel}: {e}", "WARN")
                done_files.add(str(file_path))
                continue

            chunks = chunk_text(raw_text)
            if not chunks:
                done_files.add(str(file_path))
                continue

            s_before = db.stats()
            file_new_qa = 0

            for chunk_idx, chunk_content in chunks:
                if out_of_time():
                    break

                chunk_hash = _sha(chunk_content)

                # ── Phase 3a: Embed raw chunk ─────────────────────────────────
                if not db.chunk_exists(chunk_hash):
                    chunk_emb = embed(chunk_content)
                    chunk_id  = db.insert_chunk(
                        str(file_path), chunk_idx, chunk_content, chunk_emb
                    )
                    total_chunks_ever += 1
                else:
                    row = db.conn.execute(
                        "SELECT id FROM chunks WHERE chunk_hash=?", (chunk_hash,)
                    ).fetchone()
                    chunk_id = row[0] if row else -1

                # Collect some raw chunks for the cross-file synthesis pass
                if len(file_samples_for_synthesis) < 8 and chunk_idx == 0:
                    file_samples_for_synthesis.append({
                        "file": str(rel), "text": chunk_content
                    })

                # ── Phase 3b: Generate Q&A for this chunk ────────────────────
                qa_pairs = generate_qa(chunk_content, str(file_path))
                if not qa_pairs:
                    time.sleep(1)  # brief pause before moving on
                    continue

                # ── Phase 3c: Embed Q&A and store ────────────────────────────
                for pair in qa_pairs:
                    q = pair.get("q", "").strip()
                    a = pair.get("a", "").strip()
                    if not q or not a or len(q) < 15:
                        continue
                    qa_text = f"Question: {q}\nAnswer: {a}"
                    qa_emb  = embed(qa_text)
                    db.insert_qa(str(file_path), chunk_id, q, a, qa_emb)
                    file_new_qa    += 1
                    qa_this_pass   += 1
                    total_qa_ever  += 1

                time.sleep(0.4)  # gentle pacing — keeps Ollama stable overnight

            # ── Per-file summary ──────────────────────────────────────────────
            s_after = db.stats()
            new_qa_count = s_after["qa_pairs"] - s_before["qa_pairs"]
            log(
                f"[P{pass_number}] {rel}  "
                f"chunks={len(chunks)}  new_qa={new_qa_count}  "
                f"db_total={s_after['qa_pairs']}  ({time_budget_str()})"
            )

            done_files.add(str(file_path))
            files_this_pass += 1
            save_checkpoint(done_files)

            # ── Hourly milestone log ──────────────────────────────────────────
            now = datetime.now()
            if now >= hour_marker:
                s = db.stats()
                entry = (
                    f"{now.strftime('%H:%M')} — "
                    f"{s['files']} files | {s['chunks']} chunks | {s['qa_pairs']} Q&A pairs"
                )
                hourly_log.append(entry)
                log(f"  ── HOURLY SNAPSHOT: {entry} ──")
                hour_marker = now + timedelta(hours=1)

        log(
            f"Pass {pass_number} complete: "
            f"{files_this_pass} files, {qa_this_pass} new Q&A pairs  ({time_budget_str()})"
        )

    # ── Cross-file synthesis (if time allowed enough data) ────────────────────
    arch_synthesis = ""
    if len(file_samples_for_synthesis) >= 3 and db.stats()["qa_pairs"] >= 10:
        log("\nGenerating cross-file architectural synthesis...")
        arch_synthesis = synthesize_architecture(file_samples_for_synthesis)
        if arch_synthesis:
            log("Architectural synthesis complete ✓")

    # ── Final stats ───────────────────────────────────────────────────────────
    final = db.stats()
    runtime_h = (datetime.now() - START_TIME).total_seconds() / 3600
    log("=" * 64)
    log(f"OVERNIGHT LOOP COMPLETE — {runtime_h:.2f}h elapsed")
    log(f"  Files analyzed : {final['files']}")
    log(f"  Chunks indexed : {final['chunks']}")
    log(f"  Q&A pairs      : {final['qa_pairs']}")
    log(f"  Passes         : {pass_number}")
    log("=" * 64)

    # ── Phase 4: Morning brief ────────────────────────────────────────────────
    log("\nWriting morning brief...")
    final_snapshot = (
        f"{datetime.now().strftime('%H:%M')} — FINAL: "
        f"{final['files']} files | {final['chunks']} chunks | {final['qa_pairs']} Q&A"
    )
    hourly_log.append(final_snapshot)

    brief_path = write_morning_brief(db, arch_synthesis, hourly_log)
    log(f"Morning brief written → {brief_path}")

    db.close()
    if CHECKPOINT.exists():
        CHECKPOINT.unlink()   # clean up checkpoint on successful completion

    log("\n✓ All done. Good morning! ☀️")
    log(f"  Open ~/Desktop/morning_brief.md to see what was learned.")


if __name__ == "__main__":
    main()
