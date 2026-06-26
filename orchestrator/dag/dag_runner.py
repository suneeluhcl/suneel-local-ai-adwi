#!/usr/bin/env python3
"""P3.5 — Run a pipeline YAML: topological sort, execution gates, template substitution."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

from dag_validator import validate

RUNS_DIR = Path(__file__).parent / "runs"
BIN_DIR = Path(__file__).parent.parent.parent / "bin"
VAR_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")


def _topo_sort(steps: list[dict]) -> list[dict]:
    """Kahn's algorithm — raises on cycle (validator should catch first)."""
    ids = {s["id"]: s for s in steps}
    in_degree: dict[str, int] = {s["id"]: 0 for s in steps}
    for s in steps:
        for dep in s.get("depends_on", []):
            in_degree[s["id"]] = in_degree.get(s["id"], 0) + 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(ids[nid])
        for s in steps:
            if nid in s.get("depends_on", []):
                in_degree[s["id"]] -= 1
                if in_degree[s["id"]] == 0:
                    queue.append(s["id"])

    if len(order) != len(steps):
        raise RuntimeError("Circular dependency — cannot sort")
    return order


def _resolve(template: str, inputs: dict, step_outputs: dict) -> str:
    def replace(m: re.Match) -> str:
        expr = m.group(1)
        parts = expr.split(".")
        if parts[0] == "inputs" and len(parts) >= 2:
            return str(inputs.get(parts[1], m.group(0)))
        if parts[0] == "steps" and len(parts) >= 4:
            # steps.<id>.outputs.<name>
            return str(step_outputs.get(parts[1], {}).get(parts[3], m.group(0)))
        if parts[0] == "env" and len(parts) >= 2:
            return os.environ.get(parts[1], m.group(0))
        if expr == "date":
            return datetime.now().strftime("%Y-%m-%d")
        return m.group(0)
    return VAR_RE.sub(replace, template)


_COND_RE = re.compile(
    r"""^\s*(['"]?)(.+?)\1\s*(==|!=|in|not in)\s*(['"]?)(.+?)\4\s*$"""
)


def _eval_condition(condition: str, inputs: dict, step_outputs: dict) -> bool:
    """Safe condition evaluator — supports == != in not-in only. No eval()."""
    resolved = _resolve(condition, inputs, step_outputs).strip()
    m = _COND_RE.match(resolved)
    if not m:
        return True  # unparseable condition → run step
    lhs, op, rhs = m.group(2).strip(), m.group(3).strip(), m.group(5).strip()
    if op == "==":
        return lhs == rhs
    if op == "!=":
        return lhs != rhs
    if op == "in":
        return lhs in rhs
    if op == "not in":
        return lhs not in rhs
    return True


def _extract_output(stdout: str, definition: dict) -> str:
    src = definition.get("from", "stdout_last_line")
    if src == "stdout_last_line":
        lines = [l for l in stdout.splitlines() if l.strip()]
        return lines[-1].strip() if lines else ""
    if src == "stdout":
        return stdout.strip()
    return ""


