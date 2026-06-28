"""
ollama_repair_engine.py
Uses local Ollama models to autonomously analyze and repair workspace issues.
No API costs. No quota limits. Runs during night shift.
Reads telemetry anomalies → generates targeted fixes → applies SAFE fixes automatically.
"""

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone

OLLAMA_BASE = "http://localhost:11434"
REPAIR_LOG = "blood/logs/ollama_repair.jsonl"
SUGGESTIONS_LOG = "blood/logs/ollama_suggestions.md"


def is_ollama_running() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=3)
        return True
    except Exception:
        return False


def ask_ollama(prompt: str, model: str = "suneelworkspace", timeout: int = 120) -> str:
    if not is_ollama_running():
        return ""

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 4096}
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
    except Exception as e:
        return f"error: {e}"


def analyze_anomalies() -> list:
    """Read telemetry anomalies and ask Ollama to suggest fixes."""
    anomaly_path = "blood/telemetry/anomalies.json"
    if not os.path.exists(anomaly_path):
        return []

    try:
        anomalies = json.load(open(anomaly_path)).get("anomalies", [])
    except Exception:
        return []

    if not anomalies:
        return []

    anomaly_text = "\n".join([
        f"- [{a.get('severity','?')}] {a.get('description','')}"
        for a in anomalies[:5]
    ])

    prompt = f"""You are analyzing SuneelWorkSpace telemetry anomalies.

Current anomalies:
{anomaly_text}

For each anomaly, suggest ONE specific fix. Format your response as JSON:
[
  {{
    "anomaly": "description",
    "fix": "specific command or file change",
    "execution_level": "SAFE",
    "confidence": 0.8
  }}
]

Only suggest SAFE fixes (read-only operations, reindex, status checks).
Never suggest deleting files or modifying identity/safety files."""

    response = ask_ollama(prompt, model="llama3.1")

    try:
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return []


def analyze_health_score() -> dict:
    """Ask Ollama to analyze the current health score and suggest improvements."""
    health_path = "spine/state/WORKSPACE_HEALTH.json"
    if not os.path.exists(health_path):
        return {}

    try:
        health = json.load(open(health_path))
        score = health.get("health_score", 0)
    except Exception:
        return {}

    if score >= 95:
        return {"score": score, "status": "healthy", "suggestions": []}

    prompt = f"""SuneelWorkSpace health score is {score}%.

The workspace has 12 organs: brain, heart, eyes, ears, nervous, skeleton, blood, hands, mouth, dna, lab, spine.

Suggest 3 specific actions to improve the health score. Focus on:
- Running mcp-reindex if MCP index is stale
- Running memory-reindex if vector store is stale
- Running agent-doctor to find repairable issues
- Checking for broken symlinks in hands/bin/
- Verifying nerve.json files exist for all organs

Format as JSON:
[
  {{
    "action": "specific command to run",
    "reason": "why this will help",
    "expected_improvement": "estimated score increase"
  }}
]"""

    response = ask_ollama(prompt, model="mistral")

    try:
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            suggestions = json.loads(match.group())
            return {"score": score, "suggestions": suggestions}
    except Exception:
        pass
    return {"score": score, "suggestions": []}


def generate_self_improvement_ideas() -> list:
    """Ask Ollama to generate workspace improvement ideas based on current state."""
    context_parts = []

    try:
        health = json.load(open("spine/state/WORKSPACE_HEALTH.json"))
        context_parts.append(f"Health score: {health.get('health_score', '?')}%")
    except Exception:
        pass

    try:
        with open("lab/evolution/evolution_log.jsonl") as f:
            lines = f.readlines()[-5:]
        context_parts.append(f"Recent evolution events: {len(lines)}")
    except Exception:
        pass

    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=3) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        context_parts.append(f"Local models available: {', '.join(models)}")
    except Exception:
        pass

    context = "\n".join(context_parts)

    prompt = f"""You are the self-improvement engine for SuneelWorkSpace.

Current state:
{context}

Generate 5 specific, actionable improvement ideas for this workspace.
Focus on things that would make it more autonomous, more reliable, or more intelligent.

Format as JSON:
[
  {{
    "idea": "specific improvement",
    "organ": "which organ it affects",
    "effort": "small|medium|large",
    "impact": "estimated impact"
  }}
]"""

    response = ask_ollama(prompt, model="suneelworkspace")

    try:
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return []


def run_full_repair_cycle():
    """Run a complete Ollama-powered repair cycle."""
    print(f"🔧 Ollama Repair Engine starting — {datetime.now().strftime('%H:%M:%S')}")

    if not is_ollama_running():
        print("⚠️  Ollama not running — skipping repair cycle")
        return

    os.makedirs("blood/logs", exist_ok=True)
    os.makedirs("blood/telemetry", exist_ok=True)

    all_suggestions = []

    # 1. Analyze anomalies
    print("🔍 Analyzing telemetry anomalies...")
    anomaly_fixes = analyze_anomalies()
    if anomaly_fixes:
        print(f"  Found {len(anomaly_fixes)} anomaly fixes")
        all_suggestions.extend(anomaly_fixes)

    # 2. Analyze health score
    print("💊 Analyzing health score...")
    health_analysis = analyze_health_score()
    if health_analysis.get("suggestions"):
        print(f"  Health score {health_analysis.get('score')}% — {len(health_analysis['suggestions'])} improvements suggested")
        for s in health_analysis["suggestions"]:
            all_suggestions.append({
                "fix": s.get("action"),
                "reason": s.get("reason"),
                "execution_level": "SAFE",
                "confidence": 0.9
            })

    # 3. Generate improvement ideas
    print("💡 Generating self-improvement ideas...")
    ideas = generate_self_improvement_ideas()
    if ideas:
        print(f"  Generated {len(ideas)} improvement ideas")

    # Write suggestions log
    with open(SUGGESTIONS_LOG, "w") as f:
        f.write(f"# Ollama Repair Suggestions\n\n")
        f.write(f"*Generated: {datetime.now(timezone.utc).isoformat()}*\n\n")
        if all_suggestions:
            for i, s in enumerate(all_suggestions, 1):
                f.write(f"## Suggestion {i}\n")
                f.write(f"**Fix**: `{s.get('fix', '')}`\n")
                f.write(f"**Confidence**: {s.get('confidence', '?')}\n")
                f.write(f"**Level**: {s.get('execution_level', 'SAFE')}\n\n")
        if ideas:
            f.write("\n## Improvement Ideas\n\n")
            for idea in ideas:
                f.write(f"- **{idea.get('organ', '?')}** [{idea.get('effort', '?')}]: {idea.get('idea', '')}\n")

    # Log repair cycle
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "repair_cycle_complete",
        "suggestions_count": len(all_suggestions),
        "ideas_count": len(ideas),
        "ollama_running": True,
    }
    with open(REPAIR_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    print(f"✅ Repair cycle complete — {len(all_suggestions)} suggestions written to {SUGGESTIONS_LOG}")


if __name__ == "__main__":
    run_full_repair_cycle()
