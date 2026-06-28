#!/usr/bin/env python3
"""SuneelWorkSpace Control Center — FastAPI server with WebSocket execution streaming."""

import asyncio
import json
import logging
import os
import sys
import uuid
import hashlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Importable widgets
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from widgets.goal_status import get_active_goals
from widgets.agent_activity import get_agent_activity
from widgets.memory_health import get_memory_health
from widgets.mcp_status import get_mcp_status
from widgets.anticipation import get_suggestions
from widgets.autolab_status import get_autolab_status
from widgets.readme_health import get_readme_health, get_readme_priority, get_readme_trends

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(WORKSPACE, "blood", "logs")
HISTORY_FILE = os.path.join(LOG_DIR, "execution_history.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_DIR, "dashboard.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = FastAPI(title="SuneelWorkSpace Control Center")
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")),
    name="static",
)

# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self.active: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.active[client_id] = ws
        logging.info(f"WS connected: {client_id}")

    def disconnect(self, client_id: str) -> None:
        self.active.pop(client_id, None)
        logging.info(f"WS disconnected: {client_id}")

    async def send(self, client_id: str, msg: dict) -> None:
        ws = self.active.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception as e:
                logging.warning(f"WS send error [{client_id}]: {e}")
                self.disconnect(client_id)

    async def broadcast(self, msg: dict) -> None:
        for cid in list(self.active):
            await self.send(cid, msg)

    async def run_quick_command(self, argv: list[str], action: str) -> None:
        """Run a whitelisted command (no shell) and stream output to all connected clients."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=WORKSPACE,
            )
            if proc.stdout:
                async for line in proc.stdout:
                    text = line.decode(errors="replace").rstrip()
                    if text:
                        await self.broadcast({
                            "type": "log", "level": "info", "icon": "▶",
                            "content": text,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        })
            await proc.wait()
            await self.broadcast({
                "type": "quick_action_complete",
                "action": action,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            await self.broadcast({
                "type": "error",
                "message": f"Quick action [{action}] failed: {e}",
                "ts": datetime.now(timezone.utc).isoformat(),
            })


manager = ConnectionManager()

# Pending confirm responses: client_id → asyncio.Future
_confirm_futures: dict[str, asyncio.Future] = {}


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

_ALLOWED_ORIGINS = {
    "http://localhost:7777",
    "http://127.0.0.1:7777",
}

# Server-side allowlist: action key → argv (no shell interpolation)
_QUICK_ACTIONS: dict[str, list[str]] = {
    "night-shift":     ["dag-run", "hands/automation/dag/pipelines/night_shift.yaml"],
    "gap-scan":        ["python3", "lab/evolution/gap_finder.py"],
    "challenge":       ["python3", "lab/evolution/challenger.py"],
    "screenshot":      ["screenshot-take"],
    "model-health":    ["model-health"],
    "evolution-start": ["python3", "lab/evolution/engine.py", "cycle"],
    "morning-brief":   ["morning-brief"],
    "workspace-ci":    ["workspace-ci"],
}


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(ws: WebSocket, client_id: str) -> None:
    origin = ws.headers.get("origin", "")
    if origin not in _ALLOWED_ORIGINS:
        await ws.close(code=1008)
        logging.warning(f"WS rejected: bad/missing origin {origin!r}")
        return
    await manager.connect(client_id, ws)
    # Send welcome
    await manager.send(client_id, {
        "type": "system",
        "message": "Control Center connected",
        "ts": datetime.now().isoformat(),
    })
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "execute":
                prompt = msg.get("prompt", "").strip()
                mode = msg.get("mode", "full")  # full | brainstorm
                if prompt:
                    asyncio.create_task(_run_pipeline(client_id, prompt, mode))

            elif msg_type == "confirm_response":
                fut = _confirm_futures.get(client_id)
                if fut and not fut.done():
                    fut.set_result(msg.get("approved", False))

            elif msg_type == "quick_action":
                action = msg.get("action", "")
                argv = _QUICK_ACTIONS.get(action)
                if argv:
                    asyncio.create_task(manager.run_quick_command(argv, action))
                else:
                    logging.warning(f"WS quick_action: unknown/missing action {action!r}")

            elif msg_type == "ping":
                await manager.send(client_id, {"type": "pong", "ts": datetime.now().isoformat()})

    except WebSocketDisconnect:
        manager.disconnect(client_id)


# ── Pipeline runner ─────────────────────────────────────────────────────────

async def _run_pipeline(client_id: str, prompt: str, mode: str) -> None:
    """Run the 6-stage pipeline with live WebSocket streaming."""
    sys.path.insert(0, WORKSPACE)
    try:
        from eyes.dashboard.pipeline.pipeline import Pipeline
        pipeline = Pipeline(
            client_id=client_id,
            prompt=prompt,
            mode=mode,
            send_fn=lambda msg: manager.send(client_id, msg),
            confirm_fn=lambda plan: _request_confirm(client_id, plan),
        )
        result = await pipeline.run()
        _save_history(prompt, result)
    except Exception as e:
        logging.exception(f"Pipeline error for {client_id}")
        await manager.send(client_id, {
            "type": "error",
            "message": f"Pipeline error: {e}",
            "ts": datetime.now().isoformat(),
        })


async def _request_confirm(client_id: str, plan: dict) -> bool:
    """Send confirm_request, wait for user response via WebSocket."""
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _confirm_futures[client_id] = fut
    await manager.send(client_id, {
        "type": "confirm_request",
        "plan": plan,
        "ts": datetime.now().isoformat(),
    })
    try:
        approved = await asyncio.wait_for(fut, timeout=300)
    except asyncio.TimeoutError:
        approved = False
    _confirm_futures.pop(client_id, None)
    return approved


# ── History ──────────────────────────────────────────────────────────────────

def _save_history(prompt: str, result: dict) -> None:
    record = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "outcome": result.get("outcome", "unknown"),
        "stages_completed": result.get("stages_completed", []),
        "duration_ms": result.get("duration_ms", 0),
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def _load_history(limit: int = 50) -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    lines = open(HISTORY_FILE).readlines()
    records = []
    for line in reversed(lines[-limit:]):
        try:
            records.append(json.loads(line.strip()))
        except Exception:
            pass
    return records


# ── REST APIs (kept from original + new) ─────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request) -> HTMLResponse:
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(index_path):
        return open(index_path, encoding="utf-8").read()
    return "<h1>Dashboard UI Not Found</h1>"


@app.get("/api/goals")
async def api_goals() -> Any:
    return get_active_goals()


@app.get("/api/agent")
async def api_agent() -> Any:
    return get_agent_activity()


@app.get("/api/memory")
async def api_memory() -> Any:
    return get_memory_health()


@app.get("/api/mcp")
async def api_mcp() -> Any:
    return get_mcp_status()


@app.get("/api/anticipation")
async def api_anticipation() -> Any:
    return get_suggestions()[:5]


@app.get("/api/autolab")
async def api_autolab() -> Any:
    return get_autolab_status()


@app.get("/api/readme-health")
async def api_readme_health() -> Any:
    return get_readme_health()


@app.get("/api/readme-priority")
async def api_readme_priority() -> Any:
    return get_readme_priority()


@app.get("/api/readme-trends")
async def api_readme_trends() -> Any:
    return get_readme_trends()


@app.get("/api/readme-reconcile")
async def api_readme_reconcile() -> Any:
    reconcile_path = Path(os.path.join(WORKSPACE, "spine/readme_reconcile_report.json"))
    if not reconcile_path.exists():
        return {"error": "no reconcile report — run: readme-reconcile"}
    try:
        return json.loads(reconcile_path.read_text())
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/readme-reflect")
async def api_readme_reflect() -> Any:
    reflect_path = Path(os.path.join(WORKSPACE, "spine/readme_self_reflection.json"))
    if not reflect_path.exists():
        return {"error": "no reflection data — run: readme-reflect"}
    try:
        data = json.loads(reflect_path.read_text())
        return {
            "latest_accuracy": data.get("latest_accuracy"),
            "latest_missed_count": data.get("latest_missed_count"),
            "accuracy_trend": data.get("accuracy_trend"),
            "last_run": data.get("last_run"),
            "recent_sessions": data.get("sessions", [])[-5:],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/health")
async def api_health() -> Any:
    health = get_memory_health()
    live_score = 100 - (health.get("total_errors", 0) * 30) - (health.get("total_warnings", 0) * 10)
    # Use stored score if a repair ran and improved things
    stored_score = live_score
    try:
        wh_path = Path(os.path.join(WORKSPACE, "spine/state/WORKSPACE_HEALTH.json"))
        if wh_path.exists():
            stored_score = int(json.loads(wh_path.read_text()).get("health_score", live_score))
    except Exception:
        pass
    score = max(live_score, stored_score)
    return {"score": max(0, min(100, score)), "status": health.get("status", "healthy")}


@app.get("/api/telemetry")
async def api_telemetry() -> Any:
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "blood", "telemetry"))
        from telemetry_query import summary
        return summary(days=7)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/history")
async def api_history(limit: int = 50) -> Any:
    return {"history": _load_history(limit)}


@app.get("/api/suggestions")
async def api_suggestions() -> Any:
    sugs = get_suggestions()[:5]
    return [{"label": s.get("description", ""), "priority": s.get("priority", "medium")} for s in sugs]


@app.get("/api/status")
async def api_status() -> Any:
    """Aggregate status for header pills."""
    return {
        "mcp": get_mcp_status().get("server_status", "offline"),
        "ws_clients": len(manager.active),
        "ts": datetime.now().isoformat(),
    }


# ── Upgrade 7: Model Status ───────────────────────────────────────────────────

@app.get("/api/models/status")
async def get_model_status() -> Any:
    try:
        sys.path.insert(0, WORKSPACE)
        from heart.model_router.quota_tracker import get_status
        return get_status()
    except Exception as e:
        return {"models": [], "error": str(e)[:100]}

@app.get("/widgets/models")
async def widget_models() -> HTMLResponse:
    sys.path.insert(0, os.path.join(WORKSPACE, "dashboard"))
    from eyes.dashboard.widgets.model_status import render_html
    return HTMLResponse(render_html())


# ── Upgrade 7: Evolution Status ───────────────────────────────────────────────

@app.get("/api/lab/evolution/status")
async def get_evolution_status() -> Any:
    log_path = os.path.join(WORKSPACE, "lab/evolution/evolution_log.jsonl")
    if not os.path.exists(log_path):
        return {"status": "not_started", "recent_events": [], "total_events": 0}
    events: list[dict] = []
    try:
        with open(log_path) as f:
            for line in f.readlines()[-20:]:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return {"status": "running" if events else "idle", "recent_events": events[-5:], "total_events": len(events)}

@app.get("/api/lab/evolution/gaps")
async def get_evolution_gaps() -> Any:
    gap_path = os.path.join(WORKSPACE, "brain/system/gap_analysis_latest.json")
    if not os.path.exists(gap_path):
        return {"gaps": [], "scanned_at": None}
    try:
        return json.load(open(gap_path))
    except Exception:
        return {"gaps": [], "error": "parse error"}

@app.get("/widgets/evolution")
async def widget_evolution() -> HTMLResponse:
    log_path = os.path.join(WORKSPACE, "lab/evolution/evolution_log.jsonl")
    events_raw: list[dict] = []
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                for line in f.readlines()[-5:]:
                    try:
                        events_raw.append(json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass
    rows = ""
    for e in reversed(events_raw):
        rows += f'<div style="font-size:10px;color:var(--text-dim);padding:2px 0">{e.get("ts","")[:16]} — {e.get("type","?")}</div>'
    body = rows if rows else '<div style="color:var(--text-dim);font-size:11px">Not started — run evolution-start</div>'
    return HTMLResponse(f'<div>{body}</div>')


# ── Upgrade 7: Visual Monitor Status ─────────────────────────────────────────

def _count_queue(path: str, status_filter: str) -> int:
    if not os.path.exists(path):
        return 0
    try:
        return len([i for i in json.load(open(path)) if i.get("status") == status_filter])
    except Exception:
        return 0

@app.get("/api/eyes/visual/status")
async def get_visual_status() -> Any:
    try:
        sys.path.insert(0, WORKSPACE)
        from eyes.visual.screenshot_manager import list_screenshots, get_latest_screenshot
        latest = get_latest_screenshot()
        recent = list_screenshots(5)
    except Exception:
        latest = None
        recent = []
    return {
        "latest_screenshot": latest,
        "recent_screenshots": recent,
        "repair_queue":   _count_queue(os.path.join(WORKSPACE, "eyes/visual/visual_repair_queue.json"),   "pending"),
        "approval_queue": _count_queue(os.path.join(WORKSPACE, "eyes/visual/visual_approval_queue.json"), "awaiting_approval"),
    }

@app.get("/widgets/visual")
async def widget_visual() -> HTMLResponse:
    try:
        sys.path.insert(0, WORKSPACE)
        from eyes.visual.screenshot_manager import get_latest_screenshot
        latest = get_latest_screenshot()
    except Exception:
        latest = None
    if not latest:
        return HTMLResponse('<div style="color:var(--text-dim);font-size:11px">No screenshots yet — run screenshot-take</div>')
    return HTMLResponse(f'''<div style="font-size:11px;color:var(--text-secondary)">
  <div>Last: {latest.get("taken_at","")[:16]}</div>
  <div style="color:var(--text-dim);font-family:var(--font-mono)">{latest.get("filename","")}</div>
</div>''')


# ── Upgrade 7: Approval Queue Widget + Actions ────────────────────────────────

@app.get("/widgets/approval")
async def widget_approval() -> HTMLResponse:
    sys.path.insert(0, os.path.join(WORKSPACE, "dashboard"))
    from eyes.dashboard.widgets.approval_queue import render_html
    return HTMLResponse(render_html())

@app.post("/api/approvals/approve")
async def approve_item(request: Request) -> Any:
    body = await request.json()
    _process_approval(body.get("queued_at", ""), approved=True)
    return {"status": "approved"}

@app.post("/api/approvals/reject")
async def reject_item_route(request: Request) -> Any:
    body = await request.json()
    _process_approval(body.get("queued_at", ""), approved=False)
    return {"status": "rejected"}

def _process_approval(queued_at: str, approved: bool) -> None:
    queue_path = os.path.join(WORKSPACE, "eyes/visual/visual_approval_queue.json")
    if not os.path.exists(queue_path) or not queued_at:
        return
    try:
        queue = json.load(open(queue_path))
        for item in queue:
            if item.get("queued_at") == queued_at:
                item["status"] = "approved" if approved else "rejected"
                item["processed_at"] = datetime.now(timezone.utc).isoformat()
                if approved:
                    sys.path.insert(0, WORKSPACE)
                    from eyes.visual.visual_repair_agent import _generate_and_apply_fix
                    issue = item.get("issue", item.get("improvement", {}))
                    _generate_and_apply_fix(issue)
                break
        json.dump(queue, open(queue_path, "w"), indent=2)
    except Exception as e:
        logging.error(f"Approval processing error: {e}")


# ── Enhancement 1: Health Repair Pipeline ────────────────────────────────────

@app.post("/api/health/repair")
async def api_health_repair() -> Any:
    """Launch 8-stage autonomous health repair pipeline as background task."""
    job_id = f"repair_{str(uuid.uuid4())[:8]}"

    async def _do_repair() -> None:
        sys.path.insert(0, os.path.join(WORKSPACE, "dashboard"))
        try:
            from execution.health_repair_pipeline import run_health_repair

            async def bcast(level: str, content: str) -> None:
                if level == "repair_complete":
                    try:
                        payload = json.loads(content)
                    except Exception:
                        payload = {}
                    await manager.broadcast({
                        "type": "repair_complete",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        **payload,
                    })
                else:
                    icon = {"success": "✓", "warning": "⚠", "error": "✗"}.get(level, "•")
                    lvl = "warn" if level == "warning" else level if level in ("info", "error") else "info"
                    await manager.broadcast({
                        "type": "log",
                        "level": lvl,
                        "icon": icon,
                        "content": content,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })

            await run_health_repair(broadcast=bcast, job_id=job_id)
        except Exception as e:
            logging.exception(f"Health repair error [{job_id}]")
            await manager.broadcast({
                "type": "error",
                "message": f"Repair failed: {e}",
                "ts": datetime.now(timezone.utc).isoformat(),
            })

    asyncio.create_task(_do_repair())
    return {"status": "started", "job_id": job_id, "target": 98}


# ── Enhancement 2: Autolab Experiment Controls ────────────────────────────────

@app.get("/api/lab/autolab/experiments")
async def api_autolab_experiments() -> Any:
    """Parse lab/autolab/experiment_queue.md and return structured experiment list."""
    queue_path = os.path.join(WORKSPACE, "autolab", "experiment_queue.md")
    if not os.path.exists(queue_path):
        return {"experiments": []}
    try:
        content = Path(queue_path).read_text(encoding="utf-8", errors="replace")
        sections = re.split(r"^## ", content, flags=re.MULTILINE)
        experiments = []
        for section in sections:
            section = section.strip()
            if not section:
                continue
            lines = section.split("\n")
            title = lines[0].strip()
            if not title:
                continue
            hyp_m = re.search(r"\*\*Hypothesis\*\*:\s*(.+)", section)
            lvl_m = re.search(r"\*\*Level\*\*:\s*(\w+)", section, re.IGNORECASE)
            typ_m = re.search(r"\*\*Type\*\*:\s*(.+)", section)
            exp_id = "hp_" + hashlib.md5(title.encode()).hexdigest()[:8]
            experiments.append({
                "id": exp_id,
                "name": title[:70],
                "hypothesis": hyp_m.group(1).strip() if hyp_m else title[:80],
                "level": lvl_m.group(1).upper() if lvl_m else "SAFE",
                "type": typ_m.group(1).strip() if typ_m else "improvement",
            })
        return {"experiments": experiments[:20]}
    except Exception as e:
        return {"experiments": [], "error": str(e)}


@app.post("/api/lab/autolab/run")
async def api_autolab_run() -> Any:
    """Trigger autolab runner as background task."""
    job_id = f"autolab_{str(uuid.uuid4())[:8]}"

    async def _do_run() -> None:
        runner = os.path.join(WORKSPACE, "autolab", "runner.py")
        if not os.path.exists(runner):
            await manager.broadcast({
                "type": "log", "level": "warn", "icon": "⚠",
                "content": "Autolab runner not found at lab/autolab/runner.py",
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, runner,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=WORKSPACE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            await manager.broadcast({
                "type": "log", "level": "info", "icon": "✓",
                "content": f"Autolab run [{job_id}] finished",
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logging.error(f"Autolab run error [{job_id}]: {e}")

    asyncio.create_task(_do_run())
    return {"status": "started", "job_id": job_id}


@app.post("/api/lab/autolab/generate")
async def api_autolab_generate() -> Any:
    """Trigger hypothesis generator."""
    gen_bin = os.path.join(WORKSPACE, "bin", "hypothesis-generate")
    try:
        result = subprocess.run(
            [gen_bin] if os.path.exists(gen_bin) else [sys.executable, "-c", "print('no generator')"],
            capture_output=True, text=True, timeout=30, cwd=WORKSPACE,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        return {"status": "done", "count": len(lines), "output": result.stdout[:600]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Ollama ───────────────────────────────────────────────────────────────────

@app.get("/api/ollama/status")
async def get_ollama_status() -> Any:
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            data = json.loads(r.read())
            models = data.get("models", [])
            return {
                "running": True,
                "model_count": len(models),
                "models": [{"name": m["name"], "size": m.get("size", 0)} for m in models],
                "base_url": "http://localhost:11434",
            }
    except Exception as e:
        return {"running": False, "error": str(e), "model_count": 0, "models": []}


@app.get("/widgets/ollama")
async def widget_ollama() -> HTMLResponse:
    from eyes.dashboard.widgets.ollama_status import render_html
    return HTMLResponse(render_html())


# ── Hermes Agent ─────────────────────────────────────────────────────────────

@app.get("/api/hermes/status")
async def get_hermes_status() -> Any:
    try:
        result = subprocess.run(
            ["hermes", "--version"],
            capture_output=True, text=True, timeout=5
        )
        version = result.stdout.strip() if result.returncode == 0 else None

        skills_dir = os.path.expanduser("~/.hermes/skills/")
        skill_count = len(os.listdir(skills_dir)) if os.path.exists(skills_dir) else 0

        sessions_dir = os.path.expanduser("~/.hermes/sessions/")
        last_session = None
        if os.path.exists(sessions_dir):
            sessions = sorted(os.listdir(sessions_dir))
            last_session = sessions[-1] if sessions else None

        has_night_report = os.path.exists(os.path.join(WORKSPACE, "blood/logs/hermes_night_report.md"))

        return {
            "installed": version is not None,
            "version": version,
            "skill_count": skill_count,
            "last_session": last_session,
            "has_night_report": has_night_report,
            "status": "active" if version else "not_installed",
        }
    except Exception as e:
        return {"installed": False, "error": str(e), "status": "error"}


@app.get("/widgets/hermes")
async def widget_hermes() -> HTMLResponse:
    from eyes.dashboard.widgets.hermes_status import render_html
    return HTMLResponse(render_html())


# ── Nerve Monitor ─────────────────────────────────────────────────────────────

@app.get("/api/nerve/status")
async def get_nerve_status() -> Any:
    from eyes.dashboard.widgets.nerve_monitor import get_data
    return get_data()


@app.get("/widgets/nerve")
async def widget_nerve() -> HTMLResponse:
    from eyes.dashboard.widgets.nerve_monitor import render_html
    return HTMLResponse(render_html())


# ── Model Rotation ────────────────────────────────────────────────────────────

@app.get("/api/models/rotation")
async def get_model_rotation() -> Any:
    try:
        from heart.model_router.model_rotator import get_rotation_stats
        return get_rotation_stats()
    except Exception as e:
        return {"error": str(e), "total_rotations": 0}


# ── Health Trend ──────────────────────────────────────────────────────────────

@app.get("/api/health/trend")
async def get_health_trend() -> Any:
    history_path = os.path.join(WORKSPACE, "spine/diagnostics/health_history.json")
    if not os.path.exists(history_path):
        return {"history": [], "trend": "no_data"}
    try:
        history = json.load(open(history_path))
        scores = [h["score"] for h in history[-10:]]
        if len(scores) >= 2:
            delta = scores[-1] - scores[0]
            trend = "improving" if delta > 3 else "declining" if delta < -3 else "stable"
        else:
            trend = "insufficient_data"
        return {"history": history[-10:], "trend": trend, "current": scores[-1] if scores else 0}
    except Exception as e:
        return {"error": str(e), "history": [], "trend": "error"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("eyes.dashboard.server:app", host="127.0.0.1", port=7777, log_level="warning", reload=False)
