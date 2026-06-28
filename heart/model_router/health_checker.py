"""Model health checker — verifies which API providers are reachable."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def check_anthropic() -> dict:
    try:
        import anthropic
        client = anthropic.Anthropic()
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        return {"available": True, "latency_ms": 0}
    except Exception as e:
        err = str(e)
        rate_limited = "429" in err or "529" in err or "rate" in err.lower()
        return {"available": not rate_limited, "reason": err[:120]}


def check_openai() -> dict:
    try:
        import openai
        client = openai.OpenAI()
        client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
        )
        return {"available": True}
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}


def check_ollama() -> dict:
    """Check Ollama server health and list available models."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            data = json.loads(r.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"available": True, "running": True, "models": models, "model_count": len(models)}
    except Exception as e:
        return {"available": False, "running": False, "error": str(e)[:120], "models": []}


def run_health_check() -> dict:
    results = {
        "claude": check_anthropic(),
        "ollama": check_ollama(),
    }
    # Only check OpenAI if key is present
    import os
    if os.environ.get("OPENAI_API_KEY"):
        results["openai"] = check_openai()

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "providers": results,
        "any_available": any(v.get("available") for v in results.values()),
    }


if __name__ == "__main__":
    print(json.dumps(run_health_check(), indent=2))
