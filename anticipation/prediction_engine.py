#!/usr/bin/env python3
"""Intent-aware anticipatory intelligence engine."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("SUNEEL_WORKSPACE", Path.home() / "SuneelWorkSpace")).resolve()
BASE = ROOT / "anticipation"
MEMORY = BASE / "prediction_memory.json"
PATTERNS = BASE / "behavior_patterns.json"
CURRENT_CONTEXT = BASE / "current_context.json"
SUGGESTIONS = BASE / "action_suggestions.md"
REPORT = BASE / "reports/anticipation_report.md"

INTENTS = {
    "messaging",
    "email",
    "research",
    "system_improvement",
    "development",
    "idea_execution",
    "maintenance",
    "unknown",
}

COMMAND_INTENTS = {
    "imsg-recent": "messaging",
    "imsg-search": "messaging",
    "imsg-draft": "messaging",
    "imsg-send-confirmed": "messaging",
    "imessage-recent": "messaging",
    "imessage-search": "messaging",
    "imessage-send-draft": "messaging",
    "imessage-status": "messaging",
    "mail-recent": "email",
    "mail-search": "email",
    "mail-draft-reply": "email",
    "mail-status": "email",
    "idea-start": "research",
    "idea-run": "idea_execution",
    "system-audit": "system_improvement",
    "system-gaps": "system_improvement",
    "system-capabilities": "system_improvement",
    "system-recommend": "system_improvement",
    "improve-system": "system_improvement",
    "agent-doctor": "maintenance",
    "agent-maintain": "maintenance",
    "agent-status": "maintenance",
    "mcp-reindex": "maintenance",
    "mcp-status": "maintenance",
    "goal-create": "idea_execution",
    "goal-plan": "idea_execution",
    "goal-execute": "idea_execution",
    "route-task": "development",
    "route-execute": "development",
}


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


def ensure() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / "reports").mkdir(parents=True, exist_ok=True)
    if not MEMORY.exists():
        write_json(
            MEMORY,
            {
                "version": "1.0",
                "events": [],
                "sequence_patterns": [],
                "success_failure_patterns": [],
                "preferred_workflows": [],
            },
        )
    if not PATTERNS.exists():
        write_json(PATTERNS, {"version": "1.0", "built_in_patterns": []})
    if not CURRENT_CONTEXT.exists():
        write_json(
            CURRENT_CONTEXT,
            {
                "version": "1.0",
                "intent": "unknown",
                "confidence": 0.0,
                "last_command": None,
                "recent_actions": [],
                "updated_at": None,
            },
        )


def normalize(command: str) -> str:
    return Path(command).name.strip()


def infer_intent(command: str, context: str = "") -> tuple[str, float]:
    command = normalize(command)
    text = f"{command} {context}".lower()
    if command in COMMAND_INTENTS:
        return COMMAND_INTENTS[command], 0.9
    keyword_map = {
        "messaging": ["imsg", "imessage", "message", "sms", "reply"],
        "email": ["mail", "email", "inbox"],
        "research": ["research", "audit", "recommend", "tool", "compare"],
        "system_improvement": ["system", "improve", "gap", "doctor", "repair", "maintain"],
        "development": ["code", "dev", "route", "build", "test", "script"],
        "idea_execution": ["idea", "goal", "plan", "execute"],
        "maintenance": ["status", "health", "mcp", "backup", "index"],
    }
    for intent, words in keyword_map.items():
        if any(word in text for word in words):
            return intent, 0.65
    return "unknown", 0.25


def update_current_context(command: str, context: str) -> dict[str, Any]:
    intent, confidence = infer_intent(command, context)
    previous = read_json(CURRENT_CONTEXT, {})
    recent = list(previous.get("recent_actions", []))
    recent.append({"command": normalize(command), "context": context, "intent": intent, "timestamp": now()})
    state = {
        "version": "1.0",
        "intent": intent,
        "confidence": confidence,
        "last_command": normalize(command),
        "recent_actions": recent[-20:],
        "updated_at": now(),
    }
    write_json(CURRENT_CONTEXT, state)
    return state


def record(command: str, context: str = "general", exit_code: int = 0, notes: str = "") -> list[dict[str, Any]]:
    ensure()
    command = normalize(command)
    current = update_current_context(command, context)
    data = read_json(MEMORY, {"events": []})
    event = {
        "command": command,
        "context": context,
        "intent": current["intent"],
        "intent_confidence": current["confidence"],
        "exit_code": exit_code,
        "outcome": "success" if exit_code == 0 else "failure",
        "notes": notes,
        "timestamp": now(),
    }
    data.setdefault("events", []).append(event)
    data["events"] = data["events"][-500:]
    update_patterns(data)
    write_json(MEMORY, data)
    suggestions = suggest(command, context, current["intent"])
    write_suggestions(command, current["intent"], suggestions)
    write_report()
    try:
        update_active_context(command, context, suggestions)
    except Exception:
        pass
    return suggestions


def get_active_goal_id() -> str | None:
    try:
        task_graph_path = ROOT / "goal-engine" / "graph" / "task_graph.json"
        if task_graph_path.exists():
            data = json.loads(task_graph_path.read_text())
            goals = data.get("goals", {})
            for gid, goal in goals.items():
                if goal.get("status") in ("active", "paused"):
                    return goal.get("description")
    except Exception:
        pass
    return None


def calculate_confidence(active_context: dict[str, Any], recent_actions: list[dict[str, Any]]) -> float:
    score = 0.1
    goal_desc = active_context.get("current_goal")
    if goal_desc and goal_desc != "None":
        score += 0.4
    workflow = active_context.get("active_workflow", "unknown")
    if workflow != "unknown" and recent_actions:
        last_5_actions = recent_actions[-5:]
        matching_count = sum(1 for a in last_5_actions if a.get("intent") == workflow or a.get("context") == workflow)
        if matching_count >= 3:
            score += 0.3
        elif matching_count >= 1:
            score += 0.1
    current_intent = active_context.get("current_intent", "unknown")
    if current_intent == workflow and workflow != "unknown":
        score += 0.2
    return min(1.0, round(score, 2))


def update_active_context(command: str, context: str, suggestions: list[dict[str, Any]]) -> None:
    import math
    active_context_path = ROOT / "agent-system" / "state" / "ACTIVE_CONTEXT.json"
    prev_context = read_json(active_context_path, {
        "current_goal": None,
        "current_intent": "unknown",
        "active_workflow": "unknown",
        "last_actions": [],
        "next_recommended_actions": [],
        "confidence": 0.0,
        "status": "active",
        "last_updated": "",
        "decay_factor": 1.0,
        "last_active_timestamp": "",
        "context_history": []
    })
    norm_cmd = Path(command).name.strip()
    new_intent, _ = infer_intent(norm_cmd, context)
    
    curr_ctx = read_json(CURRENT_CONTEXT, {})
    recent_actions = curr_ctx.get("recent_actions", [])
    
    # Decay logic
    last_act_ts = prev_context.get("last_active_timestamp")
    decay_factor = 1.0
    if last_act_ts:
        try:
            last_ts = datetime.fromisoformat(last_act_ts)
            current_ts = datetime.now(timezone.utc).astimezone()
            time_delta = (current_ts - last_ts).total_seconds()
            
            threshold = 600  # 10 minutes
            decay_constant = 1800  # 30 minutes
            
            if time_delta > threshold:
                decay_factor = math.exp(-(time_delta - threshold) / decay_constant)
        except Exception:
            pass
            
    prev_context["decay_factor"] = round(decay_factor, 4)
    prev_context["last_active_timestamp"] = now()
    
    # Auto context switching
    current_intent = prev_context.get("current_intent", "unknown")
    switch_intent = False
    
    if new_intent != "unknown" and new_intent != current_intent:
        last_intents = []
        for act in reversed(recent_actions[-3:]):
            act_intent, _ = infer_intent(act.get("command", ""), act.get("context", ""))
            last_intents.append(act_intent)
            
        if len(last_intents) >= 2 and all(i == new_intent for i in last_intents[:2]):
            switch_intent = True
            
    if switch_intent:
        # Archive current context to history
        history_entry = {
            "current_goal": prev_context.get("current_goal"),
            "current_intent": prev_context.get("current_intent"),
            "active_workflow": prev_context.get("active_workflow"),
            "last_actions": prev_context.get("last_actions"),
            "confidence": prev_context.get("confidence"),
            "last_updated": prev_context.get("last_updated"),
            "decay_factor": prev_context.get("decay_factor"),
            "last_active_timestamp": prev_context.get("last_active_timestamp")
        }
        history_list = prev_context.setdefault("context_history", [])
        history_list.append(history_entry)
        prev_context["context_history"] = history_list[-10:]
        
        # Initialize new context values
        prev_context["current_intent"] = new_intent
        prev_context["active_workflow"] = new_intent
        prev_context["last_actions"] = [norm_cmd]
        prev_context["decay_factor"] = 1.0
        prev_context["status"] = "active"
        
        # Log transition
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            log_entry = f"\n## {today}\n\n- Active context auto-switched from '{current_intent}' to '{new_intent}' due to behavioral divergence.\n"
            with open(ROOT / "agent-system" / "logs" / "SESSION_LOG.md", "a") as f:
                f.write(log_entry)
        except Exception:
            pass
    else:
        last_actions = list(prev_context.get("last_actions", []))
        last_actions.append(norm_cmd)
        prev_context["last_actions"] = last_actions[-10:]
        
    goal_desc = get_active_goal_id()
    if goal_desc:
        prev_context["current_goal"] = goal_desc
        prev_context["active_workflow"] = "idea_execution"
    else:
        prev_context["current_goal"] = goal_desc
        if not switch_intent and new_intent != "unknown":
            prev_context["active_workflow"] = new_intent
            prev_context["current_intent"] = new_intent
            
    if prev_context.get("status") not in ["active", "paused", "completed"]:
        prev_context["status"] = "active"
        
    next_recs = []
    for sug in suggestions[:3]:
        next_recs.append(sug.get("text", ""))
    prev_context["next_recommended_actions"] = next_recs
    
    base_confidence = calculate_confidence(prev_context, recent_actions)
    prev_context["confidence"] = round(base_confidence * decay_factor, 2)
    prev_context["last_updated"] = now()
    
    write_json(active_context_path, prev_context)




def update_patterns(data: dict[str, Any]) -> None:
    events = data.get("events", [])
    sequence_counts: Counter[tuple[str, str]] = Counter()
    success_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    workflow_counts: Counter[str] = Counter()
    for prev, curr in zip(events, events[1:]):
        sequence_counts[(prev["command"], curr["command"])] += 1
    for event in events:
        if event.get("outcome") == "success":
            success_counts[event["command"]] += 1
        else:
            failure_counts[event["command"]] += 1
        workflow_counts[event.get("intent") or event.get("context", "unknown")] += 1
    data["sequence_patterns"] = [
        {"after": a, "next": b, "count": c}
        for (a, b), c in sequence_counts.most_common(30)
        if c >= 2
    ]
    data["success_failure_patterns"] = [
        {
            "command": cmd,
            "success_count": success_counts.get(cmd, 0),
            "failure_count": failure_counts.get(cmd, 0),
        }
        for cmd in sorted(set(success_counts) | set(failure_counts))
    ]
    data["preferred_workflows"] = [
        {"intent_or_context": ctx, "count": count}
        for ctx, count in workflow_counts.most_common(20)
        if count >= 2
    ]


def built_in_candidates(command: str) -> list[dict[str, Any]]:
    command = normalize(command)
    patterns = read_json(PATTERNS, {}).get("built_in_patterns", [])
    candidates: list[dict[str, Any]] = []
    for item in patterns:
        if item.get("after") != command:
            continue
        for suggestion in item.get("suggest", []):
            candidates.append(
                {
                    "text": suggestion,
                    "source": "built_in",
                    "frequency_weight": 0.5,
                    "success_weight": 0.5,
                    "recency_weight": 0.3,
                    "identity_alignment": 0.8,
                    "intent_alignment": 0.0,
                }
            )
    return candidates


def learned_candidates(command: str) -> list[dict[str, Any]]:
    data = read_json(MEMORY, {})
    candidates: list[dict[str, Any]] = []
    for item in data.get("sequence_patterns", []):
        if item.get("after") != command:
            continue
        count = float(item.get("count", 0))
        candidates.append(
            {
                "text": f"Based on repeated workflow: run {item['next']}",
                "source": "learned_sequence",
                "frequency_weight": min(1.5, count * 0.4),
                "success_weight": 0.5,
                "recency_weight": 0.5,
                "identity_alignment": 0.7,
                "intent_alignment": 0.0,
            }
        )
    return candidates


def fallback_candidates(intent: str) -> list[dict[str, Any]]:
    fallback = {
        "messaging": ["Review recent message context", "Draft a short reply", "Send only after explicit approval"],
        "email": ["Review relevant mail thread", "Draft a concise reply", "Send only after explicit approval"],
        "research": ["Review generated research artifacts", "Compare options", "Record the decision"],
        "system_improvement": ["Review audit/gap_analysis.md", "Pick one high-impact fix", "Run agent-doctor after changes"],
        "development": ["Inspect relevant files", "Make scoped changes", "Run focused validation"],
        "idea_execution": ["Review the generated plan", "Convert accepted work into a goal", "Run goal-plan"],
        "maintenance": ["Run agent-status", "Run agent-doctor", "Reindex MCP if resources changed"],
        "unknown": ["Clarify intent if risk is high", "Inspect current context", "Choose the smallest safe next step"],
    }
    return [
        {
            "text": text,
            "source": "intent_fallback",
            "frequency_weight": 0.1,
            "success_weight": 0.2,
            "recency_weight": 0.1,
            "identity_alignment": 0.7,
            "intent_alignment": 0.7 if intent != "unknown" else 0.2,
        }
        for text in fallback.get(intent, fallback["unknown"])
    ]


def score_candidate(candidate: dict[str, Any], intent: str) -> dict[str, Any]:
    text = candidate["text"].lower()
    inferred_intent, _ = infer_intent(text, intent)
    if inferred_intent == intent:
        candidate["intent_alignment"] = max(float(candidate.get("intent_alignment", 0)), 0.9)
    elif intent != "unknown":
        candidate["intent_alignment"] = max(float(candidate.get("intent_alignment", 0)), 0.4)
    score = (
        float(candidate.get("frequency_weight", 0))
        + float(candidate.get("success_weight", 0))
        + float(candidate.get("recency_weight", 0))
        + float(candidate.get("identity_alignment", 0))
        + float(candidate.get("intent_alignment", 0))
    )
    candidate["suggestion_score"] = round(score, 2)
    if score >= 3.0:
        candidate["rank"] = "HIGH"
    elif score >= 2.0:
        candidate["rank"] = "MED"
    else:
        candidate["rank"] = "LOW"
    return candidate


def suggest(command: str, context: str = "general", intent: str | None = None) -> list[dict[str, Any]]:
    command = normalize(command)
    if intent is None:
        intent, _ = infer_intent(command, context)
    candidates = built_in_candidates(command) + learned_candidates(command)
    if not candidates:
        candidates = fallback_candidates(intent)
    scored = [score_candidate(item, intent) for item in candidates]
    deduped: dict[str, dict[str, Any]] = {}
    for item in scored:
        key = item["text"].strip().lower()
        if key not in deduped or item["suggestion_score"] > deduped[key]["suggestion_score"]:
            deduped[key] = item
    return sorted(deduped.values(), key=lambda item: item["suggestion_score"], reverse=True)[:5]


def write_suggestions(command: str, intent: str, suggestions: list[dict[str, Any]]) -> None:
    try:
        import execution_engine
        enriched = []
        for item in suggestions:
            text = item["text"]
            score = item.get("suggestion_score", 1.0)
            rank = item.get("rank", "MED")
            level, confidence, readiness, cmd = execution_engine.classify_suggestion(text, score, rank)
            enriched.append({
                "text": text,
                "rank": rank,
                "suggestion_score": score,
                "confidence_score": confidence,
                "execution_level": level,
                "readiness_flag": readiness,
                "command": cmd
            })
    except ImportError:
        enriched = suggestions

    lines = ["# Action Suggestions", "", f"Generated: {now()}", "", f"After: `{command}`", f"Intent: `{intent}`", ""]
    if enriched:
        lines.append("## Suggested Next Actions")
        lines.append("")
        for idx, item in enumerate(enriched[:5], 1):
            if "execution_level" in item:
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
            else:
                lines.append(f"{idx}. [{item['rank']}] {item['text']} (score {item['suggestion_score']})")
            lines.append("")
    else:
        lines.append("No confident suggestions yet.")
    lines.extend(["", "Safety: suggestions are not auto-executed."])
    SUGGESTIONS.write_text("\n".join(lines) + "\n")


def print_suggestions(suggestions: list[dict[str, Any]]) -> None:
    if not suggestions:
        return
    
    try:
        import execution_engine
        enriched = []
        for item in suggestions:
            text = item["text"]
            score = item.get("suggestion_score", 1.0)
            rank = item.get("rank", "MED")
            level, confidence, readiness, cmd = execution_engine.classify_suggestion(text, score, rank)
            enriched.append({
                "text": text,
                "rank": rank,
                "suggestion_score": score,
                "confidence_score": confidence,
                "execution_level": level,
                "readiness_flag": readiness,
                "command": cmd
            })
    except ImportError:
        enriched = suggestions

    print("")
    print("Suggested next actions:")
    for idx, item in enumerate(enriched[:5], 1):
        if "execution_level" in item:
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
        else:
            print(f"{idx}. [{item['rank']}] {item['text']}")



def write_report() -> None:
    data = read_json(MEMORY, {})
    current = read_json(CURRENT_CONTEXT, {})
    lines = [
        "# Anticipation Report",
        "",
        f"Generated: {now()}",
        "",
        "## Status",
        "",
        f"- Current intent: {current.get('intent', 'unknown')}",
        f"- Intent confidence: {current.get('confidence', 0)}",
        f"- Events recorded: {len(data.get('events', []))}",
        f"- Sequence patterns: {len(data.get('sequence_patterns', []))}",
        f"- Preferred workflows: {len(data.get('preferred_workflows', []))}",
        "",
        "## Top Sequence Patterns",
        "",
    ]
    if data.get("sequence_patterns"):
        for item in data["sequence_patterns"][:10]:
            lines.append(f"- After `{item['after']}` -> `{item['next']}` ({item['count']}x)")
    else:
        lines.append("- No repeated sequences yet.")
    lines.extend(
        [
            "",
            "## Ranked Suggestion Contract",
            "",
            "suggestion_score = frequency_weight + success_weight + recency_weight + identity_alignment + intent_alignment",
            "",
            "## Safety",
            "",
            "- The anticipation engine suggests, pre-plans, and pre-computes only.",
            "- It does not auto-execute actions.",
            "- It does not override safety boundaries.",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Anticipatory intelligence engine")
    sub = parser.add_subparsers(dest="action", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--command", required=True)
    rec.add_argument("--context", default="general")
    rec.add_argument("--exit-code", type=int, default=0)
    rec.add_argument("--notes", default="")
    rec.add_argument("--quiet", action="store_true")

    sug = sub.add_parser("suggest")
    sug.add_argument("command")
    sug.add_argument("--context", default="general")

    sub.add_parser("report")
    ctx = sub.add_parser("intent")
    ctx.add_argument("command")
    ctx.add_argument("--context", default="general")

    args = parser.parse_args()
    ensure()
    if args.action == "record":
        suggestions = record(args.command, args.context, args.exit_code, args.notes)
        if not args.quiet:
            print_suggestions(suggestions)
    elif args.action == "suggest":
        current = update_current_context(args.command, args.context)
        suggestions = suggest(args.command, args.context, current["intent"])
        write_suggestions(normalize(args.command), current["intent"], suggestions)
        print_suggestions(suggestions)
        try:
            update_active_context(args.command, args.context, suggestions)
        except Exception:
            pass
    elif args.action == "report":
        write_report()
        print(REPORT)
    elif args.action == "intent":
        intent, confidence = infer_intent(args.command, args.context)
        update_current_context(args.command, args.context)
        print(json.dumps({"intent": intent, "confidence": confidence}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
