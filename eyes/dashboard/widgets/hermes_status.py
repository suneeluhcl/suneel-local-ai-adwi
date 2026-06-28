import requests


def get_data() -> dict:
    try:
        res = requests.get("http://localhost:7777/api/hermes/status", timeout=3)
        return res.json()
    except Exception:
        return {"installed": False, "status": "unknown"}


def render_html() -> str:
    data = get_data()
    installed = data.get("installed", False)
    version = data.get("version", "not installed")
    skills = data.get("skill_count", 0)
    status = data.get("status", "unknown")

    status_icon = "🟢" if installed else "🔴"
    status_color = "var(--accent-green)" if installed else "var(--accent-red)"

    return f"""
    <div style="font-size:11px">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
        <span>{status_icon}</span>
        <span style="color:{status_color}">{status}</span>
        <span style="color:var(--text-dim);margin-left:auto">{version}</span>
      </div>
      <div style="color:var(--text-secondary)">
        Skills learned: <strong style="color:var(--accent-purple)">{skills}</strong>
      </div>
      <div style="margin-top:6px;display:flex;gap:6px">
        <button class="cc-quick-btn" onclick="startHermes()" style="font-size:10px;padding:3px 8px">
          💬 Chat
        </button>
        <button class="cc-quick-btn" onclick="hermesNight()" style="font-size:10px;padding:3px 8px">
          🌙 Night Run
        </button>
      </div>
    </div>
    """