def run(pipeline_path: str, inputs: dict | None = None, dry_run: bool = False) -> dict:
    inputs = inputs or {}
    ok, errors = validate(pipeline_path)
    if not ok:
        print(f"Pipeline invalid — aborting:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)

    pipeline = yaml.safe_load(Path(pipeline_path).read_text())
    steps = _topo_sort(pipeline.get("steps", []))
    name = pipeline.get("name", Path(pipeline_path).stem)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    run_record: dict = {
        "pipeline": name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "inputs": inputs,
        "steps": {},
    }
    step_outputs: dict[str, dict] = {}
    stats = {"completed": 0, "skipped": 0, "failed": 0}

    for step in steps:
        sid = step["id"]
        sname = step.get("name", sid)
        level = step.get("execution_level", "SAFE")
        cmd = step.get("command", "")
        args = [_resolve(str(a), inputs, step_outputs) for a in step.get("args", [])]
        condition = step.get("condition", "")

        print(f"\n── Step: {sname} [{level}]")

        # Check dependencies succeeded (dry-run steps count as succeeded)
        dep_failed = False
        for dep in step.get("depends_on", []):
            dep_status = run_record["steps"].get(dep, {}).get("status")
            if dep_status not in ("success", "dry-run"):
                print(f"   SKIP — dependency '{dep}' did not succeed")
                run_record["steps"][sid] = {"status": "skipped", "reason": f"dep {dep} failed"}
                stats["skipped"] += 1
                dep_failed = True
                break
        if dep_failed:
            continue

        # Evaluate condition
        if condition and not _eval_condition(condition, inputs, step_outputs):
            print(f"   SKIP — condition false: {condition}")
            run_record["steps"][sid] = {"status": "skipped", "reason": "condition false"}
            stats["skipped"] += 1
            continue

        full_cmd = [str(BIN_DIR / cmd)] + args if (BIN_DIR / cmd).exists() else [cmd] + args
        cmd_str = " ".join(full_cmd)

        if level == "CONTROLLED":
            print(f"   Command: {cmd_str}")
            answer = input(f"   Run step '{sname}'? (y/n): ").strip().lower()
            if answer != "y":
                print("   SKIP — user declined")
                run_record["steps"][sid] = {"status": "skipped", "reason": "user declined"}
                stats["skipped"] += 1
                continue

        if level == "RESTRICTED":
            print(f"   Command: {cmd_str}")
            reason = input(f"   Justification for '{sname}': ").strip()
            if not reason:
                print("   SKIP — no justification provided")
                run_record["steps"][sid] = {"status": "skipped", "reason": "no justification"}
                stats["skipped"] += 1
                continue

        if dry_run:
            print(f"   [DRY-RUN] would execute: {cmd_str}")
            run_record["steps"][sid] = {"status": "dry-run", "command": cmd_str}
            continue

        t0 = datetime.now()
        try:
            result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=300)
            duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            success = result.returncode == 0

            # Extract declared outputs
            for out_def in step.get("outputs", []):
                step_outputs.setdefault(sid, {})[out_def["name"]] = _extract_output(stdout, out_def)

            status = "success" if success else "fail"
            run_record["steps"][sid] = {
                "status": status, "duration_ms": duration_ms,
                "returncode": result.returncode,
                "stdout": stdout[:2000], "stderr": stderr[:500],
                "outputs": step_outputs.get(sid, {}),
            }
            stats["completed" if success else "failed"] += 1
            print(f"   {'✓' if success else '✗'} {status} ({duration_ms}ms)")
            if not success:
                print(f"   stderr: {stderr[:200]}")

        except subprocess.TimeoutExpired:
            run_record["steps"][sid] = {"status": "fail", "reason": "timeout"}
            stats["failed"] += 1
            print(f"   ✗ TIMEOUT")
        except Exception as e:
            run_record["steps"][sid] = {"status": "fail", "reason": str(e)}
            stats["failed"] += 1
            print(f"   ✗ ERROR: {e}")

    run_record["finished_at"] = datetime.now(timezone.utc).isoformat()
    run_record["stats"] = stats

    if not dry_run:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        run_file = RUNS_DIR / f"{name}_{ts}.json"
        run_file.write_text(json.dumps(run_record, indent=2))
        print(f"\nRun saved → {run_file}")

    print(f"\nSummary: {stats['completed']} completed, {stats['skipped']} skipped, {stats['failed']} failed")
    return run_record


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run a pipeline YAML")
    parser.add_argument("pipeline", help="Path to pipeline YAML")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()

    inputs = {}
    for kv in args.input:
        if "=" in kv:
            k, _, v = kv.partition("=")
            inputs[k.strip()] = v.strip()

    run(args.pipeline, inputs=inputs, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
