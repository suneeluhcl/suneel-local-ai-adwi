#!/usr/bin/env python3
"""Classify natural language input to workspace intents."""

import json
import re
from pathlib import Path

INTENT_MAP_PATH = Path(__file__).parent / "intent_map.json"
LEADERBOARD_PATH = Path(__file__).parent.parent.parent / "blood" / "telemetry" / "comparison" / "leaderboard.json"
CONFIDENCE_THRESHOLD = 0.7


def _load_intents() -> dict:
    return json.loads(INTENT_MAP_PATH.read_text())["intents"]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-z0-9]{2,}\b", text.lower())


def classify(query: str) -> list[tuple[str, float, dict]]:
    """Return list of (intent_name, confidence, entry) sorted by confidence desc."""
    intents = _load_intents()
    query_lower = query.lower()
    query_tokens = set(_tokenize(query))
    scored = []

    for intent_name, entry in intents.items():
        keywords = entry.get("keywords", [])
        phrase_hits = 0.0
        token_hits = 0.0
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in query_lower:
                if " " in kw_lower:
                    phrase_hits += 1.0   # multi-word phrase match — strong signal
                else:
                    token_hits += 1.0
        # Token overlap bonus (partial keyword coverage)
        kw_tokens = set(_tokenize(" ".join(keywords)))
        overlap = len(query_tokens & kw_tokens) * 0.5
        raw = phrase_hits * 3.0 + token_hits + overlap
        if raw > 0:
            # Saturate at 4 raw points = 100% confidence
            confidence = min(raw / 4.0, 1.0)
            scored.append((intent_name, confidence, entry))

    scored.sort(key=lambda x: -x[1])
    return scored


def best_agent_for(task_type: str) -> str | None:
    """Check leaderboard for best-performing agent for this task type."""
    if not LEADERBOARD_PATH.exists():
        return None
    try:
        lb = json.loads(LEADERBOARD_PATH.read_text())
        agents = lb.get(task_type, {})
        if not agents:
            return None
        return max(agents, key=lambda a: agents[a]["capability_score"])
    except Exception:
        return None


def resolve(query: str) -> tuple[str | None, float, dict | None, str | None]:
    """
    Returns (intent_name, confidence, entry, best_agent).
    intent_name is None if confidence < threshold and no clear winner.
    """
    results = classify(query)
    if not results:
        return None, 0.0, None, None

    top_intent, top_conf, top_entry = results[0]
    agent = best_agent_for(top_entry.get("task_type", ""))
    return top_intent, top_conf, top_entry, agent
