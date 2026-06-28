#!/usr/bin/env python3
"""
deep_scan_engine.py
Uses local Ollama to scan every file in every organ.
Finds gaps, broken connections, missing wiring, and improvement opportunities.
Outputs structured findings for Claude to implement.
Runs entirely locally — no API costs.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

WORKSPACE = os.path.expanduser("~/SuneelWorkSpace")
OLLAMA_BASE = "http://localhost:11434"
FINDINGS_PATH = f"{WORKSPACE}/blood/logs/night_operations/deep_scan_findings.json"
REPORT_PATH = f"{WORKSPACE}/blood/logs/night_operations/deep_scan_report.md"

ORGANS = [
    "brain", "heart", "eyes", "ears", "nervous",
    "skeleton", "blood", "hands", "mouth", "dna", "lab", "spine"
]

SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env",
    "node_modules", "chroma_store", "spine/backups",
    "brain/vault", ".agent-backups", "nerve_inbox"
}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".db", ".sqlite", ".log",
    ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".zip", ".tar", ".gz", ".bin", ".pkl"
}


def ask_ollama(prompt: str, model: str = "suneelworkspace", timeout: int = 180) -> str:
    """Send prompt to local Ollama. Returns response or empty string on failure."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
            "top_p": 0.9,
        }
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
        print(f"  ⚠️ Ollama error: {e}")
        return ""


def get_organ_files(organ: str) -> list:
    """Get all scannable files in an organ."""
    organ_path = os.path.join(WORKSPACE, organ)
    if not os.path.exists(organ_path):
        return []

    files = []
    for root, dirs, filenames in os.walk(organ_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

        rel_root = os.path.relpath(root, WORKSPACE)
        if any(skip in rel_root for skip in SKIP_DIRS):
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in SKIP_EXTENSIONS:
                continue
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, WORKSPACE)
            files.append(rel_path)

    return sorted(files)


def read_file_safe(filepath: str, max_chars: int = 3000) -> str:
    """Read a file safely, truncating if too large."""
    full_path = os.path.join(WORKSPACE, filepath)
    try:
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            content = f.read(max_chars)
        if len(content) == max_chars:
            content += "\n... [truncated]"
        return content
    except Exception:
        return ""


