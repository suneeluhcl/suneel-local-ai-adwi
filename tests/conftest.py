"""Shared pytest fixtures for SuneelWorkSpace tests."""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(WORKSPACE / "agent-system" / "telemetry"))
sys.path.insert(0, str(WORKSPACE / "dispatcher"))
sys.path.insert(0, str(WORKSPACE / "dashboard"))


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary telemetry SQLite DB."""
    db = tmp_path / "telemetry.db"
    schema = (WORKSPACE / "agent-system" / "telemetry" / "schema.sql").read_text()
    conn = sqlite3.connect(db)
    conn.executescript(schema)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def tmp_workspace(tmp_path):
    """Minimal workspace directory tree for isolated tests."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "agent-system" / "tasks").mkdir(parents=True)
    (tmp_path / "agent-system" / "memory").mkdir(parents=True)
    (tmp_path / "agent-system" / "telemetry").mkdir(parents=True)
    (tmp_path / "autolab").mkdir()
    return tmp_path
