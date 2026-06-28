"""
experiment_skill_generator.py
After each autolab experiment completes, generates a Hermes skill document
capturing what was learned. Wires lab/ learning into dna/agents/hermes/skills/.
"""

import json
import os
import glob
import urllib.request
from datetime import datetime, timezone

COMPLETED_DIR = "lab/autolab/experiments/completed"
SKILLS_DIR = "dna/agents/hermes/skills"
OLLAMA_BASE = "http://localhost:11434"
GENERATOR_LOG = "blood/logs/experiment_skills.jsonl"


def ask_ollama(prompt: str, model: str = "suneelworkspace", timeout: int = 120) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": 4096}
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


def generate_skill_from_experiment(experiment: dict) -> str:
    """Generate a Hermes skill document from a completed experiment."""
    name = experiment.get("name", "Unknown Experiment")
    hypothesis = experiment.get("hypothesis", "")
    baseline = experiment.get("baseline_value")
    result = experiment.get("result_value")
    delta = experiment.get("score_delta")
    actions = experiment.get("actions", [])
    source = experiment.get("source", "autolab")

    action_descriptions = "\n".join([
        f"- {a.get('description', a.get('command', '?'))}"
        for a in actions
    ])

    outcome = "improved" if (delta and delta > 0) else "no improvement" if delta == 0 else "regressed"

    prompt = f"""Create a Hermes skill document from this autolab experiment result.

Experiment: {name}
Hypothesis: {hypothesis}
Actions taken:
{action_descriptions}
Baseline: {baseline}
Result: {result}
Score delta: {delta} ({outcome})
Source: {source}

Write a skill document that captures:
1. What was learned from this experiment
2. When to apply this knowledge in the future
3. What to do (or avoid) based on the result
4. How this affects SuneelWorkSpace's 12-organ architecture

Format as a useful Markdown skill document that Hermes can reference."""

    return ask_ollama(prompt)


def process_new_experiments():
    """Process all completed experiments that don't have skill documents yet."""
    if not os.path.exists(COMPLETED_DIR):
        print(f"No completed experiments directory: {COMPLETED_DIR}")
        return 0

    os.makedirs(SKILLS_DIR, exist_ok=True)

    # Get already processed experiments
    processed = set()
    if os.path.exists(GENERATOR_LOG):
        with open(GENERATOR_LOG) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    processed.add(entry.get("experiment_id", ""))
                except Exception:
                    pass

    # Process new completed experiments
    new_skills = 0
    for exp_file in glob.glob(os.path.join(COMPLETED_DIR, "*.json")):
        try:
            exp = json.load(open(exp_file))
            exp_id = exp.get("experiment_id", os.path.basename(exp_file))

            if exp_id in processed:
                continue

            # Only process experiments with results
            if exp.get("result_value") is None and exp.get("score_delta") is None:
                continue

            print(f"  Generating skill for: {exp.get('name', exp_id)}")
            skill_content = generate_skill_from_experiment(exp)

            if skill_content:
                # Save skill document
                skill_name = exp_id.replace("/", "_").replace(" ", "_")
                skill_path = os.path.join(SKILLS_DIR, f"experiment_{skill_name}.md")
                with open(skill_path, "w") as f:
                    f.write(f"# Experiment Skill: {exp.get('name', exp_id)}\n\n")
                    f.write(f"*Generated: {datetime.now(timezone.utc).isoformat()}*\n\n")
                    f.write(skill_content)

                # Log as processed
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "experiment_id": exp_id,
                    "experiment_name": exp.get("name", "?"),
                    "skill_path": skill_path,
                    "score_delta": exp.get("score_delta"),
                }
                with open(GENERATOR_LOG, "a") as f:
                    f.write(json.dumps(entry) + "\n")

                new_skills += 1
                print(f"  Skill saved: {skill_path}")

        except Exception as e:
            print(f"  Error processing {exp_file}: {e}")

    print(f"\nGenerated {new_skills} new skill documents")
    return new_skills


if __name__ == "__main__":
    print("Experiment Skill Generator")
    process_new_experiments()
