"""
model_rotator.py
Intelligent model rotation for SuneelWorkSpace.
Selects the best model for each task type based on:
1. Real telemetry performance (blood/telemetry/telemetry.db)
2. Current quota state (heart/model_router/quota_state.json)
3. Task type requirements
4. Time of day (night = prefer local Ollama to save cloud quota)
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

REGISTRY_PATH = "heart/model_router/model_registry.json"
QUOTA_PATH = "heart/model_router/quota_state.json"
TELEMETRY_DB = "blood/telemetry/telemetry.db"
ROTATION_LOG = "blood/logs/model_rotation.jsonl"

# Task type → preferred model strengths mapping
TASK_MODEL_PREFERENCES = {
    "development":   ["code_generation", "code_repair", "refactoring"],
    "research":      ["reasoning", "long_context", "analysis"],
    "messaging":     ["identity-aligned", "writing", "casual"],
    "maintenance":   ["workspace_aware", "local", "fast"],
    "vision":        ["vision", "screenshot_analysis"],
    "hypothesis":    ["reasoning", "analysis", "hypothesis_generation"],
    "gap_finding":   ["reasoning", "workspace_aware"],
    "repair":        ["workspace_aware", "code_repair", "local"],
    "learning":      ["reasoning", "pattern_recognition"],
    "general":       ["reasoning", "writing"],
}

# Night mode hours — prefer local models to save cloud quota
NIGHT_HOURS = list(range(22, 24)) + list(range(0, 8))


def is_night_mode() -> bool:
    return datetime.now().hour in NIGHT_HOURS


def get_telemetry_scores(task_type: str, days: int = 7) -> dict:
    """Get real performance scores per model from telemetry DB."""
    if not os.path.exists(TELEMETRY_DB):
        return {}

    try:
        conn = sqlite3.connect(TELEMETRY_DB)
        cursor = conn.execute("""
            SELECT agent,
                   COUNT(*) as total,
                   SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) as successes,
                   AVG(duration_ms) as avg_duration
            FROM traces
            WHERE task_type = ?
              AND timestamp > datetime('now', ? || ' days')
            GROUP BY agent
            HAVING total >= 3
        """, (task_type, f"-{days}"))

        scores = {}
        for row in cursor.fetchall():
            agent, total, successes, avg_duration = row
            success_rate = successes / total if total > 0 else 0
            # Normalize duration (lower is better, cap at 60s)
            norm_duration = min(avg_duration or 60000, 60000) / 60000
            # Capability score formula
            scores[agent] = round(0.87 * success_rate + 0.13 * (1 - norm_duration), 3)

        conn.close()
        return scores
    except Exception:
        return {}


def get_best_model_for_task(task_type: str = "general") -> dict:
    """
    Select the best model for a given task type.
    Considers: telemetry performance, quota state, task preferences, time of day.
    """
    registry = json.load(open(REGISTRY_PATH))
    models = registry.get("models", [])

    # Load quota state
    quota_state = {}
    if os.path.exists(QUOTA_PATH):
        try:
            quota_state = json.load(open(QUOTA_PATH))
        except Exception:
            pass

    # Get telemetry scores for this task type
    telemetry_scores = get_telemetry_scores(task_type)

    # Get preferred strengths for this task type
    preferred_strengths = TASK_MODEL_PREFERENCES.get(task_type, TASK_MODEL_PREFERENCES["general"])

    night = is_night_mode()

    scored_models = []
    for model in models:
        model_id = model["id"]

        # Skip if quota exhausted
        model_quota = quota_state.get("models", {}).get(model_id, {})
        if model_quota.get("quota_exhausted", False):
            continue

        # Base score from priority (inverted — lower priority number = higher score)
        priority_score = 1.0 / model["priority"]

        # Telemetry bonus
        telemetry_bonus = telemetry_scores.get(model_id, 0) * 0.3

        # Strength match bonus
        model_strengths = model.get("strengths", [])
        strength_matches = sum(1 for s in preferred_strengths if s in model_strengths)
        strength_bonus = (strength_matches / max(len(preferred_strengths), 1)) * 0.2

        # Night mode bonus for local models
        night_bonus = 0.0
        if night and model.get("provider") == "ollama":
            night_bonus = 0.15  # Prefer local during night to save cloud quota

        # Workspace-aware bonus for suneelworkspace model
        workspace_bonus = 0.1 if model_id == "suneelworkspace" else 0.0

        total_score = priority_score + telemetry_bonus + strength_bonus + night_bonus + workspace_bonus

        scored_models.append({
            "model": model,
            "score": round(total_score, 4),
            "telemetry_score": telemetry_scores.get(model_id, 0),
            "strength_matches": strength_matches,
            "night_bonus": night_bonus,
        })

    if not scored_models:
        # Fallback to first available model
        return models[0] if models else {}

    # Sort by score descending
    scored_models.sort(key=lambda x: x["score"], reverse=True)
    best = scored_models[0]

    # Log rotation decision
    _log_rotation(task_type, best["model"]["id"], best["score"], night)

    return best["model"]


def _log_rotation(task_type: str, model_id: str, score: float, night_mode: bool):
    """Log model selection to rotation log."""
    os.makedirs(os.path.dirname(ROTATION_LOG), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_type": task_type,
        "selected_model": model_id,
        "score": score,
        "night_mode": night_mode,
    }
    with open(ROTATION_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_rotation_stats(days: int = 7) -> dict:
    """Get model rotation statistics."""
    if not os.path.exists(ROTATION_LOG):
        return {"total_rotations": 0, "by_model": {}, "by_task": {}}

    entries = []
    with open(ROTATION_LOG) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass

    by_model = {}
    by_task = {}
    for e in entries:
        m = e.get("selected_model", "?")
        t = e.get("task_type", "?")
        by_model[m] = by_model.get(m, 0) + 1
        by_task[t] = by_task.get(t, 0) + 1

    return {
        "total_rotations": len(entries),
        "by_model": by_model,
        "by_task": by_task,
    }


if __name__ == "__main__":
    print("Model Rotation Stats:")
    stats = get_rotation_stats()
    print(f"  Total rotations: {stats['total_rotations']}")
    print(f"  By model: {stats['by_model']}")
    print(f"  By task: {stats['by_task']}")
    print()
    for task in TASK_MODEL_PREFERENCES.keys():
        best = get_best_model_for_task(task)
        print(f"  Best for {task}: {best.get('id', '?')}")
