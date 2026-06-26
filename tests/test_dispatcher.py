"""Tests for P3.7 NL command dispatcher."""

import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE / "dispatcher"))

from intent_classifier import classify, resolve, CONFIDENCE_THRESHOLD


@pytest.mark.parametrize("query,expected_intent", [
    ("run health check on workspace",       "health_check"),
    ("show telemetry for last 7 days",      "telemetry_summary"),
    ("compare agent performance",           "agent_compare"),
    ("generate hypotheses",                 "hypothesis_generate"),
    ("fetch arxiv papers on LLMs",          "monitor_run"),
    ("what is the morning brief",           "morning_brief"),
])
def test_high_confidence_routing(query, expected_intent):
    results = classify(query)
    assert results, f"No classification results for: {query!r}"
    top_intent, top_conf, _ = results[0]
    assert top_intent == expected_intent, (
        f"Query {query!r}: expected {expected_intent}, got {top_intent} ({top_conf:.0%})"
    )
    assert top_conf >= CONFIDENCE_THRESHOLD, (
        f"Query {query!r}: confidence {top_conf:.0%} below threshold {CONFIDENCE_THRESHOLD:.0%}"
    )


def test_resolve_returns_command():
    intent, conf, entry, agent = resolve("run health check on workspace")
    assert intent is not None
    assert entry is not None
    assert "command" in entry
    assert entry["command"] == "agent-doctor"


def test_resolve_low_confidence_returns_none():
    """Completely nonsensical input should return low/no confidence."""
    intent, conf, entry, _ = resolve("xzqwerty bloop florp")
    # Either no result or very low confidence
    assert conf < CONFIDENCE_THRESHOLD or intent is None


def test_classify_returns_sorted_by_confidence():
    results = classify("health check workspace")
    assert results, "Expected at least one result"
    confidences = [c for _, c, _ in results]
    assert confidences == sorted(confidences, reverse=True)


def test_all_intents_have_command():
    """Every entry in intent_map.json must have a command field."""
    import json
    map_path = WORKSPACE / "dispatcher" / "intent_map.json"
    data = json.loads(map_path.read_text())
    for name, entry in data["intents"].items():
        assert "command" in entry, f"Intent '{name}' missing 'command'"
        assert entry["command"], f"Intent '{name}' has empty 'command'"
