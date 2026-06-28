"""
conftest.py
Shared pytest fixtures and utilities for all SuneelWorkSpace tests.
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

WORKSPACE = os.path.expanduser("~/SuneelWorkSpace")
sys.path.insert(0, WORKSPACE)
os.chdir(WORKSPACE)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def workspace_root():
    return Path(WORKSPACE)


@pytest.fixture(scope="session")
def ollama_available():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def dashboard_available():
    try:
        urllib.request.urlopen("http://localhost:7777/api/health", timeout=3)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def nerve_registry():
    path = os.path.join(WORKSPACE, "nervous/nerve_registry.json")
    if os.path.exists(path):
        return json.load(open(path))
    return {}


@pytest.fixture(scope="session")
def telemetry_db():
    db_path = os.path.join(WORKSPACE, "blood/telemetry/telemetry.db")
    if os.path.exists(db_path):
        return sqlite3.connect(db_path)
    return None


@pytest.fixture(autouse=True)
def record_test_result(request):
    start = time.time()
    yield
    duration_ms = int((time.time() - start) * 1000)
    try:
        failed = request.node.rep_call.failed if hasattr(request.node, "rep_call") else False
        outcome = "failure" if failed else "success"
    except Exception:
        outcome = "unknown"
    _write_test_telemetry(request.node.nodeid, outcome, duration_ms)


def _write_test_telemetry(test_id: str, outcome: str, duration_ms: int):
    try:
        sys.path.insert(0, WORKSPACE)
        from blood.telemetry.telemetry_writer import start_trace, complete_trace
        tid = start_trace("system", "test", intent=test_id, workflow_name="test_suite")
        complete_trace(tid, outcome, output_quality=1.0 if outcome == "success" else 0.0)
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def file_exists(relative_path: str) -> bool:
    return os.path.exists(os.path.join(WORKSPACE, relative_path))


def read_json(relative_path: str) -> dict:
    full = os.path.join(WORKSPACE, relative_path)
    if not os.path.exists(full):
        return {}
    try:
        return json.load(open(full))
    except Exception:
        return {}


def import_ok(module_path: str) -> bool:
    try:
        __import__(module_path)
        return True
    except Exception:
        return False


def symlink_valid(command: str) -> bool:
    link = os.path.join(WORKSPACE, f"hands/bin/{command}")
    return os.path.islink(link) and os.path.exists(link)


def check_inbox(organ: str) -> int:
    inbox = os.path.join(WORKSPACE, organ, "nerve_inbox")
    if not os.path.isdir(inbox):
        return 0
    return len([f for f in os.listdir(inbox) if f.endswith(".json")])
