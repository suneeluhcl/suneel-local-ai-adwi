"""
diagnostic_scheduler.py
Runs workspace diagnostics on a schedule.
Tracks health score trends over time.
Triggers automatic repair when score drops below threshold.
Runs as a background daemon via tmux.
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone

HEALTH_HISTORY_PATH = "spine/diagnostics/health_history.json"
DIAGNOSTIC_LOG = "blood/logs/diagnostic_schedule.jsonl"
REPAIR_THRESHOLD = 85      # Trigger repair if score drops below this
CHECK_INTERVAL_MINUTES = 240  # Check every 4 hours
TREND_WINDOW = 10          # Track last 10 readings for trend


def read_health_score() -> int:
    """Read current health score."""
    path = "spine/state/WORKSPACE_HEALTH.json"
    try:
        return json.load(open(path)).get("health_score", 0)
    except Exception:
        return 0


def load_health_history() -> list:
    """Load health score history."""
    if not os.path.exists(HEALTH_HISTORY_PATH):
        return []
    try:
        return json.load(open(HEALTH_HISTORY_PATH))
    except Exception:
        return []


def save_health_history(history: list):
    """Save health score history."""
    os.makedirs(os.path.dirname(HEALTH_HISTORY_PATH), exist_ok=True)
    # Keep last 100 readings
    json.dump(history[-100:], open(HEALTH_HISTORY_PATH, "w"), indent=2)


def calculate_trend(history: list, window: int = TREND_WINDOW) -> str:
    """Calculate health score trend from recent history."""
    if len(history) < 2:
        return "insufficient_data"

    recent = history[-window:]
    if len(recent) < 2:
        return "insufficient_data"

    scores = [h["score"] for h in recent]
    first_half = sum(scores[:len(scores)//2]) / (len(scores)//2)
    second_half = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)

    delta = second_half - first_half
    if delta > 3:
        return "improving"
    elif delta < -3:
        return "declining"
    else:
        return "stable"


def run_diagnostic() -> dict:
    """Run a full workspace diagnostic."""
    timestamp = datetime.now(timezone.utc).isoformat()

    # Run agent-doctor
    result = subprocess.run(
        ["agent-doctor"],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.expanduser("~/SuneelWorkSpace")
    )

    # Read health score after doctor runs
    score = read_health_score()

    # Check nerve system
    nerve_result = subprocess.run(
        ["python3", "nervous/nerve_propagator.py"],
        capture_output=True, text=True, timeout=30,
        cwd=os.path.expanduser("~/SuneelWorkSpace")
    )

    diagnostic = {
        "timestamp": timestamp,
        "score": score,
        "doctor_exit_code": result.returncode,
        "nerve_check": "ok" if nerve_result.returncode == 0 else "error",
    }

    # Log diagnostic
    os.makedirs(os.path.dirname(DIAGNOSTIC_LOG), exist_ok=True)
    with open(DIAGNOSTIC_LOG, "a") as f:
        f.write(json.dumps(diagnostic) + "\n")

    return diagnostic


def should_trigger_repair(score: int, trend: str) -> bool:
    """Determine if automatic repair should be triggered."""
    if score < REPAIR_THRESHOLD:
        return True
    if trend == "declining" and score < 92:
        return True
    return False


def trigger_repair():
    """Trigger the health repair pipeline."""
    print(f"  Triggering automatic repair (score below {REPAIR_THRESHOLD}%)...")
    subprocess.Popen(
        ["python3", "-c",
         "import asyncio; from eyes.dashboard.execution.health_repair_pipeline import run_health_repair; "
         "asyncio.run(run_health_repair(lambda l,i,c: print(f'{i} {c}'), 'scheduled_repair', 98))"],
        cwd=os.path.expanduser("~/SuneelWorkSpace")
    )


async def diagnostic_loop():
    """Main diagnostic loop — runs every CHECK_INTERVAL_MINUTES."""
    print(f"Diagnostic Scheduler started")
    print(f"   Interval: every {CHECK_INTERVAL_MINUTES} minutes")
    print(f"   Repair threshold: {REPAIR_THRESHOLD}%")

    while True:
        print(f"\nRunning diagnostic — {datetime.now().strftime('%H:%M:%S')}")

        # Run diagnostic
        diagnostic = run_diagnostic()
        score = diagnostic["score"]
        print(f"  Health score: {score}%")

        # Update history
        history = load_health_history()
        history.append({"timestamp": diagnostic["timestamp"], "score": score})
        save_health_history(history)

        # Calculate trend
        trend = calculate_trend(history)
        print(f"  Trend: {trend}")

        # Check if repair needed
        if should_trigger_repair(score, trend):
            trigger_repair()
        else:
            print(f"  Workspace healthy — no repair needed")

        # Sleep until next check
        print(f"  Next check in {CHECK_INTERVAL_MINUTES} minutes")
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(diagnostic_loop())
