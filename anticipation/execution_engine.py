#!/usr/bin/env python3
"""Semi-autonomous execution engine for SuneelWorkSpace."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SUNEEL_WORKSPACE", Path.home() / "SuneelWorkSpace")).resolve()
sys.path.append(str(ROOT))
sys.path.append(str(ROOT / "anticipation"))

try:
    import prediction_engine
except ImportError:
    prediction_engine = None

STATE_FILE = ROOT / "anticipation" / "execution_state.json"
CONTEXT_FILE = ROOT / "anticipation" / "current_context.json"
SUGGESTIONS_MD = ROOT / "anticipation" / "action_suggestions.md"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def init_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        state = {
            "version": "1.0",
            "last_executed_command": None,
            "last_execution_time": None,
            "execution_history": [],
            "auto_execute_safe": True,
        }
        write_json(STATE_FILE, state)
        return state
    return read_json(STATE_FILE, {})


def map_text_to_command(text: str) -> str:
    text_lower = text.lower()
    
    # Precise command mappings
    if "imessage-recent" in text_lower or "recent messages" in text_lower:
        return "bin/imessage-recent"
    elif "imessage-send-draft" in text_lower or "draft replies" in text_lower:
        return "bin/imessage-send-draft"
    elif "mail-recent" in text_lower or "recent mail" in text_lower:
        return "bin/mail-recent"
    elif "mail-draft-reply" in text_lower or "draft a concise reply" in text_lower:
        return "bin/mail-draft-reply"
    elif "goal-plan" in text_lower:
        return "bin/goal-plan"
    elif "route-task" in text_lower:
        return "bin/route-task"
    elif "goal-create" in text_lower or "turn a p0/p1 gap into a goal" in text_lower or "convert accepted work" in text_lower:
        return "bin/goal-create"
    elif "improve-system" in text_lower:
        return "bin/improve-system"
    elif "agent-status" in text_lower:
        return "bin/agent-status"
    elif "agent-doctor" in text_lower:
        return "bin/agent-doctor"
    elif "mcp-reindex" in text_lower:
        return "bin/mcp-reindex"
    elif "open audit/improvement_plan.md" in text_lower:
        return "cat audit/improvement_plan.md"
    elif "review audit/gap_analysis.md" in text_lower:
        return "cat audit/gap_analysis.md"
    elif "system-gaps" in text_lower:
        return "bin/system-gaps"
    elif "git status" in text_lower:
        return "git status"
    elif "git diff" in text_lower:
        return "git diff"
    elif "git log" in text_lower:
        return "git log -n 5"
    elif "run " in text_lower:
        # Extract command name if possible, e.g. "run improve-system"
        parts = text_lower.split("run ")
        if len(parts) > 1:
            cmd = parts[1].strip().split()[0]
            # Strip trailing punctuation
            cmd = cmd.rstrip(".,?!")
            # If command exists as executable in bin, prefix with bin/
            if (ROOT / "bin" / cmd).exists():
                return f"bin/{cmd}"
            return cmd
            
    # Subsystem execution mapping fallback
    if "status" in text_lower or "doctor" in text_lower:
        return "bin/agent-doctor"
    elif "changes" in text_lower:
        return "bin/workspace-changes"
    elif "plan" in text_lower:
        return "bin/goal-plan"

    return ""


def classify_suggestion(text: str, score: float, rank: str) -> tuple[str, float, bool, str]:
    """Classifies a suggestion into SAFE, CONTROLLED, or RESTRICTED and calculates confidence and readiness."""
    text_lower = text.lower()
    
    # 1. Determine execution level
    # SAFE: read-only, metadata, analysis
    # RESTRICTED: sending messages, deleting files, external installs
    # CONTROLLED: drafting, planning, local file creation (default)
    if any(k in text_lower for k in ["send", "delete", "remove", "destroy", "install", "upgrade", "push", "npm install", "pip install", "brew install"]):
        level = "RESTRICTED"
    elif any(k in text_lower for k in ["view", "show", "status", "doctor", "history", "recent", "search", "audit", "changes", "list", "read-only", "analysis", "inspect", "check", "gaps", "report", "cat ", "ls ", "git status", "git diff", "git log", "open"]):
        level = "SAFE"
    else:
        level = "CONTROLLED"
        
    # 2. Determine confidence score (0.0 to 1.0)
    # Map score (typically 0.1 to 5.0) to 0.0 to 1.0
    if rank == "HIGH":
        confidence = min(0.99, 0.85 + (score * 0.03))
    elif rank == "MED":
        confidence = min(0.84, 0.60 + (score * 0.05))
    else:
        confidence = min(0.59, 0.10 + (score * 0.10))
        
    # 3. Map to executable command
    command = map_text_to_command(text)
    
    # 4. Determine readiness_flag
    # Default ready to True if we mapped to a valid executable command/file
    readiness = False
    if command:
        parts = command.split()
        cmd_name = parts[0]
        if cmd_name.startswith("bin/"):
            readiness = (ROOT / cmd_name).exists()
        elif cmd_name == "cat":
            if len(parts) > 1:
                readiness = (ROOT / parts[1]).exists()
            else:
                readiness = False
        else:
            # Check if command exists in system PATH
            readiness = subprocess.call(f"command -v {cmd_name} >/dev/null 2>&1", shell=True) == 0
            
    # For suggestions that can't be mapped directly to a CLI command, readiness is false (requires manual step)
    return level, round(confidence, 2), readiness, command


def get_enriched_suggestions() -> list[dict[str, Any]]:
    """Fetches suggestions from prediction engine and enriches them with execution metadata."""
    if not prediction_engine:
        return []
    
    prediction_engine.ensure()
    context = read_json(CONTEXT_FILE, {})
    last_command = context.get("last_command") or "agent-status"
    intent = context.get("intent") or "unknown"
    
    raw_suggestions = prediction_engine.suggest(last_command, context.get("context", "general"), intent)
    
    enriched = []
    for item in raw_suggestions:
        text = item["text"]
        score = item.get("suggestion_score", 1.0)
        rank = item.get("rank", "MED")
        
        level, confidence, readiness, command = classify_suggestion(text, score, rank)
        
        enriched.append({
            "text": text,
            "rank": rank,
            "suggestion_score": score,
            "confidence_score": confidence,
            "execution_level": level,
            "readiness_flag": readiness,
            "command": command
        })
    return enriched


def update_suggestions_file(enriched: list[dict[str, Any]], last_command: str, intent: str) -> None:
    """Updates action_suggestions.md to include Phase 2 metadata format."""
    lines = [
        "# Action Suggestions",
        "",
        f"Generated: {now()}",
        "",
        f"After: `{last_command}`",
        f"Intent: `{intent}`",
        "",
        "## Suggested Next Actions",
        ""
    ]
    
    if enriched:
        for idx, item in enumerate(enriched[:5], 1):
            lines.append(f"{idx}. [{item['rank']} | {item['execution_level']} | {item['confidence_score']}]")
            lines.append(f"   {item['text']}")
            if item['readiness_flag']:
                if item['execution_level'] == 'SAFE':
                    lines.append("   → Ready to run")
                elif item['execution_level'] == 'CONTROLLED':
                    lines.append("   → Run now? (y/n)")
                else:
                    lines.append("   → Approval required")
            else:
                lines.append("   → Prerequisites missing or manual action required")
            lines.append("")
    else:
        lines.append("No confident suggestions yet.")
        lines.append("")
        
    lines.append("Safety: suggestions require level-appropriate verification.")
    SUGGESTIONS_MD.write_text("\n".join(lines) + "\n")


def execute_action(action: dict[str, Any], reason: str | None = None) -> tuple[bool, str]:
    """Executes the mapped command for a suggestion, respecting execution levels."""
    command = action.get("command")
    level = action.get("execution_level", "CONTROLLED")
    
    if not command:
        return False, "No executable command mapped for this suggestion."
        
    if not action.get("readiness_flag", False):
        return False, "Action is marked as not ready (missing prerequisites)."
        
    print(f"\nExecuting: {command} (Level: {level})")
    
    # Prefix commands with rtk as per instructions (Rust Token Killer)
    exec_cmd = command
    if not command.startswith("rtk") and not command.startswith("cat"):
        exec_cmd = f"rtk {command}"
        
    # Log attempt to execution state
    state = init_state()
    execution_event = {
        "timestamp": now(),
        "command": command,
        "execution_level": level,
        "reason": reason,
        "status": "pending"
    }
    state["execution_history"].append(execution_event)
    write_json(STATE_FILE, state)
    
    try:
        # Run command in shell
        result = subprocess.run(
            exec_cmd,
            shell=True,
            cwd=str(ROOT),
            text=True,
            capture_output=False  # Print output directly to user terminal
        )
        
        status = "success" if result.returncode == 0 else "failed"
        
        # Update execution state
        state["last_executed_command"] = command
        state["last_execution_time"] = now()
        state["execution_history"][-1]["status"] = status
        state["execution_history"][-1]["return_code"] = result.returncode
        write_json(STATE_FILE, state)
        
        # Also record to prediction engine memory if possible
        if prediction_engine:
            prediction_engine.record(command, context="execution_engine", exit_code=result.returncode, notes=f"Executed via engine: {reason or ''}")
            
        return result.returncode == 0, f"Command completed with exit code {result.returncode}."
        
    except Exception as e:
        error_msg = str(e)
        state["execution_history"][-1]["status"] = "error"
        state["execution_history"][-1]["error"] = error_msg
        write_json(STATE_FILE, state)
        return False, f"Execution failed: {error_msg}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Semi-autonomous execution engine")
    sub = parser.add_subparsers(dest="action", required=True)
    
    sub.add_parser("suggest")
    
    exec_parser = sub.add_parser("execute")
    exec_parser.add_argument("index", type=int, help="1-based index of suggestion to execute")
    exec_parser.add_argument("--reason", help="Confirmation reason for RESTRICTED actions")
    
    args = parser.parse_args()
    init_state()
    
    if args.action == "suggest":
        enriched = get_enriched_suggestions()
        context = read_json(CONTEXT_FILE, {})
        last_command = context.get("last_command") or "agent-status"
        intent = context.get("intent") or "unknown"
        update_suggestions_file(enriched, last_command, intent)
        
        print("\nSuggested next actions:")
        for idx, item in enumerate(enriched[:3], 1):
            print(f"{idx}. [{item['rank']} | {item['execution_level']} | {item['confidence_score']}]")
            print(f"   {item['text']}")
            if item['readiness_flag']:
                if item['execution_level'] == 'SAFE':
                    print("   → Ready to run")
                elif item['execution_level'] == 'CONTROLLED':
                    print("   → Run now? (y/n)")
                else:
                    print("   → Approval required")
            else:
                print("   → Prerequisites missing or manual action required")
            print("")
            
    elif args.action == "execute":
        enriched = get_enriched_suggestions()
        if not enriched:
            print("No active suggestions found.")
            return 1
            
        idx = args.index - 1
        if idx < 0 or idx >= len(enriched):
            print(f"Invalid index {args.index}. Must be between 1 and {len(enriched)}.")
            return 1
            
        action = enriched[idx]
        level = action["execution_level"]
        
        # Validate safety flows
        if level == "RESTRICTED":
            if not args.reason:
                print("ERROR: Restricted actions require a explicit confirmation reason via --reason.")
                return 1
            reason = args.reason
        else:
            reason = args.reason or "User selection"
            
        success, msg = execute_action(action, reason)
        print(msg)
        return 0 if success else 1
        
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
