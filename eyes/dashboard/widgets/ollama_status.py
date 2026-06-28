import urllib.request
import json


def get_data() -> dict:
    try:
        res = urllib.request.urlopen("http://localhost:7777/api/ollama/status", timeout=3)
        return json.loads(res.read())
    except Exception:
        return {"running": False, "status": "unknown", "model_count": 0}


def render_html() -> str:
    data = get_data()
    running = data.get("running", False)
    model_count = data.get("model_count", 0)
    models = data.get("models", [])

    status_icon = "🟢" if running else "🔴"
    status_text = "running" if running else "offline"
    status_color = "var(--accent-green)" if running else "var(--accent-red)"

    model_list_html = ""
    if models:
        model_names = [m.get("name", "?") for m in models[:4]]
        model_list_html = "<div style=\"color:var(--text-dim);font-size:10px;color:var(--text-dim);padding:1px 0\">" + \
            ", ".join(model_names) + \
            ("…" if len(models) > 4 else "") + "</div>"

    return f"""
    <div style="font-size:11px">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
        <span>{status_icon}</span>
        <span style="color:{status_color}">{status_text}</span>
        <span style="color:var(--text-dim);margin-left:auto">{model_count} models</span>
      </div>
      {model_list_html}
      <div style="margin-top:6px;display:flex;gap:4px">
        <button class="cc-quick-btn" onclick="ollamaRepair()" style="font-size:10px;padding:3px 8px">
          🔧 Repair
        </button>
        <button class="cc-quick-btn" onclick="ollamaLearn()" style="font-size:10px;padding:3px 8px">
          🧠 Learn
        </button>
      </div>
    </div>
    """
