#!/usr/bin/env python3
"""
workspace-brain MCP server
Local MCP server exposing SuneelWorkSpace agent-system intelligence.
Run via: uv run --with mcp python3 /Users/MAC/SuneelWorkSpace/mcp/server/main.py
"""

import json
import logging
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
WORKSPACE = pathlib.Path("/Users/MAC/SuneelWorkSpace")
AGENT_SYS = WORKSPACE / "agent-system"
AUTOLAB   = WORKSPACE / "autolab"
MCP_ROOT  = WORKSPACE / "mcp"
SERVER    = MCP_ROOT / "server"
CONFIG    = SERVER / "config" / "server_config.json"

def _load_cfg():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}

CFG = _load_cfg()

INDEX_DB    = pathlib.Path(CFG.get("index_db",    str(SERVER / "storage" / "memory_index.db")))
LOG_FILE    = pathlib.Path(CFG.get("log_file",    str(SERVER / "logs" / "mcp_server.log")))
ACCESS_LOG  = pathlib.Path(CFG.get("access_log",  str(SERVER / "logs" / "mcp_access.log")))
STATE_FILE  = pathlib.Path(CFG.get("state_file",  str(SERVER / "state" / "mcp_state.json")))
MAX_BYTES   = CFG.get("max_file_bytes_returned", 65536)
MAX_LINES   = CFG.get("max_log_lines_returned",  200)
DRY_RUN     = CFG.get("dry_run_mutating_tools",  False)

INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("workspace-brain")

def _access(tool: str, args: dict = {}) -> None:
    entry = json.dumps({"ts": _now(), "tool": tool, "args": args}) + "\n"
    try:
        with open(ACCESS_LOG, "a") as f:
            f.write(entry)
    except Exception:
        pass

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP("workspace-brain")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RESOURCE_MAP: dict = {}
_rm_path = SERVER / "config" / "resource_map.json"
try:
    RESOURCE_MAP = json.loads(_rm_path.read_text())["resources"]
except Exception:
    pass

def _read_workspace_file(rel_or_abs: str) -> str:
    """Read a file relative to WORKSPACE or as absolute path.
    Absolute paths that escape WORKSPACE are rejected."""
    p = pathlib.Path(rel_or_abs)
    if not p.is_absolute():
        p = WORKSPACE / rel_or_abs
    resolved = p.resolve()
    workspace_resolved = WORKSPACE.resolve()
    if not str(resolved).startswith(str(workspace_resolved) + os.sep) and resolved != workspace_resolved:
        return f"[Access denied: path escapes workspace: {rel_or_abs}]"
    if not p.exists():
        return f"[File not found: {p}]"
    try:
        text = p.read_text(errors="replace")
        if len(text) > MAX_BYTES:
            text = text[:MAX_BYTES] + f"\n\n[... truncated at {MAX_BYTES} bytes ...]"
        return text
    except Exception as e:
        return f"[Error reading {p}: {e}]"

def _safe_append(path: pathlib.Path, content: str, backup: bool = True) -> str:
    """Safely append content to a file, with optional backup."""
    if DRY_RUN:
        return f"[DRY RUN] Would append {len(content)} chars to {path}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup and path.exists():
            bak = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, bak)
        with open(path, "a") as f:
            f.write("\n" + content.strip() + "\n")
        log.info("Appended to %s", path)
        return f"Appended to {path.name}"
    except Exception as e:
        log.error("Append failed: %s", e)
        return f"Error: {e}"

def _update_mcp_state(key: str, value) -> None:
    try:
        data: dict = {}
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
        data[key] = value
        data["state_updated_at"] = _now()
        STATE_FILE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    except Exception as e:
        log.warning("State update failed: %s", e)