def scan_organ(organ: str) -> dict:
    """Deep scan a single organ using Ollama."""
    print(f"\n🔍 Scanning {organ}/...")
    files = get_organ_files(organ)
    print(f"  Found {len(files)} files")

    if not files:
        return {
            "organ": organ,
            "status": "empty",
            "files_scanned": 0,
            "gaps": [],
            "enhancements": [],
            "broken_connections": [],
            "missing_wiring": [],
        }

    nerve_path = os.path.join(WORKSPACE, organ, "nerve.json")
    nerve_content = ""
    if os.path.exists(nerve_path):
        nerve_content = read_file_safe(f"{organ}/nerve.json")
    else:
        nerve_content = "MISSING — nerve.json does not exist for this organ"

    file_inventory = "\n".join([f"  - {f}" for f in files[:50]])
    if len(files) > 50:
        file_inventory += f"\n  ... and {len(files) - 50} more files"

    py_files = [f for f in files if f.endswith(".py")][:5]
    key_file_contents = ""
    for pf in py_files:
        content = read_file_safe(pf, max_chars=800)
        if content:
            key_file_contents += f"\n### {pf}\n```python\n{content}\n```\n"

    json_files = [f for f in files if f.endswith(".json") and "nerve" not in f][:3]
    for jf in json_files:
        content = read_file_safe(jf, max_chars=500)
        if content:
            key_file_contents += f"\n### {jf}\n```json\n{content}\n```\n"

    prompt = f"""You are analyzing the '{organ}' organ of SuneelWorkSpace.

SuneelWorkSpace is organized as a Human Body Architecture with 12 organs:
brain, heart, eyes, ears, nervous, skeleton, blood, hands, mouth, dna, lab, spine

Each organ has:
- nerve.json: declares what it provides, needs, watches, and notifies
- nerve_inbox/: receives change notifications from other organs
- README.md: documents the organ
- CLI commands in hands/bin/ pointing into this organ

NERVE.JSON for {organ}/:
{nerve_content}

FILES IN {organ}/:
{file_inventory}

KEY FILE CONTENTS:
{key_file_contents}

Analyze this organ and find:
1. GAPS: Missing files, missing nerve.json entries, missing CLI commands, missing README
2. BROKEN_CONNECTIONS: nerve.json references paths that don't exist, broken imports
3. ENHANCEMENTS: Specific improvements that would make this organ work better
4. MISSING_WIRING: Things that should be connected to other organs but aren't

Respond in this EXACT JSON format (no other text):
{{
  "gaps": [
    {{
      "type": "missing_file|missing_nerve_entry|missing_cli|missing_readme|broken_import",
      "description": "specific description",
      "file_path": "exact path",
      "fix": "exact fix to apply",
      "severity": "critical|high|medium|low",
      "execution_level": "SAFE|CONTROLLED"
    }}
  ],
  "broken_connections": [
    {{
      "type": "broken_path|broken_import|missing_dependency",
      "description": "what is broken",
      "location": "file where broken",
      "fix": "how to fix it",
      "severity": "critical|high|medium|low"
    }}
  ],
  "enhancements": [
    {{
      "description": "specific enhancement",
      "organ": "{organ}",
      "effort": "small|medium|large",
      "impact": "high|medium|low",
      "implementation": "how to implement"
    }}
  ],
  "missing_wiring": [
    {{
      "description": "what should be connected",
      "from_organ": "{organ}",
      "to_organ": "target organ",
      "connection_type": "nerve|mcp|import|cli",
      "fix": "how to wire it"
    }}
  ],
  "summary": "one sentence summary of organ health"
}}"""

    print(f"  🤖 Asking Ollama to analyze {organ}...")
    response = ask_ollama(prompt, model="suneelworkspace")

    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            result = json.loads(match.group())
            result["organ"] = organ
            result["files_scanned"] = len(files)
            result["nerve_json_exists"] = os.path.exists(nerve_path)
            result["readme_exists"] = os.path.exists(os.path.join(WORKSPACE, organ, "README.md"))

            gap_count = len(result.get("gaps", []))
            broken_count = len(result.get("broken_connections", []))
            enhance_count = len(result.get("enhancements", []))
            print(f"  ✅ {organ}: {gap_count} gaps, {broken_count} broken, {enhance_count} enhancements")
            print(f"     Summary: {result.get('summary', 'no summary')}")
            return result
    except Exception as e:
        print(f"  ⚠️ Could not parse Ollama response for {organ}: {e}")

    return {
        "organ": organ,
        "files_scanned": len(files),
        "gaps": [],
        "broken_connections": [],
        "enhancements": [],
        "missing_wiring": [],
        "summary": "scan incomplete",
        "nerve_json_exists": os.path.exists(nerve_path),
        "readme_exists": os.path.exists(os.path.join(WORKSPACE, organ, "README.md")),
    }


def scan_nerve_connections() -> dict:
    """Scan all nerve connections across all organs for consistency."""
    print("\n🫀 Scanning nerve system connections...")

    registry_path = os.path.join(WORKSPACE, "nervous/nerve_registry.json")
    if not os.path.exists(registry_path):
        return {"error": "nerve_registry.json not found"}

    registry = json.load(open(registry_path))
    organs_config = registry.get("organs", {})

    broken = []
    missing = []

    for organ, config in organs_config.items():
        for key, path in config.get("provides", {}).items():
            if isinstance(path, str):
                full_path = os.path.join(WORKSPACE, path)
                if not os.path.exists(full_path):
                    broken.append({
                        "organ": organ,
                        "type": "broken_provides",
                        "key": key,
                        "path": path,
                        "fix": f"Create {path} or update nerve_registry.json"
                    })

        for key, path in config.get("needs", {}).items():
            if isinstance(path, str):
                full_path = os.path.join(WORKSPACE, path)
                if not os.path.exists(full_path):
                    missing.append({
                        "organ": organ,
                        "type": "missing_dependency",
                        "key": key,
                        "path": path,
                        "fix": f"Create {path} or update nerve_registry.json"
                    })

        organ_path = os.path.join(WORKSPACE, config.get("path", organ + "/"))
        if not os.path.exists(organ_path):
            broken.append({
                "organ": organ,
                "type": "organ_path_missing",
                "path": config.get("path"),
                "fix": f"Create directory {config.get('path')}"
            })

    print(f"  Found {len(broken)} broken connections, {len(missing)} missing dependencies")
    return {"broken": broken, "missing": missing}


