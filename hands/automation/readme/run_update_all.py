#!/usr/bin/env python3
"""
Bulk README updater — generates READMEs for every non-trivial workspace folder.
Supports --incremental mode to skip unchanged folders using the hash cache.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from hands.automation.readme.intelligence_engine import analyze_workspace, WORKSPACE
from hands.automation.readme.readme_generator import update_readme_for_folder


def run_all(use_claude: bool = True, quiet: bool = False, incremental: bool = False) -> bool:
    from hands.automation.readme.cache_manager import load_cache, is_folder_changed

    analyses = analyze_workspace()
    cache = load_cache() if incremental else {}
    ok_count = 0
    skip_count = 0
    fail_count = 0

    for analysis in analyses:
        folder = str(WORKSPACE / analysis["path"])

        if incremental and not is_folder_changed(folder, cache):
            skip_count += 1
            if not quiet:
                print(f"  ⏭️  {analysis['path']} (unchanged)")
            continue

        try:
            update_readme_for_folder(folder, use_claude=use_claude)
            ok_count += 1
            if not quiet:
                print(f"  ✅ {analysis['path']}")
        except Exception as e:
            fail_count += 1
            if not quiet:
                print(f"  ❌ {analysis['path']}: {e}")

    suffix = f", {skip_count} skipped" if incremental else ""
    print(f"\n{'✅' if fail_count == 0 else '⚠️'} {ok_count} updated{suffix}, {fail_count} failed")
    return fail_count == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update all workspace READMEs")
    parser.add_argument("--no-claude", action="store_true", help="Skip Claude CLI, use rule-based")
    parser.add_argument("--quiet", action="store_true", help="Only show summary")
    parser.add_argument("--incremental", action="store_true", help="Skip unchanged folders (uses cache)")
    args = parser.parse_args()

    ok = run_all(use_claude=not args.no_claude, quiet=args.quiet, incremental=args.incremental)
    sys.exit(0 if ok else 1)
