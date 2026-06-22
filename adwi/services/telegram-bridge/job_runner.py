"""
job_runner.py — Background job runner for Telegram-triggered tasks.

Stdlib-only. Thread-safe. State persisted to adwi/logs/telegram-jobs/jobs.json.
Each job runs as a subprocess; output is captured to a per-job log file.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

WORKSPACE = Path.home() / "SuneelWorkSpace"
JOBS_DIR  = WORKSPACE / "adwi" / "logs" / "telegram-jobs"
JOBS_FILE = JOBS_DIR / "jobs.json"

JOB_TIMEOUT  = 300   # seconds — 5 min max per job
MAX_LOG_TAIL = 50    # lines returned by tail_log()
MAX_JOBS     = 50    # prune oldest when state file exceeds this

_lock = threading.Lock()


class JobRunner:
    def __init__(self) -> None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if JOBS_FILE.exists():
                data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._jobs = data
        except Exception as exc:
            log.warning("Job state load failed: %s", exc)
            self._jobs = {}

    def _save(self) -> None:
        try:
            # Prune oldest entries if over limit
            if len(self._jobs) > MAX_JOBS:
                sorted_ids = sorted(
                    self._jobs,
                    key=lambda jid: self._jobs[jid].get("start_time") or jid,
                )
                for jid in sorted_ids[: len(self._jobs) - MAX_JOBS]:
                    del self._jobs[jid]
            JOBS_FILE.write_text(
                json.dumps(self._jobs, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("Job state save failed: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(self, name: str, argv: list[str]) -> str:
        """Spawn a background subprocess. Returns the job ID immediately."""
        job_id   = f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        log_path = JOBS_DIR / f"{job_id}.log"

        job: dict = {
            "id":          job_id,
            "type":        name,
            "argv":        argv,
            "status":      "queued",
            "start_time":  None,
            "end_time":    None,
            "returncode":  None,
            "pid":         None,
            "log_path":    str(log_path),
        }

        with _lock:
            self._jobs[job_id] = job
            self._save()

        t = threading.Thread(target=self._run, args=(job_id, argv, log_path), daemon=True)
        t.start()
        return job_id

    def status(self, job_id: str) -> Optional[dict]:
        """Return a copy of the job record, or None if not found."""
        with _lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def list_recent(self, n: int = 10) -> list[dict]:
        """Return the N most recent jobs, newest first."""
        with _lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda j: j.get("start_time") or j.get("id", ""),
                reverse=True,
            )
            return [dict(j) for j in jobs[:n]]

    def cancel(self, job_id: str) -> bool:
        """Send SIGTERM to a running job. Returns True if the cancel was attempted."""
        with _lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.get("status") not in ("queued", "running"):
                return False
            pid = job.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            job["status"]   = "cancelled"
            job["end_time"] = datetime.now().isoformat()
            self._save()
        return True

    def tail_log(self, job_id: str, n: int = MAX_LOG_TAIL) -> str:
        """Return the last N lines of a job's log file."""
        with _lock:
            job = self._jobs.get(job_id)
        if not job:
            return "(job not found)"
        log_path = Path(job.get("log_path", ""))
        if not log_path.exists():
            return "(log not yet available)"
        try:
            lines = log_path.read_text(errors="replace").splitlines()
        except Exception as exc:
            return f"(log read error: {exc})"
        if not lines:
            return "(log is empty)"
        return "\n".join(lines[-n:])

    # ── Internal worker ───────────────────────────────────────────────────────

    def _run(self, job_id: str, argv: list[str], log_path: Path) -> None:
        with _lock:
            self._jobs[job_id]["status"]     = "running"
            self._jobs[job_id]["start_time"] = datetime.now().isoformat()
            self._save()

        proc: Optional[subprocess.Popen] = None
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
                proc = subprocess.Popen(
                    argv,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env={
                        **os.environ,
                        "PATH": (
                            f"{WORKSPACE}/adwi/bin:/opt/homebrew/bin"
                            ":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
                        ),
                    },
                )

            with _lock:
                self._jobs[job_id]["pid"] = proc.pid
                self._save()

            try:
                rc = proc.wait(timeout=JOB_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                rc = -1

        except Exception as exc:
            log.error("Job %s failed to launch: %s", job_id, exc)
            rc = -2
            try:
                log_path.write_text(f"[launch error] {exc}\n", encoding="utf-8")
            except Exception:
                pass

        with _lock:
            job = self._jobs.get(job_id, {})
            if job.get("status") not in ("cancelled",):
                job["status"]     = "succeeded" if rc == 0 else "failed"
                job["returncode"] = rc
                job["end_time"]   = datetime.now().isoformat()
            self._save()
