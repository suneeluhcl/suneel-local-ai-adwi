"""
autonomous_repair_loop.py
1. Run all tests
2. Analyze failures with Ollama
3. Apply SAFE fixes
4. Queue CONTROLLED fixes
5. Re-run tests
6. Learn from results
7. Repeat until pass rate >= 95% or max iterations reached
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

WORKSPACE = os.path.expanduser("~/SuneelWorkSpace")
sys.path.insert(0, WORKSPACE)
os.chdir(WORKSPACE)

OLLAMA_BASE = "http://localhost:11434"
LOOP_LOG = "blood/logs/repair_loop.jsonl"
MAX_ITERATIONS = 5
TARGET_PASS_RATE = 0.95


def ask_ollama(prompt: str, model: str = "suneelworkspace", timeout: int = 120) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 4096}
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


def run_tests() -> dict:
    from tests.test_runner import run_all_tests
    return run_all_tests(verbose=False, fix_on_fail=False)


def analyze_failures_with_ollama(failures: list) -> list:
    if not failures:
        return []
    failure_text = "\n".join([
        f"Test: {f['test']}\nError: {f['message']}"
        for f in failures[:10]
    ])
    prompt = f"""Analyze these SuneelWorkSpace test failures and suggest SAFE fixes.

SuneelWorkSpace: 12 organs (brain, heart, eyes, ears, nervous, skeleton, blood, hands, mouth, dna, lab, spine)

Failures:
{failure_text}

For each failure, provide a specific fix. Respond ONLY in JSON array:
[
  {{
    "test": "test name",
    "root_cause": "why it failed",
    "fix_type": "create_dir|create_file|fix_symlink|skip",
    "target_path": "relative/path",
    "fix_command": "content or target for symlink",
    "execution_level": "SAFE",
    "confidence": 0.85
  }}
]"""

    response = ask_ollama(prompt)
    if not response:
        return []
    try:
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return []


def apply_fix(fix: dict) -> bool:
    if fix.get("execution_level") != "SAFE":
        return False
    if fix.get("confidence", 0) < 0.7:
        return False

    fix_type = fix.get("fix_type", "skip")
    target = fix.get("target_path", "")
    command = fix.get("fix_command", "")

    try:
        if fix_type == "create_dir" and target:
            full = os.path.join(WORKSPACE, target)
            os.makedirs(full, exist_ok=True)
            print(f"    Created dir: {target}")
            return True

        elif fix_type == "create_file" and target and command:
            full = os.path.join(WORKSPACE, target)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(command)
            print(f"    Created file: {target}")
            return True

        elif fix_type == "fix_symlink" and target and command:
            link_path = os.path.join(WORKSPACE, "hands/bin", target)
            if os.path.islink(link_path):
                os.unlink(link_path)
            os.symlink(command, link_path)
            os.chmod(link_path, 0o755)
            print(f"    Fixed symlink: {target}")
            return True

    except Exception as e:
        print(f"    Fix failed: {e}")

    return False


def learn_from_results(iteration: int, results: dict, fixes_applied: int):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "iteration": iteration,
        "passed": results.get("passed", 0),
        "failed": results.get("failed", 0),
        "total": results.get("total", 0),
        "fixes_applied": fixes_applied,
        "pass_rate": results.get("passed", 0) / max(results.get("total", 1), 1),
    }
    os.makedirs(os.path.dirname(LOOP_LOG), exist_ok=True)
    with open(LOOP_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    try:
        from nervous.nerve_propagator import notify_change
        notify_change("lab", "repair_loop_iteration",
                      f"iteration={iteration} passed={results.get('passed',0)}/{results.get('total',0)}")
    except Exception:
        pass


def run_autonomous_repair_loop(max_iterations: int = MAX_ITERATIONS):
    print(f"\nAutonomous Repair Loop")
    print(f"   Max iterations: {max_iterations} | Target: {TARGET_PASS_RATE*100:.0f}%\n")

    iteration = 0
    best_pass_rate = 0.0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n{'─'*50}")
        print(f"Iteration {iteration}/{max_iterations}")
        print(f"{'─'*50}")

        results = run_tests()
        passed = results.get("passed", 0)
        total = results.get("total", 0)
        pass_rate = passed / max(total, 1)
        print(f"   {passed}/{total} passing ({pass_rate*100:.1f}%)")

        if pass_rate > best_pass_rate:
            best_pass_rate = pass_rate

        if pass_rate >= TARGET_PASS_RATE:
            print(f"\nTarget reached: {pass_rate*100:.1f}%")
            learn_from_results(iteration, results, 0)
            break

        failures = results.get("failures", [])
        if not failures:
            learn_from_results(iteration, results, 0)
            break

        print(f"\nAnalyzing {len(failures)} failures with Ollama...")
        fixes = analyze_failures_with_ollama(failures)
        print(f"   {len(fixes)} potential fixes generated")

        fixes_applied = 0
        for fix in fixes:
            if fix.get("execution_level") == "SAFE" and fix.get("confidence", 0) >= 0.7:
                print(f"  Applying: {fix.get('root_cause', '')[:60]}")
                if apply_fix(fix):
                    fixes_applied += 1

        print(f"\n   Applied {fixes_applied} fixes")
        learn_from_results(iteration, results, fixes_applied)

        if fixes_applied == 0:
            print("   No more SAFE fixes available")
            break

        time.sleep(2)

    print(f"\n{'='*50}")
    print(f"Repair Loop Complete")
    print(f"   Iterations: {iteration} | Best pass rate: {best_pass_rate*100:.1f}%")
    print(f"{'='*50}\n")
    return {"iterations": iteration, "best_pass_rate": best_pass_rate}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS)
    args = parser.parse_args()
    run_autonomous_repair_loop(max_iterations=args.max_iterations)
