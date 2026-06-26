#!/usr/bin/env python3
"""SuneelWorkSpace Control Center — FastAPI server with WebSocket execution streaming."""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime
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

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(WORKSPACE, "agent-system", "logs")
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


manager = ConnectionManager()

# Pending confirm responses: client_id → asyncio.Future
_confirm_futures: dict[str, asyncio.Future] = {}


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(ws: WebSocket, client_id: str) -> None:
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

            elif msg_type == "ping":
                await manager.send(client_id, {"type": "pong", "ts": datetime.now().isoformat()})

    except WebSocketDisconnect:
        manager.disconnect(client_id)


# ── Pipeline runner ─────────────────────────────────────────────────────────

async def _run_pipeline(client_id: str, prompt: str, mode: str) -> None:
    """Run the 6-stage pipeline with live WebSocket streaming."""
    sys.path.insert(0, WORKSPACE)
    try:
        from dashboard.pipeline.pipeline import Pipeline
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
        "ts": datetime.now().isoformat(),
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


@app.get("/api/health")
async def api_health() -> Any:
    health = get_memory_health()
    score = 100 - (health.get("total_errors", 0) * 30) - (health.get("total_warnings", 0) * 10)
    return {"score": max(0, min(100, score)), "status": health.get("status", "healthy")}


@app.get("/api/telemetry")
async def api_telemetry() -> Any:
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "agent-system", "telemetry"))
        from telemetry_query import summary
        return summary(days=7)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/history")
async def api_history(limit: int = 50) -> Any:
    return _load_history(limit)


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
