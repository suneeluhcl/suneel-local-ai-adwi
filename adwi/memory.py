"""
Adwi Memory Layer — local SQLite + Ollama embedding store.
Persistent semantic ledger of terminal commands, git commits, and project notes.
Exposed to Open WebUI via /memory-context injection into prompts.

Usage (CLI):
    python3 memory.py scan     — index terminal + git + notes
    python3 memory.py recall <query>
    python3 memory.py context <query>
    python3 memory.py stats
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

HOME        = Path.home()
WORKSPACE   = HOME / "SuneelWorkSpace"
ADWI_DIR    = WORKSPACE / "adwi"
NOTES_DIR   = WORKSPACE / "notes"
DB_PATH     = ADWI_DIR / "memory.db"
OLLAMA_URL  = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"   # 274MB, already installed

_SKIP_SOURCES = re.compile(
    r"^(ls|cd|pwd|history|clear|exit|cat|echo|man|which|top|ps|df|du"
    r"|brew\s+install|brew\s+upgrade|pip\s+install|pip3\s+install"
    r"|git\s+(add|commit|push|pull|status|log|diff|fetch|checkout|merge)\b"
    r"|python3?\s+-[cm]\s+\w)",
    re.I,
)
_SKIP_SECRET = re.compile(
    r"(password|passwd|token|secret|bearer|api.?key|private.?key|access.?key"
    r"|auth.?token|credential)\s*[=:\s]",
    re.I,
)
_SKIP_PATH_DUMP = re.compile(r"^/\S+$")   # bare absolute paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    content_hash TEXT    NOT NULL,
    tags         TEXT    NOT NULL DEFAULT '[]',
    embedding    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hash   ON memories (content_hash);
CREATE INDEX       IF NOT EXISTS idx_source  ON memories (source);
CREATE INDEX       IF NOT EXISTS idx_ts      ON memories (ts);
"""

_MIGRATE_V2 = [
    "ALTER TABLE memories ADD COLUMN importance_score REAL NOT NULL DEFAULT 0.5",
    "ALTER TABLE memories ADD COLUMN recency_decay    REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE memories ADD COLUMN provenance       TEXT NOT NULL DEFAULT 'direct'",
    "CREATE INDEX IF NOT EXISTS idx_importance ON memories (importance_score)",
]


# ── Pure-Python vector math (no numpy) ──────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ── Core class ───────────────────────────────────────────────────────────────

