#!/usr/bin/env python3
"""
Cache Manager — tracks folder content hashes to enable incremental README updates.
Cache file: spine/readme_health_cache.json
Entry format: { "rel/path": { "hash": str, "health_score": int, "readme_mtime": float, "updated": str } }
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

WORKSPACE = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True,
    cwd=os.path.dirname(os.path.abspath(__file__))
).strip())

CACHE_PATH = WORKSPACE / "spine/readme_health_cache.json"
IGNORED = {".git", "node_modules", ".venv", "__pycache__", ".DS_Store", "nerve_inbox"}


def _hash_folder(folder_path: Path) -> str:
    """Stable MD5 of all file names + sizes + mtimes (shallow, non-recursive)."""
    parts = []
    try:
        for item in sorted(folder_path.iterdir()):
            if item.name in IGNORED or item.name.startswith("."):
                continue
            if item.is_file():
                try:
                    stat = item.stat()
                    parts.append(f"{item.name}:{stat.st_size}:{stat.st_mtime:.0f}")
                except Exception:
                    pass
    except Exception:
        pass
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2))
    tmp.rename(CACHE_PATH)


def is_folder_changed(folder_path: str, cache: dict) -> bool:
    """Return True if folder content has changed since last cache entry."""
    path = Path(folder_path).resolve()
    try:
        rel = str(path.relative_to(WORKSPACE))
    except ValueError:
        rel = str(path)

    current_hash = _hash_folder(path)
    entry = cache.get(rel, {})
    if current_hash != entry.get("hash", ""):
        return True

    # Also flag if README mtime changed (was manually edited)
    readme_path = path / "README.md"
    current_mtime = readme_path.stat().st_mtime if readme_path.exists() else 0.0
    if current_mtime != entry.get("readme_mtime", 0.0):
        return True

    return False


def update_cache(folder_path: str, health_score: int, cache: dict) -> dict:
    """Update cache entry for folder. Returns updated cache dict (must call save_cache separately)."""
    path = Path(folder_path).resolve()
    try:
        rel = str(path.relative_to(WORKSPACE))
    except ValueError:
        rel = str(path)

    readme_path = path / "README.md"
    readme_mtime = readme_path.stat().st_mtime if readme_path.exists() else 0.0

    cache[rel] = {
        "hash": _hash_folder(path),
        "health_score": health_score,
        "readme_mtime": readme_mtime,
        "updated": datetime.now().isoformat(),
    }
    return cache


def get_cached_score(folder_path: str, cache: dict = None) -> int:
    """Return cached health score, or -1 if not cached."""
    if cache is None:
        cache = load_cache()
    path = Path(folder_path).resolve()
    try:
        rel = str(path.relative_to(WORKSPACE))
    except ValueError:
        rel = str(path)
    return cache.get(rel, {}).get("health_score", -1)


def get_low_health_folders(threshold: int = 60, cache: dict = None) -> list:
    """Return list of {path, score} dicts for folders below threshold."""
    if cache is None:
        cache = load_cache()
    return sorted(
        [
            {"path": p, "score": v["health_score"]}
            for p, v in cache.items()
            if v.get("health_score", 100) < threshold
        ],
        key=lambda x: x["score"],
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="README health cache manager")
    parser.add_argument("--low", type=int, default=60, help="Show folders below this health score")
    parser.add_argument("--stats", action="store_true", help="Show cache statistics")
    args = parser.parse_args()

    cache = load_cache()
    if args.stats:
        scores = [v.get("health_score", -1) for v in cache.values() if "health_score" in v]
        print(f"Cache entries: {len(cache)}")
        if scores:
            print(f"Avg health score: {sum(scores)/len(scores):.0f}")
            print(f"Min: {min(scores)}  Max: {max(scores)}")
    else:
        low = get_low_health_folders(args.low, cache)
        print(f"Cache: {len(cache)} entries, {len(low)} below {args.low}:")
        for f in low:
            print(f"  {f['score']:3d}  {f['path']}")
