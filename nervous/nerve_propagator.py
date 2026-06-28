"""
Nervous system nerve propagator — routes change events between organs.
"""
import json
import os
import sys
from datetime import datetime, timezone

WORKSPACE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
REGISTRY_PATH = os.path.join(WORKSPACE, "nervous/nerve_registry.json")
NERVE_LOG_PATH = os.path.join(WORKSPACE, "blood/logs/nerve_events.jsonl")


def _load_registry() -> dict:
    try:
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    except Exception:
        return {"organs": {}}


def get_status() -> dict:
    """Return health status for all 12 organs."""
    organs = ["brain", "heart", "eyes", "ears", "nervous", "skeleton",
              "blood", "hands", "mouth", "dna", "lab", "spine"]
    status = {}
    for organ_name in organs:
        organ_dir = os.path.join(WORKSPACE, organ_name)
        nerve_path = os.path.join(WORKSPACE, organ_name, "nerve.json")
        inbox_path = os.path.join(WORKSPACE, organ_name, "nerve_inbox")
        pending = 0
        if os.path.isdir(inbox_path):
            try:
                pending = len([f for f in os.listdir(inbox_path) if f.endswith(".json")])
            except Exception:
                pass
        status[organ_name] = {
            "path_exists": os.path.isdir(organ_dir),
            "nerve_json_exists": os.path.isfile(nerve_path),
            "unprocessed_notifications": pending,
        }
    return status


def notify_change(organ: str, event_type: str = "file_updated", detail: str = "", *args, **kwargs) -> dict:
    registry = _load_registry()
    organ_config = registry["organs"].get(organ, {})
    subscribers = organ_config.get("notifies", [])

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_organ": organ,
        "event_type": event_type,
        "detail": detail,
        "notified": subscribers,
    }

    # Write to each subscriber's inbox
    for subscriber in subscribers:
        inbox = os.path.join(WORKSPACE, registry["organs"].get(subscriber, {}).get("inbox", f"{subscriber}/nerve_inbox/"))
        os.makedirs(inbox, exist_ok=True)
        inbox_file = os.path.join(inbox, f"{organ}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S%f')}.json")
        try:
            with open(inbox_file, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    # Log the event
    _log_event(payload)
    return payload


def check_inbox(organ: str) -> list[dict]:
    registry = _load_registry()
    inbox_path = os.path.join(WORKSPACE, registry["organs"].get(organ, {}).get("inbox", f"{organ}/nerve_inbox/"))
    os.makedirs(inbox_path, exist_ok=True)
    events = []
    try:
        for fname in sorted(os.listdir(inbox_path)):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(inbox_path, fname)) as f:
                        events.append(json.load(f))
                except Exception:
                    pass
    except Exception:
        pass
    return events


def clear_inbox(organ: str) -> int:
    registry = _load_registry()
    inbox_path = os.path.join(WORKSPACE, registry["organs"].get(organ, {}).get("inbox", f"{organ}/nerve_inbox/"))
    cleared = 0
    try:
        for fname in os.listdir(inbox_path):
            if fname.endswith(".json"):
                os.remove(os.path.join(inbox_path, fname))
                cleared += 1
    except Exception:
        pass
    return cleared


def _log_event(payload: dict) -> None:
    os.makedirs(os.path.dirname(NERVE_LOG_PATH), exist_ok=True)
    try:
        with open(NERVE_LOG_PATH, "a") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def log_enhancement(organ: str, description: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger_path = os.path.join(WORKSPACE, "spine/enhancement_logger.py")
    if os.path.exists(logger_path):
        try:
            sys.path.insert(0, WORKSPACE)
            from spine.enhancement_logger import log as _log
            _log(organ, description)
        except Exception:
            pass
    # Fallback: write directly to blood/logs
    log_path = os.path.join(WORKSPACE, "blood/logs/enhancements.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    entry = {"date": today, "organ": organ, "description": description}
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def get_recent(n: int = 10) -> list[dict]:
    events = []
    try:
        with open(NERVE_LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return events[-n:]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "notify":
        organ = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        detail = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        notify_change(organ, detail=detail)
        print(f"Notified subscribers of {organ}")

    elif cmd == "inbox":
        organ = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        events = check_inbox(organ)
        print(f"{organ} inbox: {len(events)} message(s)")
        for e in events:
            print(f"  [{e.get('timestamp','')}] from {e.get('source_organ','')} — {e.get('event_type','')} {e.get('detail','')}")

    elif cmd == "recent":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        for e in get_recent(n):
            print(f"[{e.get('timestamp','')}] {e.get('source_organ','')} → {e.get('notified',[])} ({e.get('event_type','')})")

    elif cmd == "log":
        organ = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        desc = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        log_enhancement(organ, desc)
        print(f"Logged enhancement for {organ}")
