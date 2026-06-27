#!/usr/bin/env python3
"""
README Auto-Commit System — detects README/state changes after nightly pipeline
and commits + optionally pushes via git-safe-push.

Usage:
  python3 auto_commit.py            # commit only (respects auto_push in policy)
  python3 auto_commit.py --dry-run  # show what would be committed without doing it
  python3 auto_commit.py --push     # force push regardless of policy setting
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", Path(__file__).resolve().parents[3]))
POLICY_FILE = WORKSPACE / "spine/readme_policy.json"
HEALTH_CACHE = WORKSPACE / "spine/readme_health_cache.json"
LOG_FILE = WORKSPACE / "blood/logs/auto_commit.log"
GIT_SAFE_PUSH = WORKSPACE / "hands/bin/git-safe-push"

# Files/patterns that should NEVER be auto-committed
EXCLUDE_PATTERNS = {
    "blood/logs/",
    ".tmp.",
    "__pycache__",
    ".pyc",
    ".venv/",
    ".git/",
    "readme-nightly.out.log",
    "readme-nightly.err.log",
    "readme_repair_report.json",  # runtime-only, gitignored
}

# Files explicitly allowed even if they look like state/cache
ALLOW_PATTERNS = {
    "README.md",
    "spine/readme_dependency_map.json",
    "spine/readme_priority_queue.json",
    "spine/readme_metrics_history.json",
    "spine/readme_self_reflection.json",
    "spine/readme_reconcile_report.json",
    "spine/readme_health_cache.json",
    "brain/system/readme_knowledge_index.json",
}


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [auto-commit] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _run(cmd: list[str], cwd: Path = WORKSPACE) -> tuple[int, str, str]:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _load_policy() -> dict:
    try:
        return json.loads(POLICY_FILE.read_text())
    except Exception:
        return {}


def _get_health_stats() -> tuple[float, int]:
    """Return (avg_health, critical_count) from cache."""
    try:
        cache = json.loads(HEALTH_CACHE.read_text())
        entries = [v for v in cache.values() if isinstance(v, dict) and "health_score" in v]
        if not entries:
            return 0.0, 0
        scores = [e["health_score"] for e in entries]
        avg = round(sum(scores) / len(scores), 1)
        critical = sum(1 for s in scores if s < 60)
        return avg, critical
    except Exception:
        return 0.0, 0


def _is_excluded(path: str) -> bool:
    for pattern in EXCLUDE_PATTERNS:
        if pattern in path:
            return True
    return False


def _is_explicitly_allowed(path: str) -> bool:
    for pattern in ALLOW_PATTERNS:
        if path.endswith(pattern) or pattern in path:
            return True
    return False


def get_stageable_changes() -> list[str]:
    """Return list of changed/untracked paths safe to auto-commit."""
    _, out, _ = _run(["git", "status", "--porcelain"])
    if not out:
        return []

    stageable = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        status = line[:2].strip()
        path = line[3:].strip()

        # Skip deletions (? marks, renames handled separately)
        if status in ("D", "DD", "AD"):
            continue

        # Excluded patterns take priority
        if _is_excluded(path) and not _is_explicitly_allowed(path):
            continue

        stageable.append(path)

    return stageable


def build_commit_message(staged_paths: list[str]) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    avg_health, critical_count = _get_health_stats()

    readme_count = sum(1 for p in staged_paths if p.endswith("README.md"))
    state_files = [p for p in staged_paths if not p.endswith("README.md")]

    lines = [
        f"chore(readme): auto-sync — {timestamp}",
        "",
        f"- Updated READMEs: {readme_count}",
        f"- Avg Health: {avg_health}/100",
        f"- Critical Issues: {critical_count}",
        "",
        "Changes:",
    ]

    if readme_count:
        lines.append(f"  - {readme_count} README update(s) — Phase 3 sections injected")
    if any("dependency_map" in p for p in state_files):
        lines.append("  - Dependency map rebuilt")
    if any("priority_queue" in p for p in state_files):
        lines.append("  - Priority queue refreshed")
    if any("metrics_history" in p for p in state_files):
        lines.append("  - Trend snapshot recorded")
    if any("knowledge_index" in p for p in state_files):
        lines.append("  - Knowledge index updated")
    if any("reconcile_report" in p or "self_reflection" in p for p in state_files):
        lines.append("  - State reconcile + self-reflection outputs updated")

    lines.append("")
    lines.append("Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>")
    return "\n".join(lines)


def auto_commit(dry_run: bool = False, force_push: bool = False) -> int:
    policy = _load_policy()
    auto_push = force_push or policy.get("auto_push", False)

    stageable = get_stageable_changes()
    if not stageable:
        _log("Nothing to commit — working tree clean.")
        return 0

    _log(f"Found {len(stageable)} file(s) to stage.")
    for p in stageable[:10]:
        _log(f"  + {p}")
    if len(stageable) > 10:
        _log(f"  ... and {len(stageable) - 10} more")

    if dry_run:
        _log("DRY RUN — no changes made.")
        return 0

    # Stage files
    for path in stageable:
        rc, _, err = _run(["git", "add", path])
        if rc != 0:
            _log(f"  ⚠️  Could not stage {path}: {err}")

    # Verify anything is actually staged
    rc, staged_out, _ = _run(["git", "diff", "--cached", "--quiet"])
    if rc == 0:
        _log("Nothing staged after filtering — skipping commit.")
        return 0

    # Build and execute commit
    message = build_commit_message(stageable)
    rc, out, err = _run(["git", "commit", "-m", message])
    if rc != 0:
        _log(f"❌ Commit failed: {err}")
        return 1

    _log(f"✅ Committed: {out.splitlines()[0] if out else 'ok'}")

    # Auto push
    if auto_push:
        _log("Auto-push enabled — running git-safe-push...")
        if GIT_SAFE_PUSH.exists():
            rc, out, err = _run([str(GIT_SAFE_PUSH)])
            if rc == 0:
                _log("✅ Auto-push succeeded.")
            else:
                _log(f"❌ Auto-push failed (commit preserved): {err or out}")
                return 1
        else:
            _log(f"⚠️  git-safe-push not found at {GIT_SAFE_PUSH} — push skipped.")
    else:
        _log("Auto-push disabled (set auto_push=true in spine/readme_policy.json to enable).")

    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    force_push = "--push" in sys.argv
    sys.exit(auto_commit(dry_run=dry_run, force_push=force_push))
