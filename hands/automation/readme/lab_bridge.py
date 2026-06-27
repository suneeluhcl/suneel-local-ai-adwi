#!/usr/bin/env python3
"""
Lab Bridge — triggers lab evolution cycles for folders with health score below threshold.
Writes JSON challenge files to lab/autolab/challenges/ for the autolab runner to pick up.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

WORKSPACE = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True,
    cwd=os.path.dirname(os.path.abspath(__file__))
).strip())

CHALLENGES_DIR = WORKSPACE / "lab/autolab/challenges"
DEFAULT_THRESHOLD = 60


def _write_challenge(folder_rel: str, score: int, issues: list) -> Path:
    CHALLENGES_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = folder_rel.replace("/", "_").replace("\\", "_")
    challenge_path = CHALLENGES_DIR / f"readme_health_{safe_name}.json"

    challenge = {
        "type": "readme_health_improvement",
        "target_folder": folder_rel,
        "health_score": score,
        "critical_issues": issues,
        "created": datetime.now().isoformat(),
        "priority": "high" if score < 40 else "medium",
        "instructions": (
            f"The folder '{folder_rel}' has README health score {score}/100. "
            f"Issues: {issues}. "
            f"Fix the issues, update README, re-run `readme-update {folder_rel}` "
            f"and confirm the health score improves above {DEFAULT_THRESHOLD}."
        ),
    }

    challenge_path.write_text(json.dumps(challenge, indent=2))
    return challenge_path


def trigger_evolution_for_low_health(threshold: int = DEFAULT_THRESHOLD, dry_run: bool = False) -> dict:
    """
    Find all cache-tracked folders with health < threshold and write lab challenge files.

    Returns:
        {triggered: list[str], skipped: list[str], threshold: int, dry_run: bool}
    """
    from hands.automation.readme.cache_manager import get_low_health_folders, load_cache
    from hands.automation.readme.health_scorer import score_folder

    cache = load_cache()
    low_folders = get_low_health_folders(threshold, cache)

    triggered = []
    skipped = []

    for entry in low_folders:
        folder_rel = entry["path"]
        cached_score = entry["score"]

        # Re-verify with live score (cache may be stale)
        folder_abs = str(WORKSPACE / folder_rel)
        try:
            live = score_folder(folder_abs)
            score = live["score"]
            issues = live["critical_issues"]
        except Exception:
            score = cached_score
            issues = [f"Cached score below threshold ({cached_score})"]

        if score >= threshold:
            skipped.append(f"{folder_rel} (live score {score} >= {threshold})")
            continue

        # Skip if challenge already pending
        safe_name = folder_rel.replace("/", "_").replace("\\", "_")
        existing = CHALLENGES_DIR / f"readme_health_{safe_name}.json"
        if existing.exists():
            skipped.append(f"{folder_rel} (challenge already queued)")
            continue

        if dry_run:
            print(f"  [dry-run] Would trigger evolution: {folder_rel} (score={score})")
        else:
            challenge_path = _write_challenge(folder_rel, score, issues)
            print(f"  🧬 Evolution triggered: {folder_rel} (score={score}) → {challenge_path.name}")

            # Notify nervous system
            try:
                subprocess.run(
                    [sys.executable, str(WORKSPACE / "nervous/nerve_propagator.py"),
                     "notify", "lab", f"readme_evolution_triggered:{folder_rel}"],
                    cwd=str(WORKSPACE),
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass

        triggered.append(folder_rel)

    return {
        "triggered": triggered,
        "skipped": skipped,
        "threshold": threshold,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trigger evolution for low-health README folders")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"Health score threshold (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be triggered without writing files")
    args = parser.parse_args()

    result = trigger_evolution_for_low_health(args.threshold, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
