"""
personalized_brief.py
Generates a personalized morning brief by combining:
1. World monitor findings (RSS, Arxiv, GitHub)
2. Active goals from heart/goals/
3. Recent evolution events from lab/evolution/
4. Ollama suggestions from last night
5. Workspace health delta
Saves to brain/logs/morning_brief_<date>.md
"""

import json
import os
import re
from datetime import datetime, timezone, date


def read_active_goals() -> list:
    """Read active goals from heart/goals/."""
    goals_path = "heart/goals/goals/active_goals.md"
    if not os.path.exists(goals_path):
        return []
    content = open(goals_path).read()
    goals = re.findall(r'^#+\s+(.+)$', content, re.MULTILINE)
    return goals[:5]


def read_recent_evolution_events(n: int = 5) -> list:
    """Read recent evolution events from lab/evolution/."""
    log_path = "lab/evolution/evolution_log.jsonl"
    if not os.path.exists(log_path):
        return []
    events = []
    with open(log_path) as f:
        for line in f.readlines()[-n:]:
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events


def read_ollama_suggestions() -> str:
    """Read last night's Ollama suggestions."""
    path = "blood/logs/ollama_suggestions.md"
    if not os.path.exists(path):
        return ""
    content = open(path).read()
    # Get last 1000 chars (most recent suggestions)
    return content[-1000:] if len(content) > 1000 else content


def read_health_delta() -> dict:
    """Read health score and compare to yesterday."""
    health_path = "spine/state/WORKSPACE_HEALTH.json"
    if not os.path.exists(health_path):
        return {}
    try:
        health = json.load(open(health_path))
        return {
            "score": health.get("health_score", 0),
            "status": health.get("status", "unknown"),
        }
    except Exception:
        return {}


def read_world_monitor_cache() -> dict:
    """Read today's world monitor cache."""
    today = date.today().isoformat()
    cache = {"rss": [], "arxiv": [], "github": []}

    for source in ["rss", "arxiv", "github"]:
        cache_path = f"ears/monitor/cache/{source}_{today}.json"
        if os.path.exists(cache_path):
            try:
                data = json.load(open(cache_path))
                cache[source] = data if isinstance(data, list) else data.get("items", [])
            except Exception:
                pass

    return cache


def score_item_relevance(item: dict, goal_keywords: list) -> float:
    """Score a world monitor item's relevance to active goals."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    matches = sum(1 for kw in goal_keywords if kw.lower() in text)
    return min(matches / max(len(goal_keywords), 1), 1.0)


def generate_personalized_brief() -> str:
    """Generate the full personalized morning brief."""
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    # Gather all data
    goals = read_active_goals()
    evolution_events = read_recent_evolution_events()
    ollama_suggestions = read_ollama_suggestions()
    health = read_health_delta()
    world_cache = read_world_monitor_cache()

    # Extract keywords from goals for relevance scoring
    goal_keywords = []
    for goal in goals:
        words = [w for w in goal.split() if len(w) > 4]
        goal_keywords.extend(words)

    # Score and filter world monitor items
    relevant_items = []
    for source, items in world_cache.items():
        for item in items[:20]:
            score = score_item_relevance(item, goal_keywords)
            if score > 0.2:
                relevant_items.append({
                    "source": source,
                    "score": score,
                    "title": item.get("title", ""),
                    "url": item.get("url", item.get("link", "")),
                    "summary": item.get("summary", item.get("abstract", ""))[:200],
                })

    relevant_items.sort(key=lambda x: x["score"], reverse=True)

    # Build the brief
    lines = []
    lines.append(f"# Morning Brief — {today}")
    lines.append(f"*Generated: {now} | Health: {health.get('score', '?')}%*")
    lines.append("")

    # Active Goals Section
    if goals:
        lines.append("## Active Goals")
        for goal in goals:
            lines.append(f"- {goal}")
        lines.append("")

    # Workspace Health
    score = health.get("score", 0)
    health_icon = "OK" if score >= 90 else "WARN" if score >= 70 else "CRITICAL"
    lines.append(f"## Workspace Health: {score}% [{health_icon}]")
    lines.append("")

    # Ollama Suggestions (from last night)
    if ollama_suggestions:
        lines.append("## Ollama's Overnight Suggestions")
        lines.append(ollama_suggestions.strip())
        lines.append("")

    # Evolution Events
    if evolution_events:
        lines.append("## Recent Evolution Events")
        for event in evolution_events[-3:]:
            event_type = event.get("event", "?")
            mode = event.get("mode", "?")
            ts = event.get("timestamp", "")[:10]
            lines.append(f"- [{ts}] [{mode}] {event_type}")
        lines.append("")

    # Relevant World Items
    if relevant_items:
        lines.append("## Relevant to Your Goals")
        for item in relevant_items[:5]:
            score_pct = int(item["score"] * 100)
            lines.append(f"### [{score_pct}% match] {item['title']}")
            lines.append(f"*Source: {item['source']}*")
            if item["summary"]:
                lines.append(f"> {item['summary']}")
            if item["url"]:
                lines.append(f"Link: {item['url']}")
            lines.append("")
    else:
        lines.append("## World Monitor")
        lines.append("*No highly relevant items found today — check monitor-config to add more sources*")
        lines.append("")

    lines.append("---")
    lines.append("*Personalized by SuneelWorkSpace ears/ organ*")

    return "\n".join(lines)


def save_brief() -> str:
    """Generate and save the morning brief."""
    brief = generate_personalized_brief()
    today = date.today().isoformat()
    output_path = f"brain/logs/morning_brief_{today}.md"
    os.makedirs("brain/logs", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(brief)
    print(f"Personalized morning brief saved: {output_path}")
    return output_path


if __name__ == "__main__":
    path = save_brief()
    print(open(path).read()[:500])
