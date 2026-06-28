"""
readme_sync.py
After every test run, updates all READMEs to reflect current test status.
Run: readme-sync
"""

import json
import os
import re
from datetime import datetime, timezone

WORKSPACE = os.path.expanduser("~/SuneelWorkSpace")
ORGANS = ["brain", "heart", "eyes", "ears", "nervous", "skeleton",
          "blood", "hands", "mouth", "dna", "lab", "spine"]


def _get_category_status(results: dict, category: str) -> str:
    failures = results.get("failures", [])
    cat_failures = [f for f in failures if category.lower() in f.get("test", "").lower()]
    return "Pass" if not cat_failures else f"Fail ({len(cat_failures)})"


def update_main_readme(test_results: dict):
    readme_path = os.path.join(WORKSPACE, "README.md")
    if not os.path.exists(readme_path):
        return

    passed = test_results.get("passed", 0)
    total = test_results.get("total", 0)
    failed = test_results.get("failed", 0)
    pass_rate = passed / max(total, 1)
    status_icon = "OK" if pass_rate >= 0.95 else "WARN" if pass_rate >= 0.80 else "FAIL"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    test_section = f"""## TEST STATUS

**{passed}/{total} tests passing** ({pass_rate*100:.1f}%) [{status_icon}] — Last run: {today}

| Category | Status |
|---|---|
| Nerve Connections | {_get_category_status(test_results, "nervous")} |
| Ollama Engines | {_get_category_status(test_results, "ollama")} |
| Integration | {_get_category_status(test_results, "integration")} |

`run-tests` to run | `repair-loop` to auto-fix
"""

    content = open(readme_path).read()
    if "## TEST STATUS" in content:
        content = re.sub(r"## TEST STATUS.*?(?=\n## |\Z)", test_section, content, flags=re.DOTALL)
    else:
        content = content + "\n\n" + test_section

    with open(readme_path, "w") as f:
        f.write(content)
    print(f"  README.md updated")


def update_organ_readme(organ: str, test_results: dict):
    readme_path = os.path.join(WORKSPACE, organ, "README.md")
    if not os.path.exists(readme_path):
        return

    failures = test_results.get("failures", [])
    organ_failures = [f for f in failures if organ in f.get("test", "").lower()]
    status = "All tests passing" if not organ_failures else f"{len(organ_failures)} tests failing"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    test_line = f"\n**Test Status:** {status} (last run: {today})\n"

    content = open(readme_path).read()
    if "**Test Status:**" in content:
        content = re.sub(r"\*\*Test Status:\*\*.*?\n", test_line, content)
    else:
        lines = content.split("\n")
        # Insert after first heading
        for i, line in enumerate(lines):
            if line.startswith("##") and i > 0:
                lines.insert(i, test_line)
                break
        else:
            lines.append(test_line)
        content = "\n".join(lines)

    with open(readme_path, "w") as f:
        f.write(content)


def sync_all_readmes(test_results: dict):
    print("Syncing READMEs with test results...")
    update_main_readme(test_results)
    for organ in ORGANS:
        update_organ_readme(organ, test_results)
        print(f"  {organ}/README.md updated")
    print("All READMEs synced")


if __name__ == "__main__":
    reports_dir = os.path.join(WORKSPACE, "tests/reports")
    if not os.path.exists(reports_dir) or not os.listdir(reports_dir):
        print("No test reports found — run tests first with: run-tests")
    else:
        reports = sorted(
            [f for f in os.listdir(reports_dir) if f.startswith("test_report_")],
        )
        if reports:
            latest_path = os.path.join(reports_dir, reports[-1])
            latest = json.load(open(latest_path))
            sync_all_readmes(latest)
        else:
            print("No test reports found")