def scan_symlinks() -> list:
    """Scan all symlinks in hands/bin/ for broken links."""
    print("\n🦾 Scanning hands/bin/ symlinks...")
    bin_path = os.path.join(WORKSPACE, "hands/bin")
    if not os.path.exists(bin_path):
        return [{"error": "hands/bin/ not found"}]

    broken = []
    valid = []
    for cmd in os.listdir(bin_path):
        link_path = os.path.join(bin_path, cmd)
        if os.path.islink(link_path):
            # os.path.exists follows symlinks — correct for broken link detection
            if not os.path.exists(link_path):
                target = os.readlink(link_path)
                broken.append({
                    "command": cmd,
                    "broken_target": target,
                    "fix": f"Find correct target and recreate: ln -sf <correct_path> hands/bin/{cmd}"
                })
            else:
                valid.append(cmd)

    print(f"  Valid: {len(valid)}, Broken: {len(broken)}")
    return broken


def scan_import_paths() -> list:
    """Scan all Python files for old-style import paths."""
    print("\n🐍 Scanning Python import paths...")
    old_patterns = [
        ("from agent_system", "from brain/heart/blood/spine (check which organ)"),
        ("from orchestrator", "from heart.orchestrator"),
        ("from identity", "from dna.identity"),
        ("from autolab", "from lab.autolab"),
        ("from evolution", "from lab.evolution"),
        ("from dashboard", "from eyes.dashboard"),
        ("from visual", "from eyes.visual"),
        ("from monitor", "from ears.monitor"),
        ("from dispatcher", "from mouth.dispatcher"),
        ("from comms", "from mouth.comms"),
        ("import orchestrator", "import heart.orchestrator"),
        ("import autolab", "import lab.autolab"),
    ]

    issues = []
    for root, dirs, files in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        rel_root = os.path.relpath(root, WORKSPACE)
        if any(skip in rel_root for skip in SKIP_DIRS):
            continue

        for filename in files:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, WORKSPACE)
            # Skip self — pattern strings in this file match their own definitions
            if rel_path == "lab/autolab/deep_scan_engine.py":
                continue

            try:
                content = open(filepath, encoding="utf-8", errors="ignore").read()
                for old_pattern, suggestion in old_patterns:
                    if old_pattern in content:
                        issues.append({
                            "file": rel_path,
                            "old_pattern": old_pattern,
                            "suggestion": suggestion,
                            "fix": f"Update import in {rel_path}"
                        })
            except Exception:
                pass

    print(f"  Found {len(issues)} old-style imports")
    return issues