class AdwiMemory:

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)
        self._migrate_v2()
        self.conn.commit()

    def _migrate_v2(self) -> None:
        """Add Phase 3 scoring columns to existing DBs without touching existing rows."""
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(memories)").fetchall()}
        for stmt in _MIGRATE_V2:
            col = stmt.split("ADD COLUMN")[1].strip().split()[0] if "ADD COLUMN" in stmt else None
            if col and col in existing:
                continue
            if "CREATE INDEX" in stmt:
                try:
                    self.conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass
                continue
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists from a prior migration
        self.conn.commit()

    # ── Embedding ────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> Optional[list]:
        try:
            payload = json.dumps({
                "model": EMBED_MODEL,
                "prompt": text[:4096],
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/embeddings",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read()).get("embedding")
        except Exception:
            return None

    # ── Write ─────────────────────────────────────────────────────────────────

    def store(
        self,
        content: str,
        source: str,
        tags: list = None,
        provenance: str = "direct",
        importance_score: float = 0.5,
    ) -> bool:
        """Insert one memory. Returns True if new, False if duplicate."""
        content = content.strip()
        if len(content) < 20:
            return False
        h = _sha256(content)
        tags_json = json.dumps(tags or [])
        ts = datetime.now().isoformat(timespec="seconds")
        embedding = self._embed(content)
        emb_json  = json.dumps(embedding) if embedding else None
        try:
            self.conn.execute(
                "INSERT INTO memories "
                "(ts, source, content, content_hash, tags, embedding, importance_score, recency_decay, provenance) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, source, content, h, tags_json, emb_json, importance_score, 1.0, provenance),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # already stored

    # ── Read ──────────────────────────────────────────────────────────────────

    def recall(self, query: str, k: int = 5, threshold: float = 0.25) -> list:
        """Semantic vector search. Falls back to keyword if embeddings unavailable."""
        q_emb = self._embed(query)
        if not q_emb:
            return self.recall_keyword(query, k=k)

        rows = self.conn.execute(
            "SELECT id, ts, source, content, tags, embedding FROM memories "
            "WHERE embedding IS NOT NULL"
        ).fetchall()

        scored = []
        for row in rows:
            try:
                emb = json.loads(row[5])
            except Exception:
                continue
            sim = _cosine(q_emb, emb)
            if sim >= threshold:
                scored.append({
                    "id": row[0], "ts": row[1], "source": row[2],
                    "content": row[3], "tags": json.loads(row[4]),
                    "score": round(sim, 4),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    def recall_keyword(self, query: str, k: int = 10) -> list:
        """BM25-lite keyword fallback for when embeddings are cold."""
        words = [w.lower() for w in re.split(r'\W+', query) if len(w) > 3]
        if not words:
            return []
        clause = " OR ".join(f"LOWER(content) LIKE ?" for _ in words)
        params = [f"%{w}%" for w in words] + [k]
        rows = self.conn.execute(
            f"SELECT id, ts, source, content, tags "
            f"FROM memories WHERE {clause} ORDER BY ts DESC LIMIT ?",
            params,
        ).fetchall()
        return [{
            "id": r[0], "ts": r[1], "source": r[2],
            "content": r[3], "tags": json.loads(r[4]), "score": 0.0,
        } for r in rows]

    def format_context(self, query: str, k: int = 5) -> str:
        """Return a compact block suitable for injecting into any prompt."""
        hits = self.recall(query, k=k)
        if not hits:
            hits = self.recall_keyword(query, k=k)
        if not hits:
            return ""
        lines = ["[Suneel's memory ledger — relevant context:]"]
        for h in hits:
            score_tag = f"{h['score']:.2f}" if h["score"] > 0 else "kw"
            lines.append(f"- [{h['ts'][:10]}][{h['source']}/{score_tag}] {h['content'][:220]}")
        return "\n".join(lines)

    # ── Scanners ─────────────────────────────────────────────────────────────

    def scan_terminal(self, n: int = 400) -> int:
        """Parse zsh/bash history and store meaningful commands."""
        for hist_file in [HOME / ".zsh_history", HOME / ".bash_history"]:
            if hist_file.exists():
                break
        else:
            return 0

        raw = hist_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        cmds = []
        for line in raw:
            # zsh extended format: ": timestamp:duration;command"
            if line.startswith(": ") and ";" in line:
                cmds.append(line.split(";", 1)[1].strip())
            else:
                cmds.append(line.strip())

        stored = 0
        for cmd in cmds[-n:]:
            if not cmd or len(cmd) < 12:
                continue
            if _SKIP_SOURCES.match(cmd):
                continue
            if _SKIP_SECRET.search(cmd):
                continue
            if _SKIP_PATH_DUMP.match(cmd):
                continue
            if self.store(f"Terminal: {cmd}", source="terminal", tags=["command"]):
                stored += 1
        return stored

    def scan_git_commits(self, workspace: Path = WORKSPACE, n: int = 60) -> int:
        """Store recent commit messages as developer-decision memories."""
        try:
            r = subprocess.run(
                ["git", "log", f"-{n}", "--pretty=format:%s — %b", "--no-merges"],
                capture_output=True, text=True, cwd=str(workspace), timeout=15,
            )
        except Exception:
            return 0
        if r.returncode != 0:
            return 0
        stored = 0
        for line in r.stdout.splitlines():
            line = line.strip(" —").strip()
            if not line:
                continue
            if self.store(f"Git commit: {line[:400]}", source="git", tags=["commit"]):
                stored += 1
        return stored

    def scan_notes(self, notes_dir: Path = NOTES_DIR, max_per_file: int = 15) -> int:
        """Chunk markdown notes into paragraphs and store as memories."""
        if not notes_dir.exists():
            return 0
        stored = 0
        for md in sorted(notes_dir.rglob("*.md")):
            if md.stat().st_size > 250_000:
                continue
            text = md.read_text(encoding="utf-8", errors="ignore")
            # Split on H1/H2/H3 headings or double blank lines
            chunks = re.split(r'\n#{1,3} |\n\n\n+', text)
            count = 0
            for chunk in chunks:
                chunk = chunk.strip()
                if len(chunk) < 50:
                    continue
                if self.store(chunk[:700], source="notes", tags=["notes", md.stem]):
                    stored += 1
                    count += 1
                if count >= max_per_file:
                    break
        return stored

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        total    = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        with_emb = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        by_src = dict(self.conn.execute(
            "SELECT source, COUNT(*) FROM memories GROUP BY source"
        ).fetchall())
        avg_imp = self.conn.execute(
            "SELECT AVG(importance_score) FROM memories"
        ).fetchone()[0] or 0.0
        return {
            "total": total, "with_embeddings": with_emb,
            "by_source": by_src, "avg_importance": round(avg_imp, 3),
        }

    # ── Phase 3: Lifecycle scoring & pruning ──────────────────────────────────

    def apply_recency_decay(self, half_life_days: float = 90.0) -> int:
        """
        Decay recency_decay for memories older than half_life_days.
        Uses exponential decay: decay = 0.5^(age_days / half_life_days).
        Returns number of rows updated.
        """
        rows = self.conn.execute(
            "SELECT id, ts FROM memories WHERE recency_decay > 0.05"
        ).fetchall()
        now = datetime.now()
        updated = 0
        for row_id, ts_str in rows:
            try:
                age_days = (now - datetime.fromisoformat(ts_str)).days
            except Exception:
                continue
            if age_days <= 0:
                continue
            new_decay = 0.5 ** (age_days / half_life_days)
            self.conn.execute(
                "UPDATE memories SET recency_decay = ? WHERE id = ?",
                (round(new_decay, 6), row_id),
            )
            updated += 1
        self.conn.commit()
        return updated

    def score_memories(self) -> int:
        """
        Recompute importance_score for all memories using a heuristic:
          - git commit memories: +0.2 (deliberate developer decisions)
          - notes memories: +0.1
          - terminal: base 0.3
          - longer content → higher score (up to +0.3)
          - multiplied by recency_decay
        Returns number of rows scored.
        """
        rows = self.conn.execute(
            "SELECT id, source, content, recency_decay FROM memories"
        ).fetchall()
        scored = 0
        for row_id, source, content, decay in rows:
            base = {"git": 0.7, "notes": 0.6, "terminal": 0.3, "manual": 0.8}.get(source, 0.5)
            length_bonus = min(len(content) / 2000, 0.3)
            raw_score = (base + length_bonus) * max(float(decay or 1.0), 0.05)
            importance = round(min(raw_score, 1.0), 4)
            self.conn.execute(
                "UPDATE memories SET importance_score = ? WHERE id = ?",
                (importance, row_id),
            )
            scored += 1
        self.conn.commit()
        return scored

    def prune_and_summarize(
        self,
        max_age_days: int = 365,
        min_importance: float = 0.2,
        summary_dest: Optional[Path] = None,
    ) -> dict:
        """
        Summarize memories older than max_age_days with importance < min_importance
        into a compact reference log, then delete the originals.

        Returns {"pruned": int, "summary_written": bool, "summary_path": str}.
        """
        cutoff = datetime.now().replace(
            year=datetime.now().year - (max_age_days // 365 or 1)
        ).isoformat(timespec="seconds")

        candidates = self.conn.execute(
            "SELECT id, ts, source, content FROM memories "
            "WHERE ts < ? AND importance_score < ? "
            "ORDER BY ts ASC LIMIT 200",
            (cutoff, min_importance),
        ).fetchall()

        if not candidates:
            return {"pruned": 0, "summary_written": False, "summary_path": ""}

        # Build compact reference block
        lines = [f"# Adwi Memory Archive — pruned on {datetime.now().strftime('%Y-%m-%d')}"]
        lines.append(f"# Source: {len(candidates)} low-importance memories older than {max_age_days} days\n")
        for _, ts, src, content in candidates:
            lines.append(f"[{ts[:10]}][{src}] {content[:180]}")
        summary_text = "\n".join(lines)

        # Write to archive file
        dest = summary_dest or (NOTES_DIR / "adwi-memory-archive.md")
        dest.parent.mkdir(parents=True, exist_ok=True)
        existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
        dest.write_text(existing + "\n\n" + summary_text, encoding="utf-8")

        # Delete pruned rows
        ids = [r[0] for r in candidates]
        self.conn.execute(
            f"DELETE FROM memories WHERE id IN ({','.join('?' * len(ids))})", ids
        )
        self.conn.commit()

        return {"pruned": len(ids), "summary_written": True, "summary_path": str(dest)}

    # ── Phase 3: Safety gate ──────────────────────────────────────────────────

    @staticmethod
    def classify_input_risk(text: str) -> str:
        """
        Classify a CLI input string into:
          SAFE             — read-only, no system mutation
          REVIEW-REQUIRED  — modifies local files, git, or services
          BLOCKED          — targets hard-blocked paths or destructive patterns

        Used as a reusable wrapper by adwi_cli.py command dispatch.
        """
        _BLOCKED = re.compile(
            r"(rm\s+-rf|git\s+push\s+--force|DROP\s+TABLE|format\s+disk"
            r"|diskutil\s+erase|/etc/passwd|/private/var|secrets/"
            r"|~/.ssh|~/.aws|~/.gnupg|/.kube|reboot|shutdown\s+-[rh])",
            re.I,
        )
        _REVIEW = re.compile(
            r"(git\s+commit|git\s+push\b|docker\s+compose\s+down|pip\s+install"
            r"|brew\s+install|brew\s+uninstall|rm\s+-r(?!f)|mv\s+\S+\s+/"
            r"|launchctl\s+(un)?load|chmod\s+[0-7]|pkill|killall"
            r"|/backup-now|/nightly-run|/self-heal|/patch-adwi)",
            re.I,
        )
        if _BLOCKED.search(text):
            return "BLOCKED"
        if _REVIEW.search(text):
            return "REVIEW-REQUIRED"
        return "SAFE"

    def close(self):
        self.conn.close()


# ── Phase 7: Qdrant-Driven Dynamic Few-Shot Routing ──────────────────────────

QDRANT_URL     = "http://localhost:6333"
NLU_COLLECTION = "nlu_fixtures"
NLU_VECTOR_DIM = 768   # nomic-embed-text output dimension

# 45 high-fidelity examples mapping colloquial phrasings to structured intents.
# Each entry: (user_phrase, intent, arguments_dict, reasoning)
NLU_SEED_FIXTURES: list[tuple[str, str, dict, str]] = [
    # ── disk / files ──────────────────────────────────────────────────────
    ("what's eating up my disk space",                   "disk_usage",   {},                                   "user wants storage breakdown"),
    ("how much space do I have left",                    "disk_usage",   {},                                   "storage space question"),
    ("show me files larger than 500mb",                  "large_files",  {"size_mb": 500},                     "explicit size threshold"),
    ("what are the biggest files on my machine",         "large_files",  {"size_mb": 100},                     "large file scan without threshold"),
    ("find files I haven't touched in a year",           "old_files",    {"days": 365},                        "age-based file search"),
    ("list files older than 6 months",                   "old_files",    {"days": 180},                        "six-month age threshold"),
    ("look for duplicate files in my downloads",         "duplicates",   {"path": "~/Downloads"},              "dedup scoped to folder"),
    ("are there any duplicate photos",                   "duplicates",   {},                                   "dedup without path"),
    ("suggest how to organize my desktop",               "organize",     {"path": "~/Desktop"},                "organization suggestion"),
    ("what can I clean up in my documents folder",       "cleanup",      {"path": "~/Documents"},              "cleanup suggestion with path"),
    ("read the file notes/adwi-roadmap.md",              "file_read",    {"path": "notes/adwi-roadmap.md"},    "explicit file path in read request"),
    ("find files related to docker in my workspace",     "file_search",  {"query": "docker"},                  "keyword file search"),
    ("list what's inside my SuneelWorkSpace",            "file_list",    {"path": "~/SuneelWorkSpace"},        "directory listing"),
    # ── web / browsing ────────────────────────────────────────────────────
    ("google what is langchain used for",                "web_search",   {"query": "what is langchain used for"}, "explicit web search request"),
    ("search online for best local LLM setups",         "web_search",   {"query": "best local LLM setups"},   "search online phrasing"),
    ("open https://grafana.com/docs",                   "browse",       {"url": "https://grafana.com/docs"},   "explicit URL browse"),
    ("scrape the page at https://news.ycombinator.com", "firecrawl",    {"url": "https://news.ycombinator.com"}, "scrape request"),
    ("use exa to find recent papers on RAG",             "exa_search",   {"query": "recent papers on RAG"},    "exa named explicitly"),
    ("tavily search for Qdrant best practices",          "tavily_search",{"query": "Qdrant best practices"},   "tavily named explicitly"),
    # ── media ─────────────────────────────────────────────────────────────
    ("summarize this youtube video https://youtu.be/xyz","youtube",     {"url": "https://youtu.be/xyz"},        "youtube URL provided"),
    ("what's in this image /tmp/screenshot.png",         "image",        {"path": "/tmp/screenshot.png"},       "image analysis with path"),
    ("draw me a futuristic robot in neon colors",        "generate_image",{"description": "futuristic robot in neon colors"}, "image generation request"),
    ("generate an illustration of a mountain sunrise",   "generate_image",{"description": "mountain sunrise"},  "image generation with subject"),
    # ── system & services ─────────────────────────────────────────────────
    ("are all my docker services running",               "status",       {},                                    "service health check"),
    ("check if n8n and qdrant are up",                   "status",       {},                                    "named service check"),
    ("run a health check on adwi",                       "doctor",       {},                                    "doctor / diagnostics"),
    ("how fast is adwi right now",                       "benchmark",    {},                                    "performance benchmark"),
    ("what should I build next in adwi",                 "what_next",    {},                                    "roadmap / next steps"),
    ("run the daily improvement routine",                "daily_improve",{},                                    "daily improve trigger"),
    ("fix adwi — it crashed on the last command",        "self_heal",    {},                                    "self-heal trigger"),
    # ── models / routing ──────────────────────────────────────────────────
    ("which model are you using right now",              "model_status", {},                                    "model routing query"),
    ("switch to local model",                            "use_local",    {},                                    "force local backend"),
    ("which tool should handle voice transcription",     "route",        {"query": "voice transcription"},      "semantic router query"),
    # ── memory & knowledge ────────────────────────────────────────────────
    ("what do you know about my obsidian setup",         "memory_recall",{"query": "obsidian setup"},          "personal memory recall"),
    ("scan and update your memories",                    "memory_scan",  {},                                    "memory scan trigger"),
    ("search my notes for anything about RAG pipelines", "obsidian_search",{"query": "RAG pipelines"},         "vault/notes search"),
    ("read my obsidian note about grafana dashboards",   "obsidian_read",{"query": "grafana dashboards"},       "read specific obsidian note"),
    ("write a note called 'adwi phase 7 complete'",      "obsidian_write",{"query": "adwi phase 7 complete"},  "write new note"),
    ("open today's daily note",                          "obsidian_daily",{},                                   "obsidian daily note"),
    # ── comms & git ───────────────────────────────────────────────────────
    ("show me unread emails",                            "gmail",        {"query": "is:unread"},                "unread email check"),
    ("emails from suneel about the project",             "gmail",        {"query": "from:suneel"},              "sender-filtered email"),
    ("what changed in git today",                        "git_status",   {},                                    "git status check"),
    ("backup my workspace to github now",                "backup_now",   {},                                    "immediate backup trigger"),
    ("speak out the current system status",              "voice_out",    {"description": "current system status"}, "TTS request"),
    # ── code / eval ───────────────────────────────────────────────────────
    ("run this python snippet: print('hello')",          "run_code",     {},                                    "execute python code"),
    ("patch adwi — the nlu pipeline is broken",          "patch_adwi",   {"query": "nlu pipeline broken"},     "aider repair request"),
    ("evaluate adwi intent routing accuracy",            "eval_adwi",    {},                                    "eval / test run"),
    # ── sync / capabilities / daily_improve ──────────────────────────────
    ("sync my knowledge",                                "sync",         {},                                    "knowledge sync trigger"),
    ("sync knowledge base to open webui",                "sync",         {},                                    "explicit sync command"),
    ("update open webui knowledge base",                 "sync",         {},                                    "sync phrased as update"),
    ("what can you do, adwi?",                           "capabilities", {},                                    "capability list — explicitly about adwi"),
    ("show me your capabilities",                        "capabilities", {},                                    "capability list phrased as show — your = adwi"),
    ("list all your features",                           "capabilities", {},                                    "feature list — your = adwi's features"),
    ("what commands does adwi support",                  "capabilities", {},                                    "adwi command list request"),
    ("make yourself better",                             "daily_improve",{},                                    "daily improve phrased colloquially"),
    ("run your daily improvement routine",               "daily_improve",{},                                    "daily improve explicit"),
    ("improve adwi today",                               "daily_improve",{},                                    "daily improve imperative"),
    # ── fix_error / self-repair ───────────────────────────────────────────
    ("I got a SyntaxError in adwi_cli.py line 42",      "fix_error",    {"query": "SyntaxError adwi_cli.py"},  "Python syntax error pasted"),
    ("NameError: name 'CMD_GIT' is not defined",         "fix_error",    {"query": "NameError CMD_GIT"},        "Python NameError pasted"),
    ("HTTP Error 400: Bad Request when calling cloud",   "fix_error",    {"query": "HTTP Error 400"},            "HTTP error string pasted"),
    ("AttributeError on line 523 of reason_engine.py",  "fix_error",    {"query": "AttributeError reason_engine"}, "attribute error pasted"),
    # ── image in sentence ────────────────────────────────────────────────
    ("analyze my screenshot ~/Desktop/error.png",        "image",        {"path": "~/Desktop/error.png"},        "image path embedded in sentence"),
    ("look at this image: /tmp/screenshot.png",          "image",        {"path": "/tmp/screenshot.png"},        "image path after colon"),
    ("describe what's in /Users/MAC/Pictures/photo.jpg", "image",        {"path": "/Users/MAC/Pictures/photo.jpg"}, "full absolute image path"),
    # ── backup ────────────────────────────────────────────────────────────
    ("backup my workspace to GitHub",                    "backup_now",   {},                                    "backup phrased with GitHub"),
    ("push a backup right now",                          "backup_now",   {},                                    "backup as push variant"),
    # ── self_heal vs fix_error distinction ───────────────────────────────
    ("something is broken, repair adwi",                 "self_heal",    {},                                    "self-heal — general repair, no specific error"),
    ("adwi is acting weird, fix it",                     "self_heal",    {},                                    "vague broken state → self_heal not fix_error"),
    # ── rag_search (notes about X) ────────────────────────────────────────
    ("find notes about Ollama",                          "rag_search",   {"query": "Ollama"},                   "rag search phrased as find notes"),
    ("search my notes for LangGraph",                    "rag_search",   {"query": "LangGraph"},                "rag search with 'my notes' phrasing"),
    # ── browse (fetch page) ───────────────────────────────────────────────
    ("fetch this page and summarize it",                 "browse",       {},                                    "browse phrased as fetch+summarize"),
    ("go to https://openai.com and tell me what's there","browse",       {"url": "https://openai.com"},         "browse with 'go to' verb"),
    # ── what_next ─────────────────────────────────────────────────────────
    ("what should I build next?",                        "what_next",    {},                                    "roadmap query — what next"),
    ("what's the next thing to add to adwi",             "what_next",    {},                                    "what_next — next feature query"),
    # ── chat fallback — conversational, advisory, and knowledge questions ──
    ("what is the transformer attention mechanism",      "chat",         {},                                    "general knowledge question"),
    ("explain how LangGraph works",                      "chat",         {},                                    "explanation request — chat"),
    # Advisory / recommendation — these must NEVER route to capabilities or sync
    ("I keep running out of quota on claude, what should I do",
                                                         "chat",         {},                                    "subscription advisory → chat, not capabilities"),
    ("what is the best alternative to claude for my use case",
                                                         "chat",         {},                                    "tool comparison advisory → chat"),
    ("how do I manage my AI subscriptions better",       "chat",         {},                                    "subscription management advice → chat"),
    ("I need to cut costs on my AI tools",               "chat",         {},                                    "cost advice → chat"),
    ("help me decide between gpt-4 and claude",          "chat",         {},                                    "model comparison → chat"),
    ("what is the difference between claude and gemini", "chat",         {},                                    "model comparison question → chat"),
    ("should I use local models or cloud models",        "chat",         {},                                    "architecture advice → chat"),
    ("how do I add more buttons to home assistant",      "chat",         {},                                    "HA how-to question → chat, not capabilities"),
    ("I want to enhance my home assistant dashboard",    "chat",         {},                                    "HA enhancement request → chat"),
    ("what are the best practices for prompt engineering","chat",        {},                                    "general best-practices question → chat"),
    ("explain what ollama does",                         "chat",         {},                                    "tool explanation → chat"),
    ("how does RAG work",                                "chat",         {},                                    "technical explanation → chat"),
    ("what is the best way to organise my notes",        "chat",         {},                                    "advice on notes organisation → chat"),
]


def _qdrant_request(method: str, path: str, body: dict | None = None, timeout: int = 8) -> dict | None:
    """Thin wrapper for Qdrant REST calls using stdlib urllib."""
    url = f"{QDRANT_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        return None
    except Exception:
        return None


def provision_nlu_fixtures(embed_fn=None) -> dict:
    """
    Ensure the nlu_fixtures Qdrant collection exists and is seeded.
    embed_fn(text) -> list[float] — defaults to inline Ollama call.
    Returns {"created": bool, "seeded": int, "already_existed": bool}.
    """
    def _default_embed(text: str) -> list | None:
        payload = json.dumps({"model": EMBED_MODEL, "prompt": text[:4096]}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read()).get("embedding")
        except Exception:
            return None

    embed = embed_fn or _default_embed

    # Check if collection already exists
    existing = _qdrant_request("GET", f"/collections/{NLU_COLLECTION}")
    already_existed = existing is not None and existing.get("status") == "ok"

    if not already_existed:
        _qdrant_request("PUT", f"/collections/{NLU_COLLECTION}", {
            "vectors": {"size": NLU_VECTOR_DIM, "distance": "Cosine"},
        })

    # Count existing points to decide whether to seed
    info = _qdrant_request("GET", f"/collections/{NLU_COLLECTION}")
    n_existing = 0
    if info:
        n_existing = (info.get("result") or {}).get("points_count", 0)

    if n_existing >= len(NLU_SEED_FIXTURES):
        return {"created": not already_existed, "seeded": 0, "already_existed": already_existed}

    # Upsert all seed fixtures (idempotent — deterministic IDs from fixture index)
    points = []
    for idx, (phrase, intent, arguments, reasoning) in enumerate(NLU_SEED_FIXTURES):
        vec = embed(phrase)
        if not vec or len(vec) != NLU_VECTOR_DIM:
            continue
        points.append({
            "id": idx + 1,
            "vector": vec,
            "payload": {
                "user_phrase": phrase,
                "intent": intent,
                "arguments": arguments,
                "reasoning": reasoning,
            },
        })

    if points:
        _qdrant_request("PUT", f"/collections/{NLU_COLLECTION}/points", {"points": points})

    return {"created": not already_existed, "seeded": len(points), "already_existed": already_existed}


def query_nlu_fixtures(text: str, embed_fn=None, k: int = 3) -> list[dict]:
    """
    Embed `text`, query Qdrant nlu_fixtures for top-k semantic matches.
    Returns list of payload dicts: {user_phrase, intent, arguments, reasoning}.
    Falls back to [] on any error (never blocks the main NLU path).
    """
    def _default_embed(t: str) -> list | None:
        payload = json.dumps({"model": EMBED_MODEL, "prompt": t[:4096]}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("embedding")
        except Exception:
            return None

    embed = embed_fn or _default_embed
    vec = embed(text)
    if not vec or len(vec) != NLU_VECTOR_DIM:
        return []

    result = _qdrant_request("POST", f"/collections/{NLU_COLLECTION}/points/search", {
        "vector": vec,
        "limit": k,
        "with_payload": True,
        "score_threshold": 0.5,
    })
    if not result:
        return []
    hits = (result.get("result") or [])
    return [h["payload"] for h in hits if "payload" in h]


# ── Open WebUI integration guide ─────────────────────────────────────────────
# To inject memory context into Open WebUI prompts:
#
#   1. Add a System Prompt prefix in Open WebUI Settings → Models → System Prompt:
#      "Before answering, I will give you relevant context from Suneel's memory."
#
#   2. Use the /memory-context <query> command in adwi_cli.py to get the context
#      block and paste it at the start of your Open WebUI session.
#
#   3. Automated injection via n8n:
#      - Trigger: HTTP webhook from adwi_cli.py
#      - Node: Run `python3 memory.py context "{{ $json.query }}"` via SSH/exec
#      - Append output to the Open WebUI message payload as a system message
#
# ── CLI ───────────────────────────────────────────────────────────────────────

def _main():
    cmd   = sys.argv[1] if len(sys.argv) > 1 else "stats"
    query = " ".join(sys.argv[2:])

    mem = AdwiMemory()

    if cmd == "scan":
        print("Scanning terminal history...")
        t = mem.scan_terminal()
        print(f"  +{t} terminal memories")

        print("Scanning git commits...")
        g = mem.scan_git_commits()
        print(f"  +{g} git memories")

        print("Scanning notes...")
        n = mem.scan_notes()
        print(f"  +{n} note memories")

        s = mem.stats()
        print(f"\nLedger total: {s['total']} ({s['with_embeddings']} with embeddings)")
        print(f"By source: {s['by_source']}")

    elif cmd == "recall":
        if not query:
            print("Usage: python3 memory.py recall <query>")
            sys.exit(1)
        hits = mem.recall(query) or mem.recall_keyword(query)
        if not hits:
            print("No matches.")
        for h in hits:
            score = f"{h['score']:.3f}" if h["score"] > 0 else " kw "
            print(f"\n[{score}] {h['source']:8s} {h['ts'][:10]}")
            print(f"  {h['content'][:240]}")

    elif cmd == "context":
        if not query:
            print("Usage: python3 memory.py context <query>")
            sys.exit(1)
        ctx = mem.format_context(query)
        print(ctx if ctx else "No relevant context found.")

    elif cmd == "store":
        if not query:
            print("Usage: python3 memory.py store <content>")
            sys.exit(1)
        ok = mem.store(query, source="manual", tags=["manual"])
        print("Stored." if ok else "Duplicate — already in ledger.")

    elif cmd == "stats":
        s = mem.stats()
        print(json.dumps(s, indent=2))

    elif cmd == "provision-nlu":
        print("Provisioning Qdrant nlu_fixtures collection…")
        result = provision_nlu_fixtures()
        print(json.dumps(result, indent=2))

    elif cmd == "query-nlu":
        if not query:
            print("Usage: python3 memory.py query-nlu <text>")
            sys.exit(1)
        hits = query_nlu_fixtures(query)
        if not hits:
            print("No matches (Qdrant may be cold or collection empty).")
        for h in hits:
            print(f'\n  [{h["intent"]}] "{h["user_phrase"]}"')
            print(f"   args: {json.dumps(h.get('arguments', {}))}")
            print(f"   why:  {h.get('reasoning', '')}")

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: scan | recall <q> | context <q> | store <text> | stats | provision-nlu | query-nlu <q>")

    mem.close()


if __name__ == "__main__":
    _main()
