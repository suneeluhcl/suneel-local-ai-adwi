"""
ollama_learning_engine.py
Uses Ollama to generate skill documents and learn from workspace patterns.
No API costs. No quota limits. Runs during night shift.
"""

import json
import os
import urllib.request
from datetime import datetime, timezone

OLLAMA_BASE = "http://localhost:11434"
SKILLS_DIR = "dna/agents/hermes/skills"
LEARNING_LOG = "blood/logs/ollama_learning.jsonl"


def ask_ollama(prompt: str, model: str = "llama3.1", timeout: int = 180) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4, "num_ctx": 4096}
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception:
        return ""


def learn_from_nerve_events() -> str:
    """Analyze nerve events to understand workspace change patterns."""
    nerve_log = "blood/logs/nerve_events.jsonl"
    if not os.path.exists(nerve_log):
        return ""

    events = []
    with open(nerve_log) as f:
        for line in f.readlines()[-50:]:
            try:
                events.append(json.loads(line))
            except Exception:
                pass

    if not events:
        return ""

    event_summary = "\n".join([
        f"- {e.get('source_organ','?')} → {e.get('change_type','?')}: {e.get('changed_path','?')}"
        for e in events[-20:]
    ])

    prompt = f"""Analyze these SuneelWorkSpace nerve system events and identify patterns:

{event_summary}

What patterns do you see? What does this tell us about how the workspace is being used?
What improvements could be made based on these patterns?

Be specific and actionable. Focus on the most impactful patterns."""

    return ask_ollama(prompt)


def generate_skill_document(topic: str, context: str) -> str:
    """Generate a Hermes skill document for a specific workspace topic."""
    prompt = f"""Create a Hermes Agent skill document for: {topic}

Context about SuneelWorkSpace:
{context}

Format as a Markdown skill document that Hermes can use to better handle this topic.
Include:
1. When to use this skill
2. Step-by-step procedure
3. Key commands and file paths
4. Common issues and solutions
5. Success criteria

Be specific to SuneelWorkSpace's Human Body Architecture."""

    return ask_ollama(prompt, model="llama3.1")


def learn_from_repair_history() -> str:
    """Learn from past repair cycles to improve future repairs."""
    suggestions_log = "blood/logs/ollama_suggestions.md"
    if not os.path.exists(suggestions_log):
        return ""

    content = open(suggestions_log).read()[-3000:]

    prompt = f"""Review these past workspace improvement suggestions and identify:
1. Which types of issues keep recurring
2. Which fixes were most effective
3. What proactive measures could prevent these issues

Past suggestions:
{content}

Generate 3 proactive improvements that would prevent the most common issues."""

    return ask_ollama(prompt)


def run_learning_cycle():
    """Run a complete Ollama-powered learning cycle."""
    print(f"🧠 Ollama Learning Engine starting — {datetime.now().strftime('%H:%M:%S')}")

    os.makedirs(SKILLS_DIR, exist_ok=True)
    os.makedirs("blood/logs", exist_ok=True)

    # 1. Learn from nerve events
    print("🔍 Analyzing nerve system patterns...")
    nerve_insights = learn_from_nerve_events()
    if nerve_insights:
        skill_path = f"{SKILLS_DIR}/workspace-patterns.md"
        with open(skill_path, "w") as f:
            f.write("# Workspace Pattern Analysis\n\n")
            f.write(f"*Generated: {datetime.now(timezone.utc).isoformat()}*\n\n")
            f.write(nerve_insights)
        print(f"  ✅ Pattern analysis saved to {skill_path}")

    # 2. Learn from repair history
    print("📚 Learning from repair history...")
    repair_insights = learn_from_repair_history()
    if repair_insights:
        skill_path = f"{SKILLS_DIR}/repair-patterns.md"
        with open(skill_path, "w") as f:
            f.write("# Repair Pattern Learning\n\n")
            f.write(f"*Generated: {datetime.now(timezone.utc).isoformat()}*\n\n")
            f.write(repair_insights)
        print(f"  ✅ Repair patterns saved to {skill_path}")

    # 3. Generate workspace navigation skill
    print("🗺️  Generating workspace navigation skill...")
    nav_skill = generate_skill_document(
        "SuneelWorkSpace Navigation and Operations",
        "12-organ Human Body Architecture. Key commands: memory-search, brain-inject, "
        "ws 'natural language', workspace-dashboard, autolab-run, evolution-start, "
        "morning-brief, nerve-status, model-status, agent-doctor, ollama-repair"
    )
    if nav_skill:
        skill_path = f"{SKILLS_DIR}/suneelworkspace-navigation.md"
        with open(skill_path, "w") as f:
            f.write(nav_skill)
        print(f"  ✅ Navigation skill saved to {skill_path}")

    # Log learning cycle
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "learning_cycle_complete",
        "skills_generated": 3,
    }
    with open(LEARNING_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    print("✅ Learning cycle complete")


if __name__ == "__main__":
    run_learning_cycle()
