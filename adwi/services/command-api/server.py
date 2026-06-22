from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import os
from datetime import datetime
from pathlib import Path

HOME = os.path.expanduser("~")
BIN = os.path.join(HOME, "SuneelWorkSpace", "adwi", "bin")

def _load_env():
    """Load config/.env into os.environ (setdefault — does not override shell env)."""
    env_path = Path(HOME) / "SuneelWorkSpace" / "adwi" / "config" / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ.setdefault(k, v)

_load_env()
SECRET = os.environ.get("ADWI_LOCAL_SECRET", "")

VENV_PY = os.path.join(HOME, "SuneelWorkSpace", "adwi", ".venv", "bin", "python3")
ADWI_CLI = os.path.join(HOME, "SuneelWorkSpace", "adwi", "adwi_cli.py")

E2E_LOOP_PY       = os.path.join(HOME, "SuneelWorkSpace", "adwi", "e2e_auto_loop.py")
E2E_STATUS_READER = os.path.join(HOME, "SuneelWorkSpace", "adwi", "bin", "adwi-e2e-status-reader")
E2E_LOOP_DIR      = Path(HOME) / "SuneelWorkSpace" / "adwi" / "notes" / "e2e-auto-loop"

ALLOWED_COMMANDS = {
    "/status-ai":              [os.path.join(BIN, "status-ai")],
    "/daily-ai-status-report": [os.path.join(BIN, "daily-ai-status-report")],
    "/index-ai-notes":         [os.path.join(BIN, "index-ai-notes")],
    "/auto-ai-maintenance":    [os.path.join(BIN, "auto-ai-maintenance")],
    "/adwi-self-heal":         [os.path.join(BIN, "adwi-self-heal")],
    "/rag-index":              [os.path.join(BIN, "rag-index")],
    "/git-status-workspace":   [os.path.join(BIN, "git-status-workspace")],
    "/benchmark-adwi":         [os.path.join(BIN, "benchmark-adwi")],
    # ── Adwi pillar commands (called by n8n + HA dashboard) ──────────────────
    "/adwi-backup":            [VENV_PY, ADWI_CLI, "/backup-now"],
    "/adwi-nightly":           [VENV_PY, ADWI_CLI, "/nightly-run"],
    "/adwi-brief":             [VENV_PY, ADWI_CLI, "/what-next"],
    "/adwi-status":            [VENV_PY, ADWI_CLI, "/status"],
    "/adwi-doctor":            [VENV_PY, ADWI_CLI, "/doctor"],
    "/adwi-models":            [VENV_PY, ADWI_CLI, "/models"],
    "/adwi-watcher-status":    [os.path.join(BIN, "status-openwebui-knowledge-watcher")],
    # /adwi-daily-brief-n8n — emits a single JSON line; safe for n8n HTTP Request node.
    # n8n HTTP Request: GET http://127.0.0.1:5055/adwi-daily-brief-n8n
    # Header: X-Adwi-Secret: {{$env.ADWI_LOCAL_SECRET}}
    # Parse response: response.body.stdout (trim trailing whitespace, parse as JSON)
    "/adwi-daily-brief-n8n":   [VENV_PY, ADWI_CLI, "/daily-brief", "--n8n"],
    # ── Observability / quick-status routes ──────────────────────────────────
    "/adwi-config-check":         [os.path.join(BIN, "adwi-config-check")],
    "/adwi-eval-status":          [os.path.join(BIN, "adwi-eval-status")],
    "/adwi-disk-summary":         [os.path.join(BIN, "adwi-disk-summary")],
    "/adwi-ports":                [os.path.join(BIN, "adwi-ports")],
    "/adwi-nightly-status":       [os.path.join(BIN, "adwi-nightly-status")],
    "/adwi-version":              [os.path.join(BIN, "adwi-version")],
    "/adwi-uptime":               ["/usr/bin/uptime"],
    # ── E2E Auto Loop (read-only routes use existing subprocess.run pattern) ────
    "/adwi-e2e-auto-loop-status": [VENV_PY, E2E_STATUS_READER, "--status"],
    "/adwi-e2e-auto-loop-report": [VENV_PY, E2E_STATUS_READER, "--report"],
    "/adwi-e2e-auto-loop-cancel": [VENV_PY, E2E_STATUS_READER, "--cancel"],
    # Note: /adwi-e2e-auto-loop-start is handled separately via Popen (see _handle_e2e_start)
    # ── Extended Telegram routes (Wave 4) ────────────────────────────────────
    "/adwi-services":          [os.path.join(BIN, "adwi-services")],
    "/adwi-obsidian-status":   [VENV_PY, ADWI_CLI, "/obsidian-status"],
    "/adwi-git-diff":          [os.path.join(BIN, "adwi-git-diff")],
    "/adwi-git-log":           [os.path.join(BIN, "adwi-git-log")],
}

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        if not SECRET:
            return True
        return self.headers.get("X-Adwi-Secret") == SECRET

    def do_GET(self):
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized — X-Adwi-Secret header required"})
            return

        if self.path == "/":
            self._send_json(200, {
                "name": "Suneel Safe Local Command API",
                "time": datetime.now().isoformat(),
                "allowed_routes": sorted(ALLOWED_COMMANDS.keys()),
                "safety": "Only explicitly allowlisted commands can run."
            })
            return

        # E2E start uses Popen (non-blocking) — handle before ALLOWED_COMMANDS lookup
        if self.path == "/adwi-e2e-auto-loop-start":
            self._handle_e2e_start()
            return

        if self.path not in ALLOWED_COMMANDS:
            self._send_json(404, {
                "error": "Route not allowed",
                "allowed_routes": sorted(ALLOWED_COMMANDS.keys()) + ["/adwi-e2e-auto-loop-start"]
            })
            return

        cmd = ALLOWED_COMMANDS[self.path]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=900,
                env={
                    **os.environ,
                    "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                    "SUNEEL_COMMAND_API_CONTEXT": "1"
                }
            )
            self._send_json(200, {
                "route": self.path,
                "command": cmd,
                "returncode": result.returncode,
                "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-4000:]
            })
        except Exception as e:
            self._send_json(500, {
                "route": self.path,
                "error": str(e)
            })

    def _handle_e2e_start(self) -> None:
        """Launch e2e_auto_loop.py as a detached background process. Returns in <1s."""
        pid_file = E2E_LOOP_DIR / "running.pid"
        if pid_file.exists():
            try:
                existing_pid = int(pid_file.read_text().strip())
                os.kill(existing_pid, 0)
                self._send_json(409, {
                    "error": "E2E loop already running",
                    "pid": existing_pid,
                    "status_route": "/adwi-e2e-auto-loop-status",
                })
                return
            except (ValueError, ProcessLookupError):
                pass   # stale lock — proceed
            except PermissionError:
                self._send_json(409, {
                    "error": "E2E loop already running (PermissionError checking PID)",
                })
                return

        job_id  = f"e2e-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        job_dir = E2E_LOOP_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "loop.log"

        try:
            proc = subprocess.Popen(
                [VENV_PY, E2E_LOOP_PY, "--job-id", job_id],
                start_new_session=True,
                stdout=open(str(log_path), "w"),
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "PATH": f"{BIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                    "SUNEEL_COMMAND_API_CONTEXT": "1",
                },
            )
            self._send_json(200, {
                "job_id":       job_id,
                "status":       "started",
                "pid":          proc.pid,
                "log":          str(log_path),
                "status_route": "/adwi-e2e-auto-loop-status",
                "report_route": "/adwi-e2e-auto-loop-report",
            })
        except Exception as exc:
            self._send_json(500, {"error": f"Failed to start E2E loop: {exc}"})

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 5055
    if not SECRET:
        print("[WARNING] ADWI_LOCAL_SECRET is not set — API is unauthenticated. Set it in config/.env to enforce auth.")
    else:
        print(f"[INFO] Auth enabled — X-Adwi-Secret header required for all routes.")
    print(f"Suneel Safe Local Command API running at http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
