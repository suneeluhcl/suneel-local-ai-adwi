"""Model Router — selects best available model with automatic fallback."""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
WORKSPACE = _HERE.parent.parent
FALLBACK_LOG = _HERE / "fallback_log.jsonl"

# Keep imports lazy so the module is importable without side effects
def _get_quota():
    from heart.model_router.quota_tracker import get_status, record_usage, mark_unavailable
    return get_status, record_usage, mark_unavailable


FALLBACK_CHAIN = [
    "claude-sonnet-4-6",
    "claude-opus-4-8",
    "gpt-4o",
    "gemini-2.5-pro",
]

TASK_ROUTING: dict[str, str] = {
    "code":     "claude-sonnet-4-6",
    "analysis": "claude-sonnet-4-6",
    "quick":    "claude-haiku-4-5-20251001",
    "vision":   "claude-sonnet-4-6",
    "research": "gemini-2.5-pro",
    "default":  "claude-sonnet-4-6",
}


def _log_fallback(from_model: str, to_model: str, reason: str) -> None:
    try:
        FALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "from": from_model,
            "to": to_model,
            "reason": reason,
        }
        with open(FALLBACK_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def get_best_model(task_type: str = "default", preferred: str = None) -> str:
    """Return the best available model for the given task type."""
    get_status, _, _ = _get_quota()
    status = get_status()
    available: dict[str, bool] = {m["id"]: m["available"] for m in status.get("models", [])}

    preferred_model = preferred or TASK_ROUTING.get(task_type, TASK_ROUTING["default"])

    if available.get(preferred_model, True):
        return preferred_model

    for model in FALLBACK_CHAIN:
        if model != preferred_model and available.get(model, True):
            _log_fallback(preferred_model, model, f"preferred unavailable for task:{task_type}")
            logging.info(f"Model router: falling back {preferred_model} → {model}")
            return model

    logging.warning("Model router: all tracked models appear unavailable, using chain[0]")
    return FALLBACK_CHAIN[0]


def get_fallback_chain() -> list:
    get_status, _, _ = _get_quota()
    status = get_status()
    by_id = {m["id"]: m for m in status.get("models", [])}
    chain = []
    for mid in FALLBACK_CHAIN:
        info = by_id.get(mid, {})
        chain.append({
            "id": mid,
            "available": info.get("available", True),
            "tokens_today": info.get("tokens_used_today", 0),
            "calls_today": info.get("calls_today", 0),
        })
    return chain


# ── Ollama REST API support ───────────────────────────────────────────────

def _is_ollama_running() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False


def _start_ollama_if_needed():
    import subprocess, time
    if not _is_ollama_running():
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)


def _call_ollama_api(model_name: str, prompt: str, timeout: int = 120) -> dict:
    """Call Ollama via REST API for better reliability than CLI."""
    import urllib.request, json as _json
    payload = _json.dumps({
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": 8192}
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            result = _json.loads(r.read())
            return {"success": True, "output": result.get("response", "").strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else "default"
    print(get_best_model(task))