# ---------------------------------------------------------------------------
# SQLite index
# ---------------------------------------------------------------------------
def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(INDEX_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            source   TEXT NOT NULL,
            section  TEXT,
            category TEXT,
            tags     TEXT,
            content  TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
        USING fts5(source, section, category, tags, content, content='entries', content_rowid='id')
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
            INSERT INTO entries_fts(rowid, source, section, category, tags, content)
            VALUES (new.id, new.source, new.section, new.category, new.tags, new.content);
        END
    """)
    conn.commit()
    return conn

def _reindex_file(conn: sqlite3.Connection, path: pathlib.Path, category: str, source_label: str) -> int:
    """Parse a file into sections and index them. Returns count of entries added."""
    if not path.exists():
        return 0
    text = path.read_text(errors="replace")
    now = _now()
    count = 0

    if path.suffix == ".md":
        # Split on ## headings
        parts = re.split(r"\n(#+\s+.+)", text)
        section = "_preamble"
        buf = []
        chunks = [(section, text)]  # fallback: index whole file as one chunk
        if len(parts) > 1:
            chunks = []
            for i, part in enumerate(parts):
                if re.match(r"#+\s+", part.strip()):
                    if buf:
                        chunks.append((section, "\n".join(buf)))
                    section = part.strip().lstrip("#").strip()
                    buf = []
                else:
                    buf.append(part)
            if buf:
                chunks.append((section, "\n".join(buf)))
        for sec, body in chunks:
            body = body.strip()
            if len(body) < 10:
                continue
            tags = ",".join(re.findall(r"#\w+", body)[:10])
            conn.execute(
                "INSERT INTO entries (source, section, category, tags, content, indexed_at) VALUES (?,?,?,?,?,?)",
                (source_label, sec, category, tags, body[:4096], now)
            )
            count += 1

    elif path.suffix == ".json":
        body = text.strip()[:4096]
        conn.execute(
            "INSERT INTO entries (source, section, category, tags, content, indexed_at) VALUES (?,?,?,?,?,?)",
            (source_label, "_json", category, "", body, now)
        )
        count += 1

    elif path.suffix == ".tsv":
        lines = text.strip().splitlines()[:100]
        body = "\n".join(lines)[:4096]
        conn.execute(
            "INSERT INTO entries (source, section, category, tags, content, indexed_at) VALUES (?,?,?,?,?,?)",
            (source_label, "_tsv", category, "autolab,results", body, now)
        )
        count += 1

    conn.commit()
    return count

def build_index() -> dict:
    """Rebuild the full index from authoritative workspace files."""
    conn = _get_db()
    # Clear old entries
    conn.execute("DELETE FROM entries")
    try:
        conn.execute("DELETE FROM entries_fts")
    except Exception:
        pass
    conn.commit()

    sources = [
        # (path_rel_or_abs, category, label)
        ("agent-system/shared/AGENT_SYSTEM.md",       "instructions", "workspace-overview"),
        ("agent-system/shared/IDENTITY.md",            "instructions", "identity"),
        ("agent-system/shared/WORKFLOW_RULES.md",      "instructions", "workflow-rules"),
        ("agent-system/shared/SAFETY_BOUNDARIES.md",   "instructions", "safety-boundaries"),
        ("agent-system/shared/STARTUP_CHECKLIST.md",   "instructions", "startup-checklist"),
        ("agent-system/memory/MEMORY.md",              "memory",       "memory"),
        ("agent-system/memory/DECISIONS.md",           "memory",       "decisions"),
        ("agent-system/memory/SESSION_HANDOFF.md",     "memory",       "session-handoff"),
        ("agent-system/memory/NOTES.md",               "memory",       "notes"),
        ("agent-system/tasks/ACTIVE_TASKS.md",         "tasks",        "active-tasks"),
        ("agent-system/tasks/TASK_QUEUE.md",           "tasks",        "task-queue"),
        ("agent-system/tasks/COMPLETED_TASKS.md",      "tasks",        "completed-tasks"),
        ("agent-system/state/CURRENT_STATE.json",      "state",        "current-state"),
        ("agent-system/state/WORKSPACE_HEALTH.json",   "state",        "workspace-health"),
        ("autolab/current_frontier.md",                "autolab",      "autolab-frontier"),
        ("autolab/program.md",                         "autolab",      "autolab-program"),
        ("autolab/meta/insights.md",                   "autolab",      "autolab-insights"),
        ("autolab/meta/patterns.json",                 "autolab",      "autolab-patterns"),
        ("autolab/meta/failure_patterns.json",         "autolab",      "autolab-failures"),
        ("autolab/meta/learning_log.md",               "autolab",      "autolab-learning"),
        ("autolab/results.tsv",                        "autolab",      "autolab-results"),
        ("agent-system/logs/SESSION_LOG.md",                       "logs",         "session-log"),
        ("orchestrator/router/router.md",                          "orchestrator", "router-guide"),
        ("orchestrator/router/decision_policy.md",                 "orchestrator", "decision-policy"),
        ("orchestrator/router/agent_profiles.json",                "orchestrator", "agent-profiles"),
        ("orchestrator/router/task_types.json",                    "orchestrator", "task-types"),
        ("orchestrator/models/routing_patterns.json",              "orchestrator", "routing-patterns"),
        ("orchestrator/reports/agent_performance.md",              "orchestrator", "agent-performance"),
        ("orchestrator/state/current_routing_state.json",          "orchestrator", "routing-state"),
    ]

    total = 0
    indexed = []
    for rel, cat, label in sources:
        p = WORKSPACE / rel
        n = _reindex_file(conn, p, cat, label)
        if n:
            indexed.append(label)
            total += n

    conn.close()
    now = _now()
    index_meta = {
        "indexed_at": now,
        "total_entries": total,
        "sources_indexed": indexed,
    }
    (SERVER / "state" / "last_index.json").write_text(
        json.dumps(index_meta, indent=2) + "\n"
    )
    _update_mcp_state("last_reindex", now)
    log.info("Reindex complete: %d entries from %d sources", total, len(indexed))
    return index_meta

def _search_index(query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]:
    """Keyword search in the FTS index."""
    try:
        conn = _get_db()
        # Sanitize query for FTS5
        safe_q = " ".join(re.findall(r"\w+", query))
        if not safe_q:
            return []
        if category:
            rows = conn.execute(
                """SELECT e.source, e.section, e.category, e.content, e.indexed_at
                   FROM entries_fts f JOIN entries e ON f.rowid = e.id
                   WHERE entries_fts MATCH ? AND e.category = ?
                   ORDER BY rank LIMIT ?""",
                (safe_q, category, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT e.source, e.section, e.category, e.content, e.indexed_at
                   FROM entries_fts f JOIN entries e ON f.rowid = e.id
                   WHERE entries_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (safe_q, limit)
            ).fetchall()
        conn.close()
        return [
            {"source": r[0], "section": r[1], "category": r[2],
             "content": r[3][:1000], "indexed_at": r[4]}
            for r in rows
        ]
    except Exception as e:
        log.error("Search error: %s", e)
        return []

# ---------------------------------------------------------------------------
# RESOURCES
# ---------------------------------------------------------------------------

def _resource_from_map(uri: str) -> str:
    entry = RESOURCE_MAP.get(uri, {})
    if not entry:
        return f"[No resource map entry for {uri}]"
    rel = entry["file"]
    return _read_workspace_file(rel)

@mcp.resource("workspace://overview")
def res_overview() -> str:
    """Canonical workspace instructions (AGENT_SYSTEM.md)"""
    return _resource_from_map("workspace://overview")

@mcp.resource("workspace://identity")
def res_identity() -> str:
    """Agent identity and context"""
    return _resource_from_map("workspace://identity")

@mcp.resource("workspace://workflow-rules")
def res_workflow_rules() -> str:
    """Workflow rules"""
    return _resource_from_map("workspace://workflow-rules")

@mcp.resource("workspace://safety")
def res_safety() -> str:
    """Safety boundaries"""
    return _resource_from_map("workspace://safety")

@mcp.resource("workspace://startup-checklist")
def res_startup_checklist() -> str:
    """Startup checklist"""
    return _resource_from_map("workspace://startup-checklist")

@mcp.resource("workspace://memory")
def res_memory() -> str:
    """Persistent workspace memory"""
    return _resource_from_map("workspace://memory")

@mcp.resource("workspace://decisions")
def res_decisions() -> str:
    """Important workspace decisions"""
    return _resource_from_map("workspace://decisions")

@mcp.resource("workspace://handoff")
def res_handoff() -> str:
    """Latest session handoff"""
    return _resource_from_map("workspace://handoff")

@mcp.resource("workspace://notes")
def res_notes() -> str:
    """Temporary notes"""
    return _resource_from_map("workspace://notes")

@mcp.resource("workspace://tasks/active")
def res_tasks_active() -> str:
    """Active tasks"""
    return _resource_from_map("workspace://tasks/active")

@mcp.resource("workspace://tasks/queue")
def res_tasks_queue() -> str:
    """Task queue"""
    return _resource_from_map("workspace://tasks/queue")

@mcp.resource("workspace://tasks/completed")
def res_tasks_completed() -> str:
    """Completed tasks"""
    return _resource_from_map("workspace://tasks/completed")

@mcp.resource("workspace://state")
def res_state() -> str:
    """Current workspace state JSON"""
    return _resource_from_map("workspace://state")

@mcp.resource("workspace://health")
def res_health() -> str:
    """Workspace health JSON"""
    return _resource_from_map("workspace://health")

@mcp.resource("workspace://autolab/frontier")
def res_autolab_frontier() -> str:
    """Autolab current frontier"""
    return _resource_from_map("workspace://autolab/frontier")

@mcp.resource("workspace://autolab/program")
def res_autolab_program() -> str:
    """Autolab program and strategy"""
    return _resource_from_map("workspace://autolab/program")

@mcp.resource("workspace://autolab/insights")
def res_autolab_insights() -> str:
    """Autolab meta insights"""
    return _resource_from_map("workspace://autolab/insights")

@mcp.resource("workspace://autolab/patterns")
def res_autolab_patterns() -> str:
    """Autolab patterns JSON"""
    return _resource_from_map("workspace://autolab/patterns")

@mcp.resource("workspace://autolab/failures")
def res_autolab_failures() -> str:
    """Autolab failure patterns JSON"""
    return _resource_from_map("workspace://autolab/failures")

@mcp.resource("workspace://autolab/learning")
def res_autolab_learning() -> str:
    """Autolab learning log"""
    return _resource_from_map("workspace://autolab/learning")

@mcp.resource("workspace://logs/recent")
def res_logs_recent() -> str:
    """Recent session log"""
    p = AGENT_SYS / "logs" / "SESSION_LOG.md"
    if not p.exists():
        return "[Session log not found]"
    lines = p.read_text(errors="replace").splitlines()
    recent = lines[-MAX_LINES:] if len(lines) > MAX_LINES else lines
    return "\n".join(recent)

@mcp.resource("workspace://digest")
def res_digest() -> str:
    """Compact workspace knowledge digest: state + health + handoff + active tasks"""
    parts = []
    for label, key in [
        ("STATE", "workspace://state"),
        ("HEALTH", "workspace://health"),
        ("HANDOFF", "workspace://handoff"),
        ("ACTIVE TASKS", "workspace://tasks/active"),
    ]:
        parts.append(f"## {label}\n{_resource_from_map(key)}")
    return "\n\n---\n\n".join(parts)

@mcp.resource("workspace://mcp/state")
def res_mcp_state() -> str:
    """MCP subsystem state"""
    if not STATE_FILE.exists():
        return "{}"
    return STATE_FILE.read_text()

# ---------------------------------------------------------------------------
# OBSIDIAN BRAIN RESOURCES
# ---------------------------------------------------------------------------

def _get_obsidian_resource_content(folder_name: str) -> str:
    folder_path = WORKSPACE / "brain" / folder_name
    if not folder_path.exists():
        return f"No {folder_name} notes found."
    files = sorted(folder_path.glob("*.md"))
    if not files:
        return f"No {folder_name} notes found."
    lines = [f"# Obsidian Brain: {folder_name.capitalize()}\n"]
    for f in files:
        rel_path = f.relative_to(WORKSPACE)
        try:
            content = f.read_text(errors="replace")
            summary = ""
            for line in content.splitlines():
                if line.strip() and not line.startswith("#"):
                    summary = line.strip()[:100] + "..."
                    break
            lines.append(f"- **[[{f.stem}]]** ({rel_path})\n  {summary}\n")
        except Exception as e:
            lines.append(f"- **[[{f.stem}]]** ({rel_path}) (unreadable: {e})")
    return "\n".join(lines)

@mcp.resource("workspace://brain/ideas")
def res_brain_ideas() -> str:
    """List of all ideas in the Obsidian vault brain"""
    return _get_obsidian_resource_content("ideas")

@mcp.resource("workspace://brain/decisions")
def res_brain_decisions() -> str:
    """List of all decisions in the Obsidian vault brain"""
    return _get_obsidian_resource_content("decisions")

@mcp.resource("workspace://brain/workflows")
def res_brain_workflows() -> str:
    """List of all workflows in the Obsidian vault brain"""
    return _get_obsidian_resource_content("workflows")

@mcp.resource("workspace://brain/system")
def res_brain_system() -> str:
    """List of all system notes in the Obsidian vault brain"""
    return _get_obsidian_resource_content("system")

# ---------------------------------------------------------------------------
# OBSIDIAN BRAIN TOOLS
# ---------------------------------------------------------------------------

@mcp.tool()
def brain_read_note(title_or_path: str) -> str:
    """Read the content of a specific note from the Obsidian brain vault.
    
    Args:
        title_or_path: The title of the note (e.g. 'daily_improvements') or path (e.g. 'system/daily_improvements.md')
    """
    _access("brain_read_note", {"title_or_path": title_or_path})
    brain_dir = WORKSPACE / "brain"
    
    # 1. Try directly as a path relative to brain
    p = brain_dir / title_or_path
    if not p.suffix == ".md":
        p = p.with_suffix(".md")
    
    if p.exists() and p.is_file():
        # Prevent path escape
        try:
            p.resolve().relative_to(brain_dir.resolve())
            return p.read_text(errors="replace")
        except Exception:
            return "[Error: Access denied (path escapes brain vault)]"
            
    # 2. Try searching by title in all categories
    for cat in ["inbox", "ideas", "decisions", "workflows", "system", "learning", "experiments", "logs"]:
        p = brain_dir / cat / title_or_path
        if not p.suffix == ".md":
            p = p.with_suffix(".md")
        if p.exists() and p.is_file():
            return p.read_text(errors="replace")
            
    # 3. Try recursive search
    for p_file in brain_dir.rglob("*.md"):
        if p_file.stem.lower() == title_or_path.lower() or p_file.name.lower() == title_or_path.lower():
            return p_file.read_text(errors="replace")
            
    return f"[Error: Note '{title_or_path}' not found in Obsidian brain]"

@mcp.tool()
def brain_write_note(title: str, category: str, content: str, mode: str = "overwrite") -> str:
    """Create a new note or append to an existing note in the Obsidian brain vault.
    
    Args:
        title: Title of the note (e.g. 'Project Ideas' or 'daily_improvements')
        category: Subfolder name (e.g. 'inbox', 'ideas', 'decisions', 'workflows', 'system', 'learning', 'experiments', 'logs')
        content: Markdown content to write to the note
        mode: 'overwrite' to replace file content or 'append' to append at the end
    """
    _access("brain_write_note", {"title": title, "category": category, "mode": mode})
    brain_dir = WORKSPACE / "brain"
    
    # Validate category
    valid_categories = ["inbox", "ideas", "decisions", "workflows", "system", "learning", "experiments", "logs"]
    if category not in valid_categories:
        return f"[Error: Invalid category '{category}'. Must be one of {', '.join(valid_categories)}]"
        
    # Standardize filename
    clean_title = title
    if clean_title.endswith(".md"):
        clean_title = clean_title[:-3]
        
    p = brain_dir / category / clean_title
    p = p.with_suffix(".md")
    
    # Path traversal check
    try:
        p.resolve().relative_to(brain_dir.resolve())
    except Exception:
        return "[Error: Access denied (path escapes brain vault)]"
        
    p.parent.mkdir(parents=True, exist_ok=True)
    
    if mode == "append":
        if p.exists():
            existing = p.read_text(errors="replace")
            if not existing.endswith("\n"):
                existing += "\n"
            p.write_text(existing + content + "\n")
            return f"Successfully appended to note '{clean_title}' in '{category}'"
        else:
            p.write_text(content + "\n")
            return f"Successfully created and wrote note '{clean_title}' in '{category}'"
    else:
        p.write_text(content + "\n")
        return f"Successfully wrote note '{clean_title}' in '{category}' (overwrote existing if any)"

@mcp.tool()
def brain_search(query: str) -> str:
    """Search for notes in the Obsidian brain vault containing the query string (case-insensitive).
    
    Args:
        query: Search term (e.g. 'triage' or 'system')
    """
    _access("brain_search", {"query": query})
    brain_dir = WORKSPACE / "brain"
    results = []
    
    if not brain_dir.exists():
        return "Obsidian brain directory not found."
        
    query_lower = query.lower()
    for p_file in sorted(brain_dir.rglob("*.md")):
        try:
            content = p_file.read_text(errors="replace")
            if query_lower in content.lower() or query_lower in p_file.name.lower():
                matches = content.lower().count(query_lower)
                rel = p_file.relative_to(WORKSPACE)
                results.append(f"- **[[{p_file.stem}]]** ({rel}) - {matches} match(es)")
        except Exception:
            pass
            
    if not results:
        return f"No matches found for query '{query}' in Obsidian brain."
    return f"Search results for '{query}' in Obsidian brain:\n\n" + "\n".join(results)

@mcp.tool()
def brain_link_notes(source_title: str, target_title: str) -> str:
    """Add an Obsidian backlink from a source note to a target note.
    
    Args:
        source_title: The title of the source note to modify
        target_title: The title of the target note to link to (will be wrapped in [[backlinks]])
    """
    _access("brain_link_notes", {"source_title": source_title, "target_title": target_title})
    
    brain_dir = WORKSPACE / "brain"
    source_path = None
    for p_file in brain_dir.rglob("*.md"):
        if p_file.stem.lower() == source_title.lower() or p_file.name.lower() == source_title.lower():
            source_path = p_file
            break
            
    if not source_path:
        return f"[Error: Source note '{source_title}' not found in brain]"
        
    link_str = f"\n\nSee also: [[{target_title}]]\n"
    try:
        existing = source_path.read_text(errors="replace")
        source_path.write_text(existing + link_str)
        return f"Successfully added link [[{target_title}]] to note [[{source_title}]]"
    except Exception as e:
        return f"[Error adding link: {e}]"

# ---------------------------------------------------------------------------
# APPROVED MCP RESOURCES
# ---------------------------------------------------------------------------

@mcp.resource("workspace://github/status")
def res_github_status() -> str:
    """GitHub MCP integration status and summary"""
    return _resource_from_map("workspace://github/status")

@mcp.resource("workspace://filesystem/status")
def res_filesystem_status() -> str:
    """Filesystem MCP integration status and summary"""
    return _resource_from_map("workspace://filesystem/status")

@mcp.resource("workspace://shortcuts/status")
def res_shortcuts_status() -> str:
    """macOS Shortcuts MCP integration status and summary"""
    return _resource_from_map("workspace://shortcuts/status")

@mcp.resource("workspace://search/status")
def res_search_status() -> str:
    """Brave Search MCP integration status and summary"""
    return _resource_from_map("workspace://search/status")

# ---------------------------------------------------------------------------
# APPROVED MCP TOOLS
# ---------------------------------------------------------------------------

@mcp.tool()
def github_list_prs(repo: str = "") -> str:
    """List open pull requests for the repository using the GitHub MCP wrapper.
    
    Args:
        repo: Repository name (e.g. 'owner/repo'). Leave blank for default repository.
    """
    _access("github_list_prs", {"repo": repo})
    script = WORKSPACE / "scripts/mcp_github.py"
    if not script.exists():
        return "[Error: github-mcp script not found]"
    cmd = ["python3", str(script), "pr-list"]
    if repo:
        cmd += ["--repo", repo]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"[Error running github-mcp: {e}]"

@mcp.tool()
def github_create_issue(title: str, body: str = "", repo: str = "") -> str:
    """Create a new issue in the target repository using the GitHub MCP wrapper.
    
    Args:
        title: Title of the issue.
        body: Markdown description of the issue.
        repo: Repository name (e.g. 'owner/repo'). Leave blank for default repository.
    """
    _access("github_create_issue", {"title": title, "repo": repo})
    script = WORKSPACE / "scripts/mcp_github.py"
    if not script.exists():
        return "[Error: github-mcp script not found]"
    cmd = ["python3", str(script), "issue-create", title]
    if body:
        cmd += ["--body", body]
    if repo:
        cmd += ["--repo", repo]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"[Error running github-mcp: {e}]"

@mcp.tool()
def filesystem_list_dir(path: str) -> str:
    """List directory contents within SuneelWorkSpace using the Filesystem MCP wrapper.
    
    Args:
        path: Path to the folder (relative to workspace or absolute).
    """
    _access("filesystem_list_dir", {"path": path})
    script = WORKSPACE / "scripts/mcp_filesystem.py"
    if not script.exists():
        return "[Error: filesystem-mcp script not found]"
    try:
        res = subprocess.run(["python3", str(script), "list", path], capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"[Error running filesystem-mcp: {e}]"

@mcp.tool()
def filesystem_read_file(path: str) -> str:
    """Read file content within SuneelWorkSpace using the Filesystem MCP wrapper.
    
    Args:
        path: Path to the file (relative to workspace or absolute).
    """
    _access("filesystem_read_file", {"path": path})
    script = WORKSPACE / "scripts/mcp_filesystem.py"
    if not script.exists():
        return "[Error: filesystem-mcp script not found]"
    try:
        res = subprocess.run(["python3", str(script), "read", path], capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"[Error running filesystem-mcp: {e}]"

@mcp.tool()
def shortcuts_list() -> str:
    """List all available native macOS Shortcuts using the Shortcuts MCP wrapper."""
    _access("shortcuts_list")
    script = WORKSPACE / "scripts/mcp_shortcuts.py"
    if not script.exists():
        return "[Error: shortcuts-mcp script not found]"
    try:
        res = subprocess.run(["python3", str(script), "list"], capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"[Error running shortcuts-mcp: {e}]"

@mcp.tool()
def shortcuts_run(name: str) -> str:
    """Trigger a native macOS Shortcut by name using the Shortcuts MCP wrapper.
    
    Args:
        name: Name of the Shortcut to run (e.g. 'Workspace Clean')
    """
    _access("shortcuts_run", {"name": name})
    script = WORKSPACE / "scripts/mcp_shortcuts.py"
    if not script.exists():
        return "[Error: shortcuts-mcp script not found]"
    try:
        res = subprocess.run(["python3", str(script), "run", name], capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"[Error running shortcuts-mcp: {e}]"

@mcp.tool()
def search_web_brave(query: str) -> str:
    """Search the web for information using the Brave Search MCP wrapper.
    
    Args:
        query: Search term (e.g. 'Model Context Protocol servers')
    """
    _access("search_web_brave", {"query": query})
    script = WORKSPACE / "scripts/mcp_brave_search.py"
    if not script.exists():
        return "[Error: brave-search-mcp script not found]"
    try:
        res = subprocess.run(["python3", str(script), query], capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"[Error running brave-search-mcp: {e}]"

# ---------------------------------------------------------------------------
# TOOLS — READ
# ---------------------------------------------------------------------------

@mcp.tool()
def query_workspace_context(focus: str = "") -> str:
    """Return combined workspace context: overview, state, health, handoff, active tasks.
    Optionally filter by focus keyword."""
    _access("query_workspace_context", {"focus": focus})
    parts = {
        "overview":   _resource_from_map("workspace://overview"),
        "state":      _resource_from_map("workspace://state"),
        "health":     _resource_from_map("workspace://health"),
        "handoff":    _resource_from_map("workspace://handoff"),
        "tasks":      _resource_from_map("workspace://tasks/active"),
    }
    if focus:
        kw = focus.lower()
        filtered = {k: v for k, v in parts.items()
                    if kw in v.lower() or kw in k}
        if filtered:
            parts = filtered
    out = []
    for k, v in parts.items():
        out.append(f"## {k.upper()}\n{v[:3000]}")
    return "\n\n---\n\n".join(out)

@mcp.tool()
def get_current_state() -> str:
    """Return the current workspace state as JSON."""
    _access("get_current_state")
    return _resource_from_map("workspace://state")

@mcp.tool()
def get_recent_handoff() -> str:
    """Return the latest session handoff document."""
    _access("get_recent_handoff")
    return _resource_from_map("workspace://handoff")

@mcp.tool()
def search_memory(query: str, limit: int = 10) -> str:
    """Keyword search across workspace memory (MEMORY.md, DECISIONS.md, NOTES.md).
    Returns matching sections with source labels."""
    _access("search_memory", {"query": query})
    results = _search_index(query, category="memory", limit=limit)
    if not results:
        # Fallback: simple grep over file
        mem = _resource_from_map("workspace://memory")
        dec = _resource_from_map("workspace://decisions")
        combined = f"MEMORY:\n{mem}\n\nDECISIONS:\n{dec}"
        kw = query.lower()
        hits = [ln for ln in combined.splitlines() if kw in ln.lower()]
        if hits:
            return "Grep results:\n" + "\n".join(hits[:50])
        return f"No results for '{query}' in memory"
    lines = []
    for r in results:
        lines.append(f"[{r['source']}] #{r['section']}\n{r['content'][:500]}")
    return "\n\n---\n".join(lines)

@mcp.tool()
def search_decisions(query: str, limit: int = 10) -> str:
    """Keyword search across workspace decisions."""
    _access("search_decisions", {"query": query})
    results = _search_index(query, category="memory", limit=limit)
    dec_results = [r for r in results if "decision" in r["source"].lower()]
    if not dec_results:
        dec_results = results
    if not dec_results:
        text = _resource_from_map("workspace://decisions")
        kw = query.lower()
        hits = [ln for ln in text.splitlines() if kw in ln.lower()]
        return "Grep results:\n" + "\n".join(hits[:50]) if hits else f"No results for '{query}'"
    lines = [f"[{r['source']}] #{r['section']}\n{r['content'][:500]}" for r in dec_results]
    return "\n\n---\n".join(lines)

@mcp.tool()
def search_tasks(query: str, limit: int = 10) -> str:
    """Keyword search across active tasks, task queue, and completed tasks."""
    _access("search_tasks", {"query": query})
    results = _search_index(query, category="tasks", limit=limit)
    if not results:
        combined = (
            _resource_from_map("workspace://tasks/active") + "\n\n" +
            _resource_from_map("workspace://tasks/queue")
        )
        kw = query.lower()
        hits = [ln for ln in combined.splitlines() if kw in ln.lower()]
        return "Grep results:\n" + "\n".join(hits[:50]) if hits else f"No results for '{query}'"
    lines = [f"[{r['source']}] #{r['section']}\n{r['content'][:500]}" for r in results]
    return "\n\n---\n".join(lines)

@mcp.tool()
def search_autolab_results(query: str, limit: int = 10) -> str:
    """Search autolab experiment results, insights, and patterns."""
    _access("search_autolab_results", {"query": query})
    results = _search_index(query, category="autolab", limit=limit)
    if not results:
        tsv = (AUTOLAB / "results.tsv")
        if tsv.exists():
            kw = query.lower()
            hits = [ln for ln in tsv.read_text().splitlines() if kw in ln.lower()]
            return "\n".join(hits[:30]) if hits else f"No autolab results matching '{query}'"
        return f"No autolab results for '{query}'"
    lines = [f"[{r['source']}] #{r['section']}\n{r['content'][:500]}" for r in results]
    return "\n\n---\n".join(lines)

@mcp.tool()
def list_active_hypotheses() -> str:
    """List current autolab experiment queue and active hypotheses."""
    _access("list_active_hypotheses")
    queue_path = AUTOLAB / "experiment_queue.md"
    frontier = _resource_from_map("workspace://autolab/frontier")
    queue_content = _read_workspace_file(str(queue_path)) if queue_path.exists() else "[No experiment queue found]"
    return f"## FRONTIER\n{frontier}\n\n## EXPERIMENT QUEUE\n{queue_content}"

@mcp.tool()
def get_workspace_health() -> str:
    """Return workspace health status and issue count."""
    _access("get_workspace_health")
    return _resource_from_map("workspace://health")

@mcp.tool()
def get_recent_changes() -> str:
    """Return recent git status and last few commits from the workspace."""
    _access("get_recent_changes")
    try:
        status = subprocess.run(
            ["git", "-C", str(WORKSPACE), "status", "--short"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip() or "(no changes)"
        log_out = subprocess.run(
            ["git", "-C", str(WORKSPACE), "log", "--oneline", "-10"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip() or "(no commits)"
        return f"## GIT STATUS\n{status}\n\n## RECENT COMMITS\n{log_out}"
    except Exception as e:
        return f"[Error getting git changes: {e}]"

# ---------------------------------------------------------------------------
# TOOLS — MUTATING (write-bounded, append-only)
# ---------------------------------------------------------------------------

@mcp.tool()
def add_memory_note(note: str, tags: str = "") -> str:
    """Append a note to MEMORY.md. Use for stable facts worth remembering across sessions.
    note: the text to add. tags: optional comma-separated tags."""
    _access("add_memory_note", {"len": len(note), "tags": tags})
    stamp = _now()
    tag_str = f" [{tags}]" if tags else ""
    content = f"<!-- mcp-added {stamp}{tag_str} -->\n{note.strip()}"
    return _safe_append(AGENT_SYS / "memory" / "MEMORY.md", content)

@mcp.tool()
def add_decision(decision: str, reason: str = "", tags: str = "") -> str:
    """Append a decision to DECISIONS.md.
    decision: what was decided. reason: why. tags: optional."""
    _access("add_decision", {"len": len(decision)})
    stamp = _now()
    tag_str = f" [{tags}]" if tags else ""
    content = (
        f"<!-- mcp-added {stamp}{tag_str} -->\n"
        f"**Decision:** {decision.strip()}\n"
        + (f"**Reason:** {reason.strip()}\n" if reason else "")
    )
    return _safe_append(AGENT_SYS / "memory" / "DECISIONS.md", content)

@mcp.tool()
def add_task(task: str, queue: str = "active") -> str:
    """Add a task. queue='active' for ACTIVE_TASKS.md, queue='queue' for TASK_QUEUE.md."""
    _access("add_task", {"task": task[:80], "queue": queue})
    stamp = _now()
    content = f"<!-- mcp-added {stamp} -->\n- {task.strip()}"
    target = (
        AGENT_SYS / "tasks" / "ACTIVE_TASKS.md"
        if queue == "active"
        else AGENT_SYS / "tasks" / "TASK_QUEUE.md"
    )
    return _safe_append(target, content)

@mcp.tool()
def update_task_status(task_substring: str, new_status: str) -> str:
    """Find a task line containing task_substring in ACTIVE_TASKS.md and mark it with new_status.
    new_status examples: DONE, IN-PROGRESS, BLOCKED, CANCELLED."""
    _access("update_task_status", {"substring": task_substring[:80], "status": new_status})
    if DRY_RUN:
        return f"[DRY RUN] Would update task matching '{task_substring}' to {new_status}"
    path = AGENT_SYS / "tasks" / "ACTIVE_TASKS.md"
    if not path.exists():
        return "ACTIVE_TASKS.md not found"
    bak = path.with_suffix(".md.bak")
    shutil.copy2(path, bak)
    lines = path.read_text().splitlines()
    updated = 0
    stamp = _now()
    new_lines = []
    for ln in lines:
        if task_substring.lower() in ln.lower():
            new_lines.append(f"{ln}  <!-- [{new_status}] {stamp} -->")
            updated += 1
        else:
            new_lines.append(ln)
    path.write_text("\n".join(new_lines) + "\n")
    log.info("update_task_status: updated %d lines", updated)
    return f"Updated {updated} task line(s) with status [{new_status}]"

@mcp.tool()
def append_session_note(note: str) -> str:
    """Append a note to SESSION_LOG.md for the current session."""
    _access("append_session_note", {"len": len(note)})
    stamp = _now()
    content = f"### MCP Note — {stamp}\n{note.strip()}"
    return _safe_append(AGENT_SYS / "logs" / "SESSION_LOG.md", content, backup=False)

@mcp.tool()
def create_handoff_draft(summary: str, changed: str = "", verification: str = "",
                          open_items: str = "") -> str:
    """Write a handoff draft to SESSION_HANDOFF.md.
    summary: what happened. changed: comma-separated list. verification: what was checked.
    open_items: what still needs doing."""
    _access("create_handoff_draft")
    stamp = _now()[:10]
    content = textwrap.dedent(f"""\
        # Session Handoff

        ## Latest Handoff

        Date: {stamp}

        Summary: {summary.strip()}

        Changed:
        {chr(10).join('- ' + c.strip() for c in changed.split(',') if c.strip()) or '- (none recorded)'}

        Verification:
        {verification.strip() or '- (none recorded)'}

        Open Items:
        {chr(10).join('- ' + o.strip() for o in open_items.split(',') if o.strip()) or '- (none)'}
        """)
    if DRY_RUN:
        return f"[DRY RUN] Would write handoff ({len(content)} chars)"
    path = AGENT_SYS / "memory" / "SESSION_HANDOFF.md"
    bak = path.with_suffix(".md.bak")
    if path.exists():
        shutil.copy2(path, bak)
    path.write_text(content)
    log.info("Wrote handoff draft")
    return f"Handoff draft written to {path.name}"

# ---------------------------------------------------------------------------
# TOOLS — OPERATIONS
# ---------------------------------------------------------------------------

@mcp.tool()
def trigger_reindex() -> str:
    """Rebuild the workspace knowledge index from authoritative files."""
    _access("trigger_reindex")
    try:
        meta = build_index()
        return (
            f"Reindex complete.\n"
            f"Entries: {meta['total_entries']}\n"
            f"Sources: {', '.join(meta['sources_indexed'])}"
        )
    except Exception as e:
        log.error("Reindex failed: %s", e)
        return f"Reindex failed: {e}"

@mcp.tool()
def run_workspace_doctor() -> str:
    """Run agent-doctor and return the output (read-only health check)."""
    _access("run_workspace_doctor")
    bin_path = WORKSPACE / "bin" / "agent-doctor"
    if not bin_path.exists():
        return "[agent-doctor not found]"
    try:
        result = subprocess.run(
            [str(bin_path)], capture_output=True, text=True, timeout=30,
            env={**os.environ, "SUNEEL_WORKSPACE": str(WORKSPACE)}
        )
        out = (result.stdout + result.stderr).strip()
        return out[:4096] or "(no output)"
    except subprocess.TimeoutExpired:
        return "[agent-doctor timed out]"
    except Exception as e:
        return f"[Error running agent-doctor: {e}]"

@mcp.tool()
def run_workspace_repair_safe() -> str:
    """Run agent-repair with --quiet flag (safe bounded repairs only)."""
    _access("run_workspace_repair_safe")
    bin_path = WORKSPACE / "bin" / "agent-repair"
    if not bin_path.exists():
        return "[agent-repair not found]"
    if DRY_RUN:
        return "[DRY RUN] Would run agent-repair --quiet"
    try:
        result = subprocess.run(
            [str(bin_path), "--quiet"], capture_output=True, text=True, timeout=60,
            env={**os.environ, "SUNEEL_WORKSPACE": str(WORKSPACE)}
        )
        out = (result.stdout + result.stderr).strip()
        log.info("agent-repair ran, exit=%d", result.returncode)
        return out[:4096] or "(repair complete, no output)"
    except subprocess.TimeoutExpired:
        return "[agent-repair timed out]"
    except Exception as e:
        return f"[Error running agent-repair: {e}]"

@mcp.tool()
def generate_workspace_report() -> str:
    """Run workspace-report and return the output."""
    _access("generate_workspace_report")
    bin_path = WORKSPACE / "bin" / "workspace-report"
    if not bin_path.exists():
        return "[workspace-report not found]"
    try:
        result = subprocess.run(
            [str(bin_path)], capture_output=True, text=True, timeout=30,
            env={**os.environ, "SUNEEL_WORKSPACE": str(WORKSPACE)}
        )
        out = (result.stdout + result.stderr).strip()
        return out[:8192] or "(no output)"
    except subprocess.TimeoutExpired:
        return "[workspace-report timed out]"
    except Exception as e:
        return f"[Error: {e}]"

# ---------------------------------------------------------------------------
# PROMPTS / WORKFLOWS
# ---------------------------------------------------------------------------

@mcp.prompt()
def startup_context() -> str:
    """Compact startup context: state + health + handoff + tasks."""
    state = _resource_from_map("workspace://state")
    health = _resource_from_map("workspace://health")
    handoff = _resource_from_map("workspace://handoff")
    tasks = _resource_from_map("workspace://tasks/active")
    return (
        f"# Workspace Startup Context\n\n"
        f"## Current State\n{state[:2000]}\n\n"
        f"## Health\n{health[:1000]}\n\n"
        f"## Latest Handoff\n{handoff[:2000]}\n\n"
        f"## Active Tasks\n{tasks[:1500]}"
    )

@mcp.prompt()
def closeout_context() -> str:
    """What to update when closing a session."""
    return textwrap.dedent("""\
        # Session Closeout Checklist

        Use the workspace-brain MCP tools to close out properly:

        1. create_handoff_draft(summary, changed, verification, open_items)
        2. append_session_note(brief note about what happened)
        3. update_task_status for any completed tasks
        4. add_memory_note for any new stable facts
        5. add_decision for any important choices made

        Or run: ~/SuneelWorkSpace/bin/agent-finish "summary"
        """)

@mcp.prompt()
def workspace_status_brief() -> str:
    """Brief one-page workspace status."""
    health_raw = _resource_from_map("workspace://health")
    try:
        h = json.loads(health_raw)
        health_line = f"Status: {h.get('status','?')} | Issues: {h.get('issue_count',0)} | Errors: {h.get('error_count',0)}"
    except Exception:
        health_line = health_raw[:200]
    state_raw = _resource_from_map("workspace://state")
    try:
        s = json.loads(state_raw)
        state_line = f"Last activity: {s.get('last_activity_timestamp','?')} | Session: {s.get('status','?')}"
    except Exception:
        state_line = state_raw[:200]
    tasks = _resource_from_map("workspace://tasks/active")
    task_lines = [ln for ln in tasks.splitlines() if ln.strip().startswith("-")][:5]
    return (
        f"# Workspace Status Brief\n\n"
        f"**Health:** {health_line}\n"
        f"**State:** {state_line}\n\n"
        f"**Active Tasks (top 5):**\n" + "\n".join(task_lines or ["(none)"])
    )

@mcp.prompt()
def autolab_summary() -> str:
    """Autolab learning and experiment summary."""
    frontier = _resource_from_map("workspace://autolab/frontier")
    insights = _resource_from_map("workspace://autolab/insights")
    failures = _resource_from_map("workspace://autolab/failures")
    return (
        f"# Autolab Summary\n\n"
        f"## Current Frontier\n{frontier[:1500]}\n\n"
        f"## Insights\n{insights[:2000]}\n\n"
        f"## Failure Patterns\n{failures[:1000]}"
    )

@mcp.prompt()
def maintenance_summary() -> str:
    """What maintenance has been run and what the workspace needs."""
    state = _resource_from_map("workspace://state")
    health = _resource_from_map("workspace://health")
    index_meta_path = SERVER / "state" / "last_index.json"
    index_meta = index_meta_path.read_text() if index_meta_path.exists() else "{}"
    return (
        f"# Maintenance Summary\n\n"
        f"## State\n{state[:1000]}\n\n"
        f"## Health\n{health[:800]}\n\n"
        f"## Last MCP Reindex\n{index_meta}"
    )

# ---------------------------------------------------------------------------
# ORCHESTRATOR — resources, tools, prompt
# ---------------------------------------------------------------------------

ORCH = WORKSPACE / "orchestrator"

def _read_orch(rel: str) -> str:
    p = ORCH / rel
    if not p.exists():
        return f"[{p.name} not found — run route-analyze to generate]"
    text = p.read_text(errors="replace")
    return text[:MAX_BYTES] if len(text) > MAX_BYTES else text

@mcp.resource("workspace://routing/state")
def res_routing_state() -> str:
    """Current orchestrator routing state"""
    return _read_orch("state/current_routing_state.json")

@mcp.resource("workspace://routing/history")
def res_routing_history() -> str:
    """Routing decision history (last 50 entries)"""
    p = ORCH / "router" / "history.json"
    if not p.exists():
        return "[No routing history yet]"
    try:
        data = json.loads(p.read_text())
        entries = data.get("entries", [])[-50:]
        return json.dumps({"entries": entries, "total": data.get("_meta", {}).get("entry_count", 0)}, indent=2)
    except Exception as e:
        return f"[Error reading routing history: {e}]"

@mcp.resource("workspace://routing/performance")
def res_routing_performance() -> str:
    """Agent performance report"""
    return _read_orch("reports/agent_performance.md")

@mcp.resource("workspace://routing/patterns")
def res_routing_patterns() -> str:
    """Learned routing patterns"""
    return _read_orch("models/routing_patterns.json")

@mcp.resource("workspace://routing/profiles")
def res_routing_profiles() -> str:
    """Agent capability profiles"""
    return _read_orch("router/agent_profiles.json")

@mcp.resource("workspace://routing/logs")
def res_routing_logs() -> str:
    """Recent routing decision logs"""
    p = ORCH / "router" / "routing_logs.md"
    if not p.exists():
        return "[No routing logs yet]"
    lines = p.read_text(errors="replace").splitlines()
    recent = lines[-MAX_LINES:] if len(lines) > MAX_LINES else lines
    return "\n".join(recent)

@mcp.tool()
def route_task(task: str, dry_run: bool = False) -> str:
    """Classify a task and recommend the best agent (Claude or Codex) to handle it.
    Returns: agent, task_type, confidence, reasoning, and optional hybrid suggestion.
    dry_run=True logs nothing and is safe to call for exploration."""
    _access("route_task", {"task": task[:100], "dry_run": dry_run})
    script = ORCH / "scripts" / "route-task"
    if not script.exists():
        return "[route-task script not found]"
    try:
        flags = ["--json"]
        if dry_run:
            flags.append("--dry-run")
        result = subprocess.run(
            ["python3", str(script)] + flags + [task],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "SUNEEL_WORKSPACE": str(WORKSPACE)}
        )
        out = result.stdout.strip()
        if not out:
            return f"[route-task produced no output: {result.stderr[:200]}]"
        return out
    except subprocess.TimeoutExpired:
        return "[route-task timed out]"
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def get_agent_recommendation(task: str) -> str:
    """Get a human-readable routing recommendation for a task.
    Shows: recommended agent, task type, confidence, and reasoning."""
    _access("get_agent_recommendation", {"task": task[:100]})
    script = ORCH / "scripts" / "route-task"
    if not script.exists():
        return "[route-task script not found]"
    try:
        result = subprocess.run(
            ["python3", str(script), "--dry-run", task],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "SUNEEL_WORKSPACE": str(WORKSPACE)}
        )
        return (result.stdout + result.stderr).strip() or "[No output]"
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def get_agent_performance() -> str:
    """Return the agent performance report showing success rates per task type."""
    _access("get_agent_performance")
    return _read_orch("reports/agent_performance.md")

@mcp.tool()
def get_routing_history(limit: int = 20) -> str:
    """Return recent routing decisions from history.json."""
    _access("get_routing_history", {"limit": limit})
    p = ORCH / "router" / "history.json"
    if not p.exists():
        return "[No routing history yet]"
    try:
        data = json.loads(p.read_text())
        entries = data.get("entries", [])[-limit:]
        total = data.get("_meta", {}).get("entry_count", 0)
        lines = [f"Total decisions: {total}\n"]
        for e in reversed(entries):
            ts = e.get("timestamp", "")[:19]
            agent = e.get("agent", "?").upper()
            tt = e.get("task_type", "?")
            conf = e.get("confidence", 0)
            outcome = e.get("outcome", "pending")
            task = e.get("task", "")[:60]
            lines.append(f"{ts} | {agent:8} | {tt:<20} | {conf:.2f} | {outcome:<8} | {task}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def run_routing_learn() -> str:
    """Run route-learn to update routing patterns and agent profiles from history."""
    _access("run_routing_learn")
    script = ORCH / "scripts" / "route-learn"
    if not script.exists():
        return "[route-learn not found]"
    try:
        result = subprocess.run(
            ["python3", str(script)],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "SUNEEL_WORKSPACE": str(WORKSPACE)}
        )
        return (result.stdout + result.stderr).strip()[:4096] or "(no output)"
    except subprocess.TimeoutExpired:
        return "[route-learn timed out]"
    except Exception as e:
        return f"[Error: {e}]"

@mcp.prompt()
def routing_context() -> str:
    """Orchestrator context: agent profiles, routing state, recent decisions."""
    profiles = _read_orch("router/agent_profiles.json")
    state = _read_orch("state/current_routing_state.json")
    perf = _read_orch("reports/agent_performance.md")
    return (
        f"# Orchestrator Context\n\n"
        f"## Agent Profiles\n{profiles[:2000]}\n\n"
        f"## Routing State\n{state[:500]}\n\n"
        f"## Performance\n{perf[:1500]}"
    )

# ---------------------------------------------------------------------------
# GSTACK — resources, tools, prompts
# ---------------------------------------------------------------------------

GSTACK_PATH = pathlib.Path.home() / ".claude" / "skills" / "gstack"
GSTACK_POLICY = WORKSPACE / "orchestrator" / "router" / "gstack_policy.json"
GSTACK_VERSION_CONFIG = WORKSPACE / "mcp" / "config" / "gstack_version.json"

def _gstack_skill_list() -> list[dict]:
    """Return list of available gstack skills with descriptions."""
    skills = []
    if not GSTACK_PATH.exists():
        return skills
    for entry in sorted(GSTACK_PATH.iterdir()):
        skill_md = entry / "SKILL.md"
        if skill_md.exists() and entry.is_dir():
            try:
                header = skill_md.read_text(errors="replace")[:400]
                desc = ""
                for line in header.splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
                        break
                skills.append({"skill": f"/{entry.name}", "description": desc, "path": str(skill_md)})
            except Exception:
                pass
    return skills

@mcp.resource("workspace://gstack/skills")
def res_gstack_skills() -> str:
    """Available gstack skills and their descriptions."""
    skills = _gstack_skill_list()
    if not skills:
        return "[gstack not installed — run: git clone https://github.com/garrytan/gstack ~/.claude/skills/gstack]"
    lines = ["# Available gstack Skills\n"]
    for s in skills:
        lines.append(f"- **{s['skill']}**: {s['description']}")
    return "\n".join(lines)

@mcp.resource("workspace://gstack/policy")
def res_gstack_policy() -> str:
    """gstack skill selection policy — maps task types to recommended skills."""
    if not GSTACK_POLICY.exists():
        return "[gstack_policy.json not found]"
    return GSTACK_POLICY.read_text(errors="replace")[:MAX_BYTES]

@mcp.tool()
def get_gstack_recommendation(task: str) -> str:
    """Get the recommended gstack skill for a task description.

    Runs route-task and extracts the gstack_skill field from the decision.
    Returns the skill name, hint, and how to invoke it.

    Args:
        task: Task description to classify
    """
    try:
        result = subprocess.run(
            [str(WORKSPACE / "orchestrator" / "scripts" / "route-task"), "--json", "--dry-run", task],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
        skill = data.get("gstack_skill")
        hint  = data.get("gstack_hint")
        agent = data.get("agent", "claude")
        ttype = data.get("task_type", "unknown")
        if skill:
            return (
                f"Task type: {ttype}\n"
                f"Agent: {agent}\n"
                f"Recommended gstack skill: {skill}\n"
                f"Why: {hint}\n"
                f"How to use: Open Claude Code and type `{skill}` at the start of your session."
            )
        else:
            return (
                f"Task type: {ttype}\n"
                f"Agent: {agent}\n"
                f"No specific gstack skill needed — use standard reasoning."
            )
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def list_available_gstack_skills() -> str:
    """List all gstack skills installed at ~/.claude/skills/gstack/ with descriptions."""
    skills = _gstack_skill_list()
    if not skills:
        return "[gstack not installed]"
    lines = [f"gstack skills ({len(skills)} total, at {GSTACK_PATH}):\n"]
    for s in skills:
        lines.append(f"  {s['skill']:25s}  {s['description']}")
    lines.append("\nKey skills for this workspace:")
    key = ["/investigate", "/cso", "/review", "/office-hours", "/plan-eng-review", "/ship", "/careful"]
    for k in key:
        match = next((s for s in skills if s["skill"] == k), None)
        if match:
            lines.append(f"  {k:25s}  {match['description']}")
    return "\n".join(lines)

@mcp.tool()
def suggest_cognitive_mode(task: str) -> str:
    """Suggest the best cognitive mode (gstack skill + agent) for a task.

    Returns a structured recommendation covering: agent, gstack skill,
    how to think about the task, and the expected output shape.

    Args:
        task: Task description
    """
    try:
        result = subprocess.run(
            [str(WORKSPACE / "orchestrator" / "scripts" / "route-task"), "--json", "--dry-run", task],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
    except Exception as e:
        return f"[Error classifying task: {e}]"

    skill = data.get("gstack_skill")
    hint  = data.get("gstack_hint")
    agent = data.get("agent", "claude")
    ttype = data.get("task_type", "unknown")
    conf  = data.get("confidence", 0.0)

    skill_modes = {
        "/investigate": "Systematic 5-phase debugging: Observe → Hypothesize → Test → Fix → Verify",
        "/cso": "Security threat model: STRIDE + OWASP Top 10 sweep, trust boundary analysis",
        "/review": "Pre-commit audit: auto-fix obvious bugs, flag production risks, check error paths",
        "/office-hours": "10-star product challenge: interrogate scope, find the real problem, tighten the plan",
        "/plan-eng-review": "Architecture lock: define interfaces, scope, dependencies, risks before coding",
        "/ship": "Release sequence: tests → diff review → version bump → CHANGELOG → PR",
        "/careful": "Safety preview: show commands before running, confirm destructive steps",
        "/qa": "Browser QA: navigate flows, screenshot, file bugs automatically",
    }

    lines = [
        f"Cognitive Mode Recommendation",
        f"  Task: {task[:80]}",
        f"  Classified as: {ttype} (confidence: {conf:.0%})",
        f"  Agent: {agent.upper()}",
    ]
    if skill:
        lines += [
            f"  gstack skill: {skill}",
            f"  Mode: {skill_modes.get(skill, hint or '')}",
            f"  Trigger: type `{skill}` in Claude Code at session start",
        ]
    else:
        lines.append("  Mode: Standard reasoning — no specific gstack skill needed")
    return "\n".join(lines)

# gstack supply chain security — version pin + integrity tools

def _gstack_integrity_status() -> dict:
    """Run gstack-verify and return parsed result dict."""
    verify_script = WORKSPACE / "bin" / "gstack-verify"
    if not verify_script.exists():
        return {"status": "error", "reason": "gstack-verify script not found"}
    try:
        result = subprocess.run(
            ["python3", str(verify_script), "--json"],
            capture_output=True, text=True, timeout=15
        )
        return json.loads(result.stdout)
    except Exception as e:
        return {"status": "error", "reason": str(e)}

@mcp.resource("workspace://gstack/version")
def res_gstack_version() -> str:
    """Pinned gstack version info — commit hash, version, and last verified timestamp."""
    if not GSTACK_VERSION_CONFIG.exists():
        return "[gstack version config not found — run: bin/gstack-verify]"
    return GSTACK_VERSION_CONFIG.read_text(errors="replace")

@mcp.resource("workspace://gstack/integrity")
def res_gstack_integrity() -> str:
    """Live gstack integrity check — compares installed commit to pinned commit."""
    data = _gstack_integrity_status()
    lines = [f"# gstack Integrity Status\n"]
    lines.append(f"Status: **{data.get('status', 'unknown').upper()}**")
    if data.get("pinned_commit"):
        lines.append(f"Pinned:  {data['pinned_commit'][:16]}  (v{data.get('pinned_version', '?')})")
    if data.get("issues"):
        lines.append("\nIssues:")
        for i in data["issues"]:
            lines.append(f"  - {i}")
        lines.append("\nRun `bin/gstack-repair` to restore the pinned version.")
    if data.get("checked_at"):
        lines.append(f"\nChecked: {data['checked_at']}")
    return "\n".join(lines)

@mcp.tool()
def get_gstack_version() -> str:
    """Return the pinned gstack version and install metadata.

    Shows: pinned commit hash, version tag, install path, last verified time,
    and the upgrade policy. Use verify_gstack_integrity() to check live status.
    """
    _access("get_gstack_version")
    if not GSTACK_VERSION_CONFIG.exists():
        return "[gstack_version.json not found — run bin/gstack-verify to initialise]"
    try:
        cfg = json.loads(GSTACK_VERSION_CONFIG.read_text())
        verify_status_file = WORKSPACE / "mcp" / "server" / "state" / "gstack_verify_status.json"
        if verify_status_file.exists():
            try:
                vcfg = json.loads(verify_status_file.read_text())
                cfg["last_verified"] = vcfg.get("last_verified")
                cfg["last_verified_status"] = vcfg.get("last_verified_status")
            except Exception:
                pass
        return (
            f"gstack Supply Chain Pin\n"
            f"  Version:        {cfg.get('pinned_version', 'unknown')}\n"
            f"  Commit:         {cfg.get('pinned_commit', 'unknown')[:16]}\n"
            f"  Install path:   {cfg.get('installed_path', '~/.claude/skills/gstack')}\n"
            f"  Mode:           {cfg.get('mode', 'pinned')}\n"
            f"  Last verified:  {cfg.get('last_verified', 'never')}\n"
            f"  Last status:    {cfg.get('last_verified_status', 'unknown')}\n"
            f"  Upgrade policy: {cfg.get('upgrade_policy', 'manual')}"
        )
    except Exception as e:
        return f"[Error reading version config: {e}]"

@mcp.tool()
def verify_gstack_integrity() -> str:
    """Run a live integrity check on the gstack install.

    Compares the installed commit to the pinned commit in mcp/config/gstack_version.json.
    Also checks for dirty working tree and broken skill symlinks.
    Returns OK, DRIFT, or ERROR.
    """
    _access("verify_gstack_integrity")
    data = _gstack_integrity_status()
    status = data.get("status", "error")
    if status == "ok":
        return (
            f"[gstack-verify] OK\n"
            f"  Version: {data.get('pinned_version', '?')}\n"
            f"  Commit:  {data.get('pinned_commit', '?')[:16]}\n"
            f"  Checked: {data.get('checked_at', 'now')}"
        )
    elif status == "drift":
        issues = "\n".join(f"  - {i}" for i in data.get("issues", []))
        return (
            f"[gstack-verify] DRIFT DETECTED\n"
            f"  Pinned:  {data.get('pinned_commit', '?')[:16]}\n"
            f"  Issues:\n{issues}\n"
            f"  Fix: run bin/gstack-repair"
        )
    else:
        return f"[gstack-verify] ERROR: {data.get('reason', 'unknown')}"

@mcp.tool()
def repair_gstack_if_needed() -> str:
    """Run gstack-repair in dry-run mode to see what would be fixed.

    This tool only PREVIEWS the repair (dry-run). To actually repair,
    run bin/gstack-repair directly in the terminal. This prevents
    accidental automated repo manipulation.
    """
    _access("repair_gstack_if_needed")
    repair_script = WORKSPACE / "bin" / "gstack-repair"
    if not repair_script.exists():
        return "[gstack-repair script not found]"
    try:
        result = subprocess.run(
            ["python3", str(repair_script), "--dry-run"],
            capture_output=True, text=True, timeout=15
        )
        out = (result.stdout + result.stderr).strip()
        return f"[gstack-repair dry-run]\n{out}\n\nTo apply: run `bin/gstack-repair` in terminal."
    except Exception as e:
        return f"[Error: {e}]"

# ---------------------------------------------------------------------------
# GOAL ENGINE — resources, tools, prompts
# ---------------------------------------------------------------------------

GOAL_ENGINE = WORKSPACE / "goal-engine"

def _read_ge(rel: str) -> str:
    p = GOAL_ENGINE / rel
    if not p.exists():
        return f"[{p.name} not found — run goal-status to generate]"
    text = p.read_text(errors="replace")
    return text[:MAX_BYTES] if len(text) > MAX_BYTES else text

@mcp.resource("workspace://goals/active")
def res_goals_active() -> str:
    """Active goals list"""
    return _read_ge("goals/active_goals.md")

@mcp.resource("workspace://goals/status")
def res_goals_status() -> str:
    """Goal engine state (counts, last execution, last monitor)"""
    return _read_ge("state/goal_state.json")

@mcp.resource("workspace://goals/graph")
def res_goals_graph() -> str:
    """Task graph (goals and tasks with dependencies)"""
    p = GOAL_ENGINE / "graph" / "task_graph.json"
    if not p.exists():
        return "[No task graph yet]"
    try:
        data = json.loads(p.read_text())
        active_goals = {gid: g for gid, g in data.get("goals", {}).items() if g.get("status") == "active"}
        active_task_ids = [tid for g in active_goals.values() for tid in g.get("tasks", [])]
        active_tasks = {tid: data["tasks"][tid] for tid in active_task_ids if tid in data.get("tasks", {})}
        return json.dumps({"goals": active_goals, "tasks": active_tasks}, indent=2)[:MAX_BYTES]
    except Exception as e:
        return f"[Error reading task graph: {e}]"

@mcp.resource("workspace://goals/history")
def res_goals_history() -> str:
    """Goal execution history log"""
    return _read_ge("execution/execution_log.md")

@mcp.tool()
def create_goal(description: str, priority: str = "medium", complexity: str = "medium", criteria: str = "") -> str:
    """Create a new goal in the goal engine. Returns the goal ID.

    Args:
        description: High-level description of what you want to achieve
        priority: low | medium | high | critical
        complexity: low | medium | high
        criteria: Success criteria (what 'done' looks like). Leave empty to auto-generate.
    """
    cmd = [str(GOAL_ENGINE / "scripts" / "goal-create"), "--json", description,
           "--priority", priority, "--complexity", complexity]
    if criteria:
        cmd += ["--criteria", criteria]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return f"[Error creating goal: {result.stderr.strip()}]"
        return result.stdout.strip()
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def plan_goal(goal_id: str) -> str:
    """Break a goal into tasks with dependencies. Must be called after create_goal.

    Args:
        goal_id: Goal ID returned by create_goal (e.g. G001)
    """
    try:
        result = subprocess.run(
            [str(GOAL_ENGINE / "scripts" / "goal-plan"), goal_id, "--json"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 2:
            return f"[Goal {goal_id} not found. Run create_goal first.]"
        return result.stdout.strip()[:4096]
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def get_goal_status(goal_id: str = "") -> str:
    """Get status of a specific goal or all active goals.

    Args:
        goal_id: Goal ID (e.g. G001), or empty string for all active goals
    """
    cmd = [str(GOAL_ENGINE / "scripts" / "goal-status")]
    if goal_id:
        cmd.append(goal_id)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()[:4096]
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def get_active_goals() -> str:
    """List all active goals with their task progress."""
    return _read_ge("goals/active_goals.md")

@mcp.tool()
def execute_goal(goal_id: str, dry_run: bool = True) -> str:
    """Show the next ready task(s) for a goal (dry_run=True) or queue them for execution.

    In dry_run mode (default), returns what would be executed without launching agents.
    Set dry_run=False to actually run tasks (requires interactive confirmation).

    Args:
        goal_id: Goal ID (e.g. G001)
        dry_run: If True (default), preview only. If False, execute.
    """
    cmd = [str(GOAL_ENGINE / "scripts" / "goal-execute"), goal_id]
    if dry_run:
        cmd.append("--dry-run")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (result.stdout + result.stderr).strip()[:4096]
    except Exception as e:
        return f"[Error: {e}]"

@mcp.tool()
def get_execution_log(limit: int = 20) -> str:
    """Get recent goal execution log entries.

    Args:
        limit: Max lines to return
    """
    p = GOAL_ENGINE / "execution" / "execution_log.md"
    if not p.exists():
        return "[No execution log yet]"
    lines = p.read_text(errors="replace").splitlines()
    recent = lines[-limit:] if len(lines) > limit else lines
    return "\n".join(recent)

@mcp.prompt()
def goal_context() -> str:
    """Goal engine context: active goals, current goal, task graph."""
    active = _read_ge("goals/active_goals.md")
    current = _read_ge("state/current_goal.json")
    state = _read_ge("state/goal_state.json")
    return (
        f"# Goal Engine Context\n\n"
        f"## Active Goals\n{active[:2000]}\n\n"
        f"## Current Goal\n{current[:1000]}\n\n"
        f"## System State\n{state[:500]}"
    )

@mcp.prompt()
def execution_summary() -> str:
    """Recent goal execution summary: what ran, what succeeded, what failed."""
    log = _read_ge("execution/execution_log.md")
    report = _read_ge("reports/goal_report.md")
    current_run = _read_ge("execution/current_run.json")
    return (
        f"# Execution Summary\n\n"
        f"## Current Run\n{current_run[:500]}\n\n"
        f"## Execution Log (recent)\n{log[-2000:] if len(log) > 2000 else log}\n\n"
        f"## Goal Report\n{report[:1500]}"
    )

# ---------------------------------------------------------------------------
# Startup: build index if empty
# ---------------------------------------------------------------------------
def _ensure_index():
    try:
        conn = _get_db()
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.close()
        if count == 0:
            log.info("Index is empty, building initial index")
            build_index()
        else:
            log.info("Index has %d entries, skipping rebuild", count)
    except Exception as e:
        log.warning("Could not check/build index: %s", e)

_update_mcp_state("server_started_at", _now())
_update_mcp_state("server_version", "1.0.0")
_ensure_index()
log.info("workspace-brain MCP server ready")

# ---------------------------------------------------------------------------
# COMMS — iMessage and Mail tools/resources
# ---------------------------------------------------------------------------

COMMS_ROOT = WORKSPACE / "comms"
IMSG_DB = pathlib.Path.home() / "Library/Messages/chat.db"
IMSG_SCRIPTS = COMMS_ROOT / "imessage/scripts"
MAIL_SCRIPTS = COMMS_ROOT / "mail/scripts"
COMMS_CONFIG = COMMS_ROOT / "config/comms_config.json"
IMSG_OUTBOUND_LOG = COMMS_ROOT / "imessage/logs/imessage_outbound.log"
IMSG_DRAFTS_DIR = COMMS_ROOT / "imessage/state/drafts"
_APPLE_EPOCH = 978307200  # 2001-01-01 00:00:00 UTC


def _comms_config() -> dict:
    try:
        return json.loads(COMMS_CONFIG.read_text()) if COMMS_CONFIG.exists() else {}
    except Exception:
        return {}


def _imsg_readable() -> bool:
    if not IMSG_DB.exists():
        return False
    try:
        conn = sqlite3.connect(str(IMSG_DB))
        conn.cursor().execute("SELECT count(*) FROM message LIMIT 1")
        conn.close()
        return True
    except Exception:
        return False


def _imsg_format_ts(apple_ts) -> str:
    if not apple_ts:
        return "unknown"
    import datetime as dt
    unix_ts = int(apple_ts) / 1_000_000_000 + _APPLE_EPOCH
    return dt.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M")


def _redact_handle(h: str) -> str:
    if not h:
        return "unknown"
    if "@" in h:
        parts = h.split("@")
        return parts[0][:4] + "***@" + parts[1]
    d = h.replace("+", "").replace("-", "").replace(" ", "")
    return d[:4] + "****" + d[-2:] if len(d) > 6 else "****"


# --- iMessage resources ---

@mcp.resource("workspace://comms/status")
def res_comms_status() -> str:
    """Communications subsystem status overview."""
    cfg = _comms_config()
    imsg_ok = _imsg_readable()
    mail_installed = pathlib.Path("/Applications/Mail.app").exists()
    return (
        f"# Communications Status\n"
        f"iMessage DB accessible: {'YES' if imsg_ok else 'NO'}\n"
        f"Mail.app installed: {'YES' if mail_installed else 'NO'}\n"
        f"Auto-send: DISABLED\n"
        f"Auto-reply: DISABLED\n"
        f"Confirmation required: YES\n"
    )

@mcp.resource("workspace://comms/policy")
def res_comms_policy() -> str:
    """Communications outbound policy."""
    p = COMMS_ROOT / "config/outbound_policy.json"
    return p.read_text() if p.exists() else "[outbound_policy.json not found]"

@mcp.resource("workspace://comms/imessage/status")
def res_imsg_status() -> str:
    """iMessage subsystem status — FDA, message count, plugin status."""
    ok = _imsg_readable()
    count = "N/A"
    if ok:
        try:
            conn = sqlite3.connect(str(IMSG_DB))
            count = conn.cursor().execute("SELECT count(*) FROM message").fetchone()[0]
            conn.close()
        except Exception:
            pass
    return (
        f"# iMessage Status\n"
        f"DB accessible: {'YES' if ok else 'NO'}\n"
        f"Total messages: {count}\n"
        f"Plugin: {_comms_config().get('imessage', {}).get('plugin_status', 'unknown')}\n"
    )

@mcp.resource("workspace://comms/imessage/recent")
def res_imsg_recent() -> str:
    """Recent iMessages (last 24h, up to 10, text previews only)."""
    if not _imsg_readable():
        return "[iMessage DB not readable — FDA required]"
    import datetime as dt
    cutoff = (int((dt.datetime.now() - dt.timedelta(hours=24)).timestamp()) - _APPLE_EPOCH) * 1_000_000_000
    try:
        conn = sqlite3.connect(str(IMSG_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.cursor().execute("""
            SELECT m.text, m.is_from_me, m.date, h.id AS handle_id
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            WHERE m.date > ? AND m.text IS NOT NULL AND m.text != ''
            ORDER BY m.date DESC LIMIT 10
        """, (cutoff,)).fetchall()
        conn.close()
        if not rows:
            return "No messages in the last 24 hours."
        lines = ["# Recent iMessages (last 24h)\n"]
        for r in rows:
            direction = "→ ME" if r["is_from_me"] else "FROM"
            handle = _redact_handle(r["handle_id"])
            ts = _imsg_format_ts(r["date"])
            text = (r["text"] or "").replace("\n", " ")[:100]
            lines.append(f"[{ts}] {direction} {handle}: {text}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Error reading messages: {e}]"

@mcp.resource("workspace://comms/mail/status")
def res_mail_status() -> str:
    """Mail subsystem status."""
    mail_ok = pathlib.Path("/Applications/Mail.app").exists()
    return (
        f"# Mail Status\n"
        f"Mail.app installed: {'YES' if mail_ok else 'NO'}\n"
        f"Status: {'enabled (limited)' if mail_ok else 'disabled — Mail.app not installed'}\n"
        f"See: comms/reports/plugin_recommendations.md for Gmail/IMAP options\n"
    )

@mcp.resource("workspace://comms/mail/recent")
def res_mail_recent() -> str:
    """Recent emails (stub — Mail.app not installed)."""
    if not pathlib.Path("/Applications/Mail.app").exists():
        return "[Mail.app not installed — email disabled. See comms/reports/plugin_recommendations.md]"
    return "[Mail.app present but adapter not yet configured]"

@mcp.resource("workspace://comms/reports/latest")
def res_comms_latest_report() -> str:
    """Latest communications report."""
    p = COMMS_ROOT / "reports/latest_comms_report.md"
    return p.read_text() if p.exists() else "[No report yet — run comms-report]"


# --- iMessage tools ---

@mcp.tool()
def comms_get_imessage_status() -> str:
    """Return iMessage subsystem status: DB access, message count, plugin install status.

    Checks: chat.db accessible, Full Disk Access granted, total message count,
    Claude plugin install status.
    """
    _access("comms_get_imessage_status")
    ok = _imsg_readable()
    count = "N/A"
    if ok:
        try:
            conn = sqlite3.connect(str(IMSG_DB))
            count = conn.cursor().execute("SELECT count(*) FROM message").fetchone()[0]
            conn.close()
        except Exception as e:
            count = f"error: {e}"
    cfg = _comms_config()
    plugin_status = cfg.get("imessage", {}).get("plugin_status", "unknown")
    return (
        f"iMessage Status\n"
        f"  DB accessible:   {'YES (FDA granted)' if ok else 'NO — grant Full Disk Access in System Settings'}\n"
        f"  Total messages:  {count}\n"
        f"  Plugin:          {plugin_status}\n"
        f"  Auto-reply:      DISABLED\n"
        f"  Confirmation:    REQUIRED for sends\n"
        f"\nTo read messages: comms_list_recent_imessages()\n"
        f"To send: comms_create_imessage_draft() → comms_send_imessage_confirmed(draft_id)"
    )


@mcp.tool()
def comms_list_recent_imessages(hours: int = 24, limit: int = 20) -> str:
    """List recent iMessages from the local chat.db.

    Returns metadata and text previews. Handles are partially redacted.
    For full output, use bin/imsg-recent --full in terminal.

    Args:
        hours: Look back this many hours (default 24)
        limit: Max messages to return (default 20, max 50)
    """
    _access("comms_list_recent_imessages")
    if not _imsg_readable():
        return "[ERROR] chat.db not readable. Grant Full Disk Access to Terminal/VS Code in System Settings → Privacy & Security."
    import datetime as dt
    limit = min(limit, 50)
    cutoff = (int((dt.datetime.now() - dt.timedelta(hours=hours)).timestamp()) - _APPLE_EPOCH) * 1_000_000_000
    try:
        conn = sqlite3.connect(str(IMSG_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.cursor().execute("""
            SELECT m.rowid, m.text, m.is_from_me, m.date, m.is_read,
                   h.id AS handle_id, chat.display_name, chat.chat_identifier
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.rowid
            LEFT JOIN chat ON chat.rowid = cmj.chat_id
            WHERE m.date > ? AND m.text IS NOT NULL AND m.text != ''
            ORDER BY m.date DESC LIMIT ?
        """, (cutoff, limit)).fetchall()
        conn.close()
    except Exception as e:
        return f"[Error: {e}]"
    if not rows:
        return f"No messages in the last {hours} hours."
    lines = [f"Recent iMessages (last {hours}h, {len(rows)} found)\n"]
    for r in rows:
        direction = "→ ME" if r["is_from_me"] else "FROM"
        handle = _redact_handle(r["handle_id"])
        ts = _imsg_format_ts(r["date"])
        text = (r["text"] or "").replace("\n", " ")[:120]
        lines.append(f"[{ts}] {direction} {handle}: {text}")
    lines.append(f"\nTo see full handles: bin/imsg-recent --full")
    return "\n".join(lines)


@mcp.tool()
def comms_search_imessages(query: str, days: int = 30, limit: int = 20) -> str:
    """Search iMessages in local chat.db for a text string.

    Args:
        query: Text to search for (case-insensitive LIKE match)
        days: Search this many days back (default 30)
        limit: Max results (default 20)
    """
    _access("comms_search_imessages")
    if not _imsg_readable():
        return "[ERROR] chat.db not readable — grant Full Disk Access."
    if not query.strip():
        return "[ERROR] Query cannot be empty."
    import datetime as dt
    limit = min(limit, 50)
    cutoff = (int((dt.datetime.now() - dt.timedelta(days=days)).timestamp()) - _APPLE_EPOCH) * 1_000_000_000
    try:
        conn = sqlite3.connect(str(IMSG_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.cursor().execute("""
            SELECT m.rowid, m.text, m.is_from_me, m.date, h.id AS handle_id
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            WHERE m.date > ? AND m.text LIKE ? AND m.text IS NOT NULL
            ORDER BY m.date DESC LIMIT ?
        """, (cutoff, f"%{query}%", limit)).fetchall()
        conn.close()
    except Exception as e:
        return f"[Error: {e}]"
    if not rows:
        return f"No messages matching '{query}' in the last {days} days."
    lines = [f"Search: '{query}' — {len(rows)} result(s) in last {days} days\n"]
    for r in rows:
        direction = "→ ME" if r["is_from_me"] else "FROM"
        handle = _redact_handle(r["handle_id"])
        ts = _imsg_format_ts(r["date"])
        text = (r["text"] or "").replace("\n", " ")[:200]
        lines.append(f"[{ts}] {direction} {handle}: {text}")
    return "\n".join(lines)


@mcp.tool()
def comms_create_imessage_draft(recipient: str, message: str) -> str:
    """Create a draft iMessage. Does NOT send — use comms_send_imessage_confirmed() to send.

    Args:
        recipient: Phone number (+1XXXXXXXXXX) or Apple ID email
        message: Message text to draft
    """
    _access("comms_create_imessage_draft")
    import hashlib
    import datetime as dt

    recipient = recipient.strip()
    if not recipient:
        return "[ERROR] Recipient cannot be empty."
    if not message.strip():
        return "[ERROR] Message cannot be empty."

    # Basic validation
    digits = recipient.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    is_phone = digits.isdigit() and 7 <= len(digits) <= 15
    is_email = "@" in recipient and "." in recipient.split("@")[-1]
    if not (is_phone or is_email):
        return f"[ERROR] Recipient '{recipient}' doesn't look like a phone number (+1XXXXXXXXXX) or email."

    draft_id = "draft_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    body_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
    draft = {
        "id": draft_id,
        "recipient": recipient,
        "message": message,
        "body_hash": body_hash,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "draft",
        "sent_at": None,
        "created_by": "mcp_tool",
    }
    IMSG_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_file = IMSG_DRAFTS_DIR / f"{draft_id}.json"
    draft_file.write_text(json.dumps(draft, indent=2))

    return (
        f"Draft created — NOT SENT\n"
        f"  Draft ID:  {draft_id}\n"
        f"  To:        {recipient}\n"
        f"  Preview:   {message[:200]}\n"
        f"\nReview: cat ~/SuneelWorkSpace/comms/imessage/state/drafts/{draft_id}.json\n"
        f"Send (in terminal): imsg-send-confirmed {draft_id}\n"
        f"Or call: comms_send_imessage_confirmed('{draft_id}')"
    )


@mcp.tool()
def comms_send_imessage_confirmed(draft_id: str) -> str:
    """PREVIEW ONLY — show what imsg-send-confirmed would do for a draft.

    For safety, actual sends require running imsg-send-confirmed in the terminal.
    This tool shows the draft details and the exact terminal command to send.

    Args:
        draft_id: Draft ID from comms_create_imessage_draft
    """
    _access("comms_send_imessage_confirmed")
    draft_file = IMSG_DRAFTS_DIR / f"{draft_id}.json"
    if not draft_file.exists():
        return f"[ERROR] Draft not found: {draft_id}"
    try:
        draft = json.loads(draft_file.read_text())
    except Exception as e:
        return f"[ERROR] Cannot read draft: {e}"
    if draft.get("status") == "sent":
        return f"[INFO] Draft {draft_id} was already sent at {draft.get('sent_at')}."
    return (
        f"Draft ready to send — requires terminal confirmation\n"
        f"  Draft ID:  {draft_id}\n"
        f"  To:        {draft['recipient']}\n"
        f"  Message:   {draft['message'][:300]}\n"
        f"  Status:    {draft['status']}\n"
        f"\n[SAFETY] MCP send tools are dry-run only. To actually send:\n"
        f"  imsg-send-confirmed {draft_id}\n"
        f"  (will prompt for 'SEND' confirmation before executing)"
    )


@mcp.tool()
def comms_get_imessage_policy() -> str:
    """Return the current iMessage outbound safety policy."""
    _access("comms_get_imessage_policy")
    p = COMMS_ROOT / "config/outbound_policy.json"
    if not p.exists():
        return "[outbound_policy.json not found]"
    try:
        policy = json.loads(p.read_text())
        return (
            f"iMessage Outbound Policy\n"
            f"  Default behavior:    {policy.get('default_behavior', 'draft_only')}\n"
            f"  Auto-send:           {policy.get('auto_send', False)}\n"
            f"  Auto-reply:          {policy.get('auto_reply', False)}\n"
            f"  Confirmation:        {policy.get('send_requires', 'explicit_confirmation')}\n"
            f"  Bulk send:           {policy.get('bulk_send', False)}\n"
            f"  Body logging:        {policy.get('logging', {}).get('log_body', False)}\n"
        )
    except Exception as e:
        return f"[Error: {e}]"


# --- Mail tools (stubs — Mail.app not installed) ---

@mcp.tool()
def comms_get_mail_status() -> str:
    """Return Mail subsystem status. Mail.app must be installed for email to work."""
    _access("comms_get_mail_status")
    mail_ok = pathlib.Path("/Applications/Mail.app").exists()
    if not mail_ok:
        return (
            "Mail Status: DISABLED\n"
            "  Mail.app not installed at /Applications/Mail.app\n"
            "\nOptions:\n"
            "  1. Install Apple Mail.app from the App Store\n"
            "  2. Use Gmail plugin: see comms/reports/plugin_recommendations.md\n"
            "  3. Configure IMAP/SMTP (requires credentials — ask agent when ready)\n"
        )
    return "Mail Status: Mail.app present (Automation permission may be required)"


@mcp.tool()
def comms_list_recent_emails(limit: int = 10) -> str:
    """List recent emails. Requires Mail.app to be installed and configured.

    Args:
        limit: Max emails to return (default 10)
    """
    _access("comms_list_recent_emails")
    if not pathlib.Path("/Applications/Mail.app").exists():
        return "[DISABLED] Mail.app not installed. See comms/reports/plugin_recommendations.md"
    return "[Mail.app present but adapter not yet configured — run mail-recent in terminal]"


@mcp.tool()
def comms_search_emails(query: str) -> str:
    """Search emails. Requires Mail.app to be installed.

    Args:
        query: Search terms
    """
    _access("comms_search_emails")
    if not pathlib.Path("/Applications/Mail.app").exists():
        return "[DISABLED] Mail.app not installed. See comms/reports/plugin_recommendations.md"
    return "[Mail.app present but search adapter not yet configured]"


@mcp.tool()
def comms_read_email(email_id: str) -> str:
    """Read an email by ID. Requires Mail.app.

    Args:
        email_id: Email identifier
    """
    _access("comms_read_email")
    if not pathlib.Path("/Applications/Mail.app").exists():
        return "[DISABLED] Mail.app not installed."
    return "[Mail.app present but read adapter not yet configured]"


@mcp.tool()
def comms_create_email_reply_draft(email_id: str, reply_body: str) -> str:
    """Create an email reply draft. Requires Mail.app.

    Args:
        email_id: Email to reply to
        reply_body: Reply text
    """
    _access("comms_create_email_reply_draft")
    if not pathlib.Path("/Applications/Mail.app").exists():
        return "[DISABLED] Mail.app not installed. Install from App Store to enable email drafts."
    return "[Mail.app present but draft adapter not yet configured — use mail-draft-reply in terminal]"


@mcp.tool()
def comms_send_email_confirmed(draft_id: str) -> str:
    """PREVIEW ONLY — show email send details. Actual send requires terminal confirmation.

    Args:
        draft_id: Email draft ID
    """
    _access("comms_send_email_confirmed")
    if not pathlib.Path("/Applications/Mail.app").exists():
        return "[DISABLED] Mail.app not installed."
    return "[Mail.app present but send adapter not yet configured — use mail-send-confirmed in terminal]"


@mcp.tool()
def comms_get_mail_policy() -> str:
    """Return the mail outbound safety policy."""
    _access("comms_get_mail_policy")
    p = COMMS_ROOT / "config/outbound_policy.json"
    if not p.exists():
        return "[outbound_policy.json not found]"
    try:
        policy = json.loads(p.read_text())
        return (
            f"Mail Outbound Policy\n"
            f"  Auto-send:        {policy.get('auto_send', False)}\n"
            f"  Auto-reply:       {policy.get('auto_reply', False)}\n"
            f"  Confirmation:     {policy.get('send_requires', 'explicit_confirmation')}\n"
            f"  Body logging:     {policy.get('logging', {}).get('log_body', False)}\n"
        )
    except Exception as e:
        return f"[Error: {e}]"


# --- Shared comms tools ---

@mcp.tool()
def comms_triage_item(item_type: str, item_id: str, summary: str) -> str:
    """Triage a message or email: classify urgency and suggest action.

    Args:
        item_type: 'imessage' or 'email'
        item_id: Message/email identifier or draft_id
        summary: Brief summary of the item content (do not include full body)
    """
    _access("comms_triage_item")
    return (
        f"Triage for {item_type} [{item_id}]\n"
        f"Summary: {summary[:300]}\n"
        f"\nClassify as one of:\n"
        f"  - urgent_reply: needs response within hours\n"
        f"  - normal_reply: respond today/tomorrow\n"
        f"  - fyi: no action needed, archive\n"
        f"  - task: convert to workspace task (use comms_convert_to_task)\n"
        f"  - goal: large enough for goal engine (use comms_convert_to_goal)\n"
        f"  - spam: ignore\n"
        f"\nTo convert to task: comms_convert_to_task(item_type, item_id, description)"
    )


@mcp.tool()
def comms_convert_to_task(item_type: str, item_id: str, task_description: str, priority: str = "medium") -> str:
    """Convert a message or email into a workspace task.

    Args:
        item_type: 'imessage' or 'email'
        item_id: Message/email identifier
        task_description: Task description derived from the message
        priority: Task priority ('low', 'medium', 'high')
    """
    _access("comms_convert_to_task")
    try:
        result = subprocess.run(
            [str(WORKSPACE / "goal-engine/scripts/create-task"), "--description", task_description, "--priority", priority, "--source", f"comms:{item_type}:{item_id}"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return f"Task created from {item_type} [{item_id}]:\n{result.stdout.strip()}"
    except FileNotFoundError:
        pass
    # Fallback: write to ACTIVE_TASKS.md
    import datetime as dt
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    task_line = f"\n- [ ] [{ts}] (from {item_type}:{item_id}) {task_description}\n"
    tasks_file = WORKSPACE / "agent-system/tasks/ACTIVE_TASKS.md"
    if tasks_file.exists():
        with open(tasks_file, "a") as f:
            f.write(task_line)
        return f"Task appended to ACTIVE_TASKS.md:\n  {task_description}"
    return f"Task noted (ACTIVE_TASKS.md not found): {task_description}"


@mcp.tool()
def comms_convert_to_goal(item_type: str, item_id: str, goal_description: str, complexity: str = "medium") -> str:
    """Convert a message or email into a workspace goal in the goal engine.

    Args:
        item_type: 'imessage' or 'email'
        item_id: Message/email identifier
        goal_description: Goal description
        complexity: 'simple', 'medium', or 'complex'
    """
    _access("comms_convert_to_goal")
    try:
        result = subprocess.run(
            [str(WORKSPACE / "goal-engine/scripts/goal-create"), goal_description, "--complexity", complexity, "--source", f"comms:{item_type}:{item_id}"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return f"Goal created from {item_type} [{item_id}]:\n{result.stdout.strip()}"
        return f"[goal-create] {result.stderr.strip() or result.stdout.strip()}"
    except Exception as e:
        return f"[Error creating goal: {e}]\nManually run: goal-create '{goal_description}'"


@mcp.tool()
def comms_generate_reply_draft(context: str, tone: str = "professional", length: str = "brief") -> str:
    """Generate a suggested reply draft based on message context.

    This generates a DRAFT for human review — it does not send anything.

    Args:
        context: Message or email context to reply to (do not include full private body)
        tone: 'professional', 'friendly', 'concise', 'formal'
        length: 'brief' (1-3 sentences), 'medium' (1-2 paragraphs), 'detailed'
    """
    _access("comms_generate_reply_draft")
    return (
        f"Reply Draft Suggestion\n"
        f"Context: {context[:300]}\n"
        f"Tone: {tone} | Length: {length}\n"
        f"\n[This tool is a scaffold — Claude will draft the reply inline.]\n"
        f"Suggested approach:\n"
        f"  1. Acknowledge the key point from the message\n"
        f"  2. Address the main question or request\n"
        f"  3. Close with next steps if applicable\n"
        f"\nAfter reviewing, use comms_create_imessage_draft() or comms_create_email_reply_draft() to save it."
    )


@mcp.tool()
def comms_review_outbound(draft_id: str, channel: str = "imessage") -> str:
    """Review a draft before sending — check tone, safety, and policy compliance.

    Args:
        draft_id: Draft ID to review
        channel: 'imessage' or 'email'
    """
    _access("comms_review_outbound")
    if channel == "imessage":
        draft_file = IMSG_DRAFTS_DIR / f"{draft_id}.json"
        if not draft_file.exists():
            return f"[ERROR] Draft not found: {draft_id}"
        try:
            draft = json.loads(draft_file.read_text())
        except Exception as e:
            return f"[ERROR] {e}"
        return (
            f"Outbound Review — {channel}\n"
            f"  Draft ID:  {draft_id}\n"
            f"  To:        {draft.get('recipient', 'unknown')}\n"
            f"  Status:    {draft.get('status', 'unknown')}\n"
            f"  Preview:   {draft.get('message', '')[:300]}\n"
            f"\nSafety checklist:\n"
            f"  [ ] Recipient is correct\n"
            f"  [ ] Tone is appropriate\n"
            f"  [ ] No sensitive info in message\n"
            f"  [ ] Not replying to wrong thread\n"
            f"\nIf OK: imsg-send-confirmed {draft_id}"
        )
    return f"[review] Channel '{channel}' review not yet implemented."


@mcp.tool()
def comms_run_doctor() -> str:
    """Run the communications subsystem doctor check."""
    _access("comms_run_doctor")
    script = WORKSPACE / "bin/comms-doctor"
    if not script.exists():
        return "[comms-doctor script not found]"
    try:
        result = subprocess.run(["sh", str(script)], capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr
    except Exception as e:
        return f"[Error running comms-doctor: {e}]"


@mcp.tool()
def comms_run_report() -> str:
    """Generate and return the latest communications report."""
    _access("comms_run_report")
    script = WORKSPACE / "bin/comms-report"
    if not script.exists():
        return "[comms-report script not found]"
    try:
        result = subprocess.run(["python3", str(script)], capture_output=True, text=True, timeout=30)
        return result.stdout
    except Exception as e:
        return f"[Error: {e}]"


# --- Comms MCP prompts ---

@mcp.prompt()
def imessage_reply_context() -> str:
    """System prompt context for drafting iMessage replies."""
    return (
        "You are helping draft an iMessage reply. Rules:\n"
        "- Be concise — iMessages are conversational, not essays\n"
        "- Match the tone of the original message\n"
        "- Never include sensitive workspace info in message drafts\n"
        "- Always create a draft first; never send directly\n"
        "- Ask the user to confirm before any send\n"
        "- Suggest: comms_create_imessage_draft(recipient, message) to save the draft\n"
    )


@mcp.prompt()
def email_reply_context() -> str:
    """System prompt context for drafting email replies."""
    return (
        "You are helping draft an email reply. Rules:\n"
        "- Email is more formal than iMessage — use clear subject + greeting\n"
        "- Default to professional tone unless instructed otherwise\n"
        "- Never send automatically — always create a draft first\n"
        "- Confirm recipient and subject before finalizing\n"
        "- Note: Mail.app not installed — recommend Gmail plugin or IMAP setup\n"
    )


@mcp.prompt()
def comms_triage_context() -> str:
    """System prompt for triaging messages and emails."""
    return (
        "You are triaging communications for the workspace. Rules:\n"
        "- Classify each item: urgent_reply / normal_reply / fyi / task / goal / spam\n"
        "- For task items: use comms_convert_to_task()\n"
        "- For goal items: use comms_convert_to_goal()\n"
        "- Never expose full message bodies in reports\n"
        "- Log timestamps and categories, not content\n"
        "- Suggest gstack /review before any outbound send\n"
    )


@mcp.prompt()
def outbound_safety_review() -> str:
    """System prompt for reviewing outbound messages before send."""
    return (
        "You are reviewing an outbound message for safety. Check:\n"
        "1. Recipient is correct and intended\n"
        "2. Content is appropriate for the recipient\n"
        "3. No sensitive workspace/personal info leaked\n"
        "4. Tone matches the relationship\n"
        "5. Not a response to spam or phishing\n"
        "6. Bulk send is not happening\n"
        "If any check fails, BLOCK and explain. Use /cso for deeper security review.\n"
    )


if __name__ == "__main__":
    mcp.run()