def generate_master_report(organ_findings: list, nerve_findings: dict,
                           broken_symlinks: list, import_issues: list) -> str:
    """Generate a comprehensive report for Claude to act on."""
    total_gaps = sum(len(f.get("gaps", [])) for f in organ_findings)
    total_broken = sum(len(f.get("broken_connections", [])) for f in organ_findings)
    total_enhancements = sum(len(f.get("enhancements", [])) for f in organ_findings)
    total_wiring = sum(len(f.get("missing_wiring", [])) for f in organ_findings)

    report = f"""# 🌙 Deep Scan Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}

## SUMMARY
- **Organs scanned:** {len(organ_findings)}
- **Total gaps found:** {total_gaps}
- **Total broken connections:** {total_broken}
- **Total enhancements identified:** {total_enhancements}
- **Missing nerve wiring:** {total_wiring}
- **Broken symlinks:** {len(broken_symlinks)}
- **Old import paths:** {len(import_issues)}
- **Broken nerve paths:** {len(nerve_findings.get('broken', []))}

---

## ORGAN-BY-ORGAN FINDINGS

"""
    for finding in organ_findings:
        organ = finding.get("organ", "?")
        nerve_ok = "✅" if finding.get("nerve_json_exists") else "❌"
        readme_ok = "✅" if finding.get("readme_exists") else "❌"
        summary = finding.get("summary", "no summary")

        report += f"### {organ}/\n"
        report += f"nerve.json: {nerve_ok} | README.md: {readme_ok} | "
        report += f"Files: {finding.get('files_scanned', 0)}\n"
        report += f"*{summary}*\n\n"

        gaps = finding.get("gaps", [])
        if gaps:
            report += f"**Gaps ({len(gaps)}):**\n"
            for g in gaps:
                sev = g.get("severity", "?")
                report += f"- [{sev.upper()}] {g.get('description', '')} → `{g.get('fix', '')}`\n"
            report += "\n"

        broken = finding.get("broken_connections", [])
        if broken:
            report += f"**Broken Connections ({len(broken)}):**\n"
            for b in broken:
                report += f"- {b.get('description', '')} in `{b.get('location', '')}` → {b.get('fix', '')}\n"
            report += "\n"

        wiring = finding.get("missing_wiring", [])
        if wiring:
            report += f"**Missing Wiring ({len(wiring)}):**\n"
            for w in wiring:
                report += f"- {w.get('description', '')} ({w.get('from_organ', '')} → {w.get('to_organ', '')})\n"
            report += "\n"

        enhancements = finding.get("enhancements", [])
        if enhancements:
            report += f"**Enhancements ({len(enhancements)}):**\n"
            for e in enhancements[:3]:
                report += f"- [{e.get('impact', '?').upper()}] {e.get('description', '')}\n"
            report += "\n"

    report += "---\n\n## NERVE SYSTEM ISSUES\n\n"
    for b in nerve_findings.get("broken", [])[:10]:
        report += f"- ❌ {b['organ']}.provides.{b.get('key','?')}: `{b['path']}` missing → {b['fix']}\n"

    report += "\n---\n\n## BROKEN SYMLINKS\n\n"
    for s in broken_symlinks:
        report += f"- ❌ `hands/bin/{s['command']}` → `{s['broken_target']}` (broken)\n"

    report += "\n---\n\n## OLD IMPORT PATHS\n\n"
    for i in import_issues[:20]:
        report += f"- `{i['file']}`: `{i['old_pattern']}` → should be `{i['suggestion']}`\n"

    return report


def run_deep_scan():
    """Run the complete deep scan."""
    print("🌙 Deep Scan Engine starting...")
    print(f"   Workspace: {WORKSPACE}")
    print(f"   Time: {datetime.now().strftime('%H:%M:%S')}\n")

    os.makedirs(os.path.join(WORKSPACE, "blood/logs/night_operations"), exist_ok=True)

    all_findings = []

    for organ in ORGANS:
        finding = scan_organ(organ)
        all_findings.append(finding)
        time.sleep(2)

    nerve_findings = scan_nerve_connections()
    broken_symlinks = scan_symlinks()
    import_issues = scan_import_paths()

    all_data = {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "organ_findings": all_findings,
        "nerve_findings": nerve_findings,
        "broken_symlinks": broken_symlinks,
        "import_issues": import_issues,
    }
    with open(FINDINGS_PATH, "w") as f:
        json.dump(all_data, f, indent=2)
    print(f"\n✅ Raw findings saved: {FINDINGS_PATH}")

    report = generate_master_report(all_findings, nerve_findings, broken_symlinks, import_issues)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    print(f"✅ Report saved: {REPORT_PATH}")

    total_issues = (
        sum(len(f.get("gaps", [])) for f in all_findings) +
        sum(len(f.get("broken_connections", [])) for f in all_findings) +
        len(broken_symlinks) +
        len(nerve_findings.get("broken", []))
    )
    print(f"\n🎯 SCAN COMPLETE — {total_issues} total issues found")
    print(f"   Report: {REPORT_PATH}")
    print(f"   Findings: {FINDINGS_PATH}")

    return all_data


if __name__ == "__main__":
    run_deep_scan()
