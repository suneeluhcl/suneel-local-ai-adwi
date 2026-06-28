"""
nerve_monitor.py
Dashboard widget showing live nerve system health.
Shows all 12 organs with connection status and pending notifications.
"""

import html
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/SuneelWorkSpace"))


ORGAN_NAMES = ["brain", "heart", "eyes", "ears", "nervous", "skeleton",
               "blood", "hands", "mouth", "dna", "lab", "spine"]


def get_data() -> dict:
    """Get nerve system status for all 12 organs by inspecting filesystem directly."""
    workspace = os.path.expanduser("~/SuneelWorkSpace")
    organs = []
    total_pending = 0
    healthy_count = 0

    # Load nerve_registry for organ metadata
    registry_path = os.path.join(workspace, "nervous/nerve_registry.json")
    registry = {}
    if os.path.exists(registry_path):
        try:
            registry = json.load(open(registry_path)).get("organs", {})
        except Exception:
            pass

    for organ_name in ORGAN_NAMES:
        organ_dir = os.path.join(workspace, organ_name)
        nerve_path = os.path.join(workspace, organ_name, "nerve.json")
        inbox_path = os.path.join(workspace, organ_name, "nerve_inbox")

        path_exists = os.path.isdir(organ_dir)
        nerve_exists = os.path.isfile(nerve_path)

        # Count unprocessed notifications in inbox
        pending = 0
        if os.path.isdir(inbox_path):
            try:
                pending = len([f for f in os.listdir(inbox_path)
                               if not f.startswith(".")])
            except Exception:
                pass

        total_pending += pending

        health = "healthy"
        if not path_exists:
            health = "missing"
        elif not nerve_exists:
            health = "no_nerve"
        elif pending > 5:
            health = "overloaded"
        elif pending > 0:
            health = "pending"

        if health == "healthy":
            healthy_count += 1

        organs.append({
            "name": organ_name,
            "health": health,
            "pending": pending,
            "path_exists": path_exists,
            "nerve_exists": nerve_exists,
        })

    migration_complete = registry.get("migration_complete", False) if registry else False

    return {
        "organs": organs,
        "total_pending": total_pending,
        "healthy_count": healthy_count,
        "total_organs": len(organs),
        "migration_complete": migration_complete,
    }


def render_html() -> str:
    """Render nerve monitor as HTML panel."""
    data = get_data()
    organs = data.get("organs", [])
    healthy = data.get("healthy_count", 0)
    total = data.get("total_organs", 12)
    pending = data.get("total_pending", 0)

    ORGAN_EMOJIS = {
        "brain": "🧠", "heart": "💓", "eyes": "👁️", "ears": "👂",
        "nervous": "🫀", "skeleton": "🦴", "blood": "🩸", "hands": "🤲",
        "mouth": "👄", "dna": "🧬", "lab": "🔬", "spine": "📋",
    }

    HEALTH_COLORS = {
        "healthy": "var(--accent-green)",
        "pending": "var(--accent-yellow)",
        "overloaded": "var(--accent-red)",
        "no_nerve": "var(--accent-yellow)",
        "missing": "var(--accent-red)",
    }

    HEALTH_ICONS = {
        "healthy": "●",
        "pending": "◐",
        "overloaded": "⚠",
        "no_nerve": "○",
        "missing": "✕",
    }

    # Build organ grid
    organ_dots = ""
    for organ in organs:
        organ_health = organ.get("health", "missing")
        color = HEALTH_COLORS.get(organ_health, "var(--text-dim)")
        icon = HEALTH_ICONS.get(organ_health, "?")
        emoji = ORGAN_EMOJIS.get(organ["name"], "?")
        organ_pending = int(organ.get("pending", 0))
        pending_str = f" ({organ_pending})" if organ_pending > 0 else ""
        organ_name = html.escape(str(organ["name"]))
        pending_badge = f'<span style="font-size:9px;color:var(--accent-yellow);margin-left:auto">+{organ_pending}</span>' if organ_pending > 0 else ""
        organ_dots += f"""
        <div style="display:flex;align-items:center;gap:4px;padding:2px 0" title="{organ_name}: {organ_health}{pending_str}">
          <span style="color:{color};font-size:10px">{icon}</span>
          <span style="font-size:10px">{emoji}</span>
          <span style="font-size:10px;color:var(--text-secondary)">{organ_name}</span>
          {pending_badge}
        </div>"""

    health_color = "var(--accent-green)" if healthy == total else \
                   "var(--accent-yellow)" if healthy >= total * 0.8 else \
                   "var(--accent-red)"

    pending_badge_html = f'<span style="color:var(--accent-yellow);font-size:10px">{pending} pending</span>' if pending > 0 else ""

    return f"""
    <div style="font-size:11px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="color:{health_color};font-weight:600">{healthy}/{total} healthy</span>
        {pending_badge_html}
        <button class="cc-quick-btn" onclick="quickAction('nerve-status')"
                style="font-size:9px;padding:2px 6px;margin-left:auto">Check</button>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0">
        {organ_dots}
      </div>
    </div>
    """
