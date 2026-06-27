#!/usr/bin/env python3
"""
Knowledge Indexer — builds brain/system/readme_knowledge_index.json.
Machine-readable index of all folder purposes, capabilities, health scores,
and cross-references. Used by brain subsystems for context-aware search.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

WORKSPACE = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True,
    cwd=os.path.dirname(os.path.abspath(__file__))
).strip())

INDEX_PATH = WORKSPACE / "brain/system/readme_knowledge_index.json"


def _extract_readme_text(readme_path: Path) -> dict:
    """Extract named sections from a README.md file."""
    if not readme_path.exists():
        return {}
    try:
        content = readme_path.read_text(errors="ignore")
    except Exception:
        return {}

    sections = {}
    # Extract title
    title_m = re.match(r"#\s+(.+)", content)
    if title_m:
        sections["title"] = title_m.group(1).strip()

    # Extract key sections by scanning ## headers
    for m in re.finditer(r"##\s+[^\n]*?(Purpose|Responsibilities|Capabilities|Health Score|Critical Issues|System Role|Gaps)\n(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE):
        key = m.group(1).lower().replace(" ", "_")
        text = m.group(2).strip()[:400]
        sections[key] = text

    return sections


def build_knowledge_index() -> dict:
    from hands.automation.readme.intelligence_engine import analyze_workspace
    from hands.automation.readme.cache_manager import load_cache, get_cached_score

    analyses = analyze_workspace()
    cache = load_cache()

    index = {
        "generated": datetime.now().isoformat(),
        "workspace": str(WORKSPACE),
        "folder_count": len(analyses),
        "folders": {},
    }

    for analysis in analyses:
        path_str = analysis["path"]
        folder_path = WORKSPACE / path_str
        readme_path = folder_path / "README.md"

        readme_sections = _extract_readme_text(readme_path)
        cached_score = get_cached_score(str(folder_path), cache)

        index["folders"][path_str] = {
            "name": analysis.get("name", ""),
            "organ": analysis.get("organ"),
            "purpose": analysis.get("purpose", ""),
            "capabilities": analysis.get("capabilities", []),
            "workspace_references": analysis.get("workspace_references", []),
            "file_count": analysis.get("file_count", 0),
            "has_readme": readme_path.exists(),
            "health_score": cached_score if cached_score >= 0 else None,
            "gaps": analysis.get("gaps", []),
            "readme_sections": readme_sections,
        }

    return index


def write_index() -> None:
    index = build_knowledge_index()
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_PATH.with_suffix(".tmp.json")
    tmp.write_text(json.dumps(index, indent=2))
    tmp.rename(INDEX_PATH)
    total = len(index["folders"])
    with_readme = sum(1 for v in index["folders"].values() if v["has_readme"])
    print(f"✅ Knowledge index: {total} folders ({with_readme} with README) → {INDEX_PATH.relative_to(WORKSPACE)}")


def query_index(query: str, top_k: int = 5) -> list:
    """Simple keyword relevance search over the index."""
    if not INDEX_PATH.exists():
        write_index()
    index = json.loads(INDEX_PATH.read_text())
    query_words = query.lower().split()

    scored = []
    for path, entry in index["folders"].items():
        text = " ".join(filter(None, [
            entry.get("purpose", ""),
            " ".join(entry.get("capabilities", [])),
            entry.get("name", ""),
            " ".join(str(v) for v in entry.get("readme_sections", {}).values()),
        ])).lower()
        hits = sum(text.count(w) for w in query_words)
        if hits > 0:
            scored.append({
                "path": path,
                "relevance": hits,
                "purpose": entry.get("purpose", ""),
                "organ": entry.get("organ"),
                "health_score": entry.get("health_score"),
            })

    return sorted(scored, key=lambda x: -x["relevance"])[:top_k]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build or query the README knowledge index")
    parser.add_argument("--query", help="Keyword search over the index")
    parser.add_argument("--top", type=int, default=5, help="Number of results to return")
    args = parser.parse_args()

    if args.query:
        if not INDEX_PATH.exists():
            print("Building index first...")
            write_index()
        results = query_index(args.query, top_k=args.top)
        print(f"Top {len(results)} results for '{args.query}':")
        for r in results:
            score_str = f"  health={r['health_score']}" if r["health_score"] is not None else ""
            print(f"  [{r['relevance']}] {r['path']} — {r['purpose'][:60]}{score_str}")
    else:
        write_index()
