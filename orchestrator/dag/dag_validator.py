#!/usr/bin/env python3
"""P3.5 — Validate a pipeline YAML: deps, cycles, variable refs, commands, execution levels."""

import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

BIN_DIR = Path(__file__).parent.parent.parent / "bin"
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
VALID_LEVELS = {"SAFE", "CONTROLLED", "RESTRICTED"}
VAR_RE = re.compile(r"\{\{\s*(\w+)\.(\S+?)\s*\}\}")


def _command_exists(cmd: str) -> bool:
    """Check if command exists in bin/ or scripts/ (strips any leading path)."""
    name = Path(cmd).name
    return (BIN_DIR / name).exists() or (SCRIPTS_DIR / name).exists()


def validate(path: str) -> tuple[bool, list[str]]:
    if yaml is None:
        return False, ["pyyaml not installed — run: pip install pyyaml"]
    errors: list[str] = []

    try:
        pipeline = yaml.safe_load(Path(path).read_text())
    except Exception as e:
        return False, [f"YAML parse error: {e}"]

    if not isinstance(pipeline, dict):
        return False, ["Pipeline must be a YAML mapping"]

    steps = pipeline.get("steps", [])
    if not steps:
        errors.append("Pipeline has no steps")

    inputs = {i["name"] for i in pipeline.get("inputs", []) if isinstance(i, dict) and "name" in i}
    step_ids = {s["id"] for s in steps if isinstance(s, dict) and "id" in s}
    step_outputs: dict[str, set[str]] = {}
    for s in steps:
        if isinstance(s, dict):
            step_outputs[s.get("id", "")] = {
                o["name"] for o in s.get("outputs", []) if isinstance(o, dict) and "name" in o
            }

    # Topological sort to detect cycles
    deps: dict[str, list[str]] = {
        s["id"]: s.get("depends_on", []) for s in steps if isinstance(s, dict) and "id" in s
    }

    def _has_cycle() -> bool:
        visited: set[str] = set()
        path_set: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            path_set.add(node)
            for nb in deps.get(node, []):
                if nb not in visited:
                    if dfs(nb):
                        return True
                elif nb in path_set:
                    return True
            path_set.discard(node)
            return False

        return any(dfs(n) for n in deps if n not in visited)

    for s in steps:
        if not isinstance(s, dict):
            continue
        sid = s.get("id", "?")

        # depends_on references exist
        for dep in s.get("depends_on", []):
            if dep not in step_ids:
                errors.append(f"Step '{sid}': depends_on '{dep}' not found")

        # Execution level valid
        level = s.get("execution_level", "SAFE")
        if level not in VALID_LEVELS:
            errors.append(f"Step '{sid}': invalid execution_level '{level}'")

        # Command exists
        cmd = s.get("command", "")
        if cmd and not _command_exists(cmd):
            errors.append(f"Step '{sid}': command '{cmd}' not found in bin/ or scripts/")

        # Variable references valid
        for arg in s.get("args", []) + [s.get("condition", "")]:
            for ns, ref in VAR_RE.findall(str(arg)):
                if ns == "inputs" and ref not in inputs:
                    errors.append(f"Step '{sid}': references undefined input '{{{{ inputs.{ref} }}}}'")
                elif ns == "steps":
                    parts = ref.split(".")
                    ref_step = parts[0]
                    ref_out = parts[2] if len(parts) > 2 else ""
                    if ref_step not in step_ids:
                        errors.append(f"Step '{sid}': references unknown step '{ref_step}'")
                    elif ref_out and ref_out not in step_outputs.get(ref_step, set()):
                        errors.append(f"Step '{sid}': step '{ref_step}' has no output '{ref_out}'")

    if _has_cycle():
        errors.append("Circular dependency detected in DAG")

    return len(errors) == 0, errors


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: dag-validate <pipeline.yaml>")
        sys.exit(1)
    ok, errors = validate(sys.argv[1])
    if ok:
        pipeline = yaml.safe_load(Path(sys.argv[1]).read_text())
        steps = pipeline.get("steps", [])
        print(f"PASS — {len(steps)} steps validated: {sys.argv[1]}")
    else:
        print(f"FAIL — {len(errors)} error(s):")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
