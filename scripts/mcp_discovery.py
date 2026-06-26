#!/usr/bin/env python3
"""System capability discovery and MCP recommendations generator."""

import json
import os
import pathlib
import shutil

ROOT = pathlib.Path(os.environ.get("SUNEEL_WORKSPACE", str(pathlib.Path.home() / "SuneelWorkSpace"))).resolve()
INVENTORY_PATH = ROOT / "tools/tool_inventory.json"
OPPORTUNITIES_PATH = ROOT / "tools/mcp_opportunities.json"
RECOMMENDATIONS_PATH = ROOT / "tools/mcp_recommendations.md"

def load_inventory() -> list:
    if not INVENTORY_PATH.exists():
        return []
    try:
        data = json.loads(INVENTORY_PATH.read_text())
        return data.get("tools", [])
    except Exception:
        return []

def main():
    tools = load_inventory()
    
    # Check what is installed on the system
    installed_names = {t.get("name").lower(): t for t in tools}
    
    opportunities = {
        "communication": [],
        "development": [],
        "research": [],
        "automation": [],
        "system_control": []
    }
    
    # 1. Communication Opportunities
    if "imessage-status" in installed_names or "mail-status" in installed_names:
        opportunities["communication"].append({
            "name": "mac-comms-mcp",
            "detected_triggers": ["mail-status", "imessage-recent"],
            "purpose": " macOS iMessage and Mail integration",
            "connector_source": "builtin/custom",
            "status": "partially_integrated"
        })
    
    # 2. Development Opportunities
    if shutil.which("git") or "git" in installed_names:
        opportunities["development"].append({
            "name": "github-mcp",
            "detected_triggers": ["git", "gh"],
            "purpose": "GitHub PR, issue, and repository management",
            "connector_source": "github.com/modelcontextprotocol/servers/tree/main/src/github",
            "status": "available"
        })
    if shutil.which("sqlite3") or "sqlite3" in installed_names:
        opportunities["development"].append({
            "name": "sqlite-mcp",
            "detected_triggers": ["sqlite3"],
            "purpose": "SQLite database queries and schema inspection",
            "connector_source": "github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
            "status": "available"
        })
    if shutil.which("docker"):
        opportunities["development"].append({
            "name": "docker-mcp",
            "detected_triggers": ["docker"],
            "purpose": "Docker container and image inspection",
            "connector_source": "github.com/modelcontextprotocol/servers/tree/main/src/docker",
            "status": "available"
        })
        
    # 3. Research Opportunities
    if "obsidian" in installed_names or os.path.exists("/Applications/Obsidian.app"):
        opportunities["research"].append({
            "name": "obsidian-mcp",
            "detected_triggers": ["obsidian"],
            "purpose": "Expose Obsidian vault notes as direct resources",
            "connector_source": "builtin/custom-bridge",
            "status": "fully_integrated"
        })
    opportunities["research"].append({
        "name": "brave-search-mcp",
        "detected_triggers": ["brew"],
        "purpose": "Web search capabilities for fresh research",
        "connector_source": "github.com/modelcontextprotocol/servers/tree/main/src/brave-search",
        "status": "available"
    })
    
    # 4. Automation Opportunities
    if shutil.which("shortcuts") or "shortcuts" in installed_names:
        opportunities["automation"].append({
            "name": "macos-shortcuts-mcp",
            "detected_triggers": ["shortcuts", "osascript"],
            "purpose": "Trigger native macOS Shortcuts app workflows",
            "connector_source": "builtin/custom-shortcuts",
            "status": "available"
        })
        
    # 5. System Control Opportunities
    opportunities["system_control"].append({
        "name": "filesystem-mcp",
        "detected_triggers": ["mdfind", "rg"],
        "purpose": "Safe, read-only file listing, reading, and searching",
        "connector_source": "github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        "status": "available"
    })
    
    # Write opportunities JSON
    OPPORTUNITIES_PATH.write_text(json.dumps({"opportunities": opportunities, "generated_at": now_iso()}, indent=2) + "\n")
    print(f"Generated {OPPORTUNITIES_PATH}")
    
    # Write recommendations markdown
    rec_lines = [
        "# MCP Connector Recommendations",
        "",
        f"Generated: {now_iso()}",
        "",
        "The following Model Context Protocol (MCP) servers are recommended based on your macOS system apps, developer tools, and workflow logs.",
        "",
        "## Recommendations List",
        ""
    ]
    
    for category, list_opps in opportunities.items():
        if not list_opps:
            continue
        rec_lines.append(f"### {category.replace('_', ' ').capitalize()}")
        rec_lines.append("")
        for opp in list_opps:
            status_str = "Integrated" if opp["status"] == "fully_integrated" else "Recommended"
            priority = "HIGH" if opp["name"] in ["github-mcp", "filesystem-mcp", "obsidian-mcp"] else "MED"
            complexity = "Low" if opp["name"] in ["sqlite-mcp", "filesystem-mcp"] else "Medium"
            
            rec_lines.extend([
                f"#### {opp['name']} ({status_str})",
                f"- **What it enables**: {opp['purpose']}",
                f"- **How it integrates**: Connects as an MCP server using `uv` or custom python main handler.",
                f"- **Complexity**: {complexity}",
                f"- **Priority**: {priority}",
                ""
            ])
            
    RECOMMENDATIONS_PATH.write_text("\n".join(rec_lines) + "\n")
    print(f"Generated {RECOMMENDATIONS_PATH}")

def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat()

if __name__ == "__main__":
    main()
