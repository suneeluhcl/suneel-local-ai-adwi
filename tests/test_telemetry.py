"""Tests for P3.2 telemetry engine."""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE / "agent-system" / "telemetry"))


def _make_writer(tmp_db):
    import telemetry_writer as tw
    with patch.object(tw, 'DB_PATH', tmp_db):
        yield tw


@pytest.fixture
def writer(tmp_db):
    import importlib
    import telemetry_writer as tw
    original_db = tw.DB_PATH
    tw.DB_PATH = tmp_db
    yield tw
    tw.DB_PATH = original_db


def test_write_trace_success(writer):
    row_id = writer.write_trace("claude", "code_review", "success", 1200, 500, 300)
    assert row_id == 1


def test_write_trace_stores_fields(writer, tmp_db):
    writer.write_trace("codex", "code_edit", "fail", 900, 400, 0, {"step": "compile"})
    conn = sqlite3.connect(tmp_db)
    row = conn.execute("SELECT * FROM traces WHERE id=1").fetchone()
    conn.close()
    assert row[2] == "codex"
    assert row[3] == "code_edit"
    assert row[7] == "fail"
    assert json.loads(row[8]) == {"step": "compile"}


def test_write_trace_invalid_outcome(writer):
    with pytest.raises(ValueError, match="outcome must be"):
        writer.write_trace("claude", "test", "unknown_outcome")


def test_multiple_traces(writer, tmp_db):
    for i in range(5):
        writer.write_trace("claude", "health_check", "success", i * 100, 10, 10)
    conn = sqlite3.connect(tmp_db)
    count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    conn.close()
    assert count == 5


def test_anomaly_detection_no_data(tmp_db):
    import telemetry_anomaly as ta
    original = ta.DB_PATH
    ta.DB_PATH = tmp_db
    anomalies = ta.detect_anomalies()
    ta.DB_PATH = original
    assert anomalies == []
