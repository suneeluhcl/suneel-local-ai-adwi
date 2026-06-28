"""Tests for blood/ organ — telemetry, logs, anomaly detection."""

import os
import sqlite3
import pytest
from tests.conftest import file_exists, read_json, import_ok, symlink_valid, WORKSPACE


class TestBloodStructure:
    def test_nerve_json_exists(self):
        assert file_exists("blood/nerve.json")

    def test_logs_dir_exists(self):
        assert file_exists("blood/logs"), "blood/logs/ missing"

    def test_telemetry_dir_exists(self):
        assert file_exists("blood/telemetry"), "blood/telemetry/ missing"

    def test_session_log_exists(self):
        assert file_exists("blood/logs/SESSION_LOG.md"), "SESSION_LOG.md missing"


class TestBloodNerveJson:
    def test_nerve_json_valid(self):
        nerve = read_json("blood/nerve.json")
        assert nerve.get("organ") == "blood"
        assert nerve.get("version") == "1.1"
        assert "session_log" in nerve.get("provides", {})


class TestBloodTelemetry:
    def test_telemetry_db_exists_or_skip(self):
        db_path = os.path.join(WORKSPACE, "blood/telemetry/telemetry.db")
        if not os.path.exists(db_path):
            pytest.skip("telemetry.db not yet created — will be created on first trace")
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "traces" in tables, f"traces table missing. Tables: {tables}"

    def test_telemetry_writer_importable_or_skip(self):
        if not file_exists("blood/telemetry/telemetry_writer.py"):
            pytest.skip("telemetry_writer.py not found")
        assert import_ok("blood.telemetry.telemetry_writer")

    def test_night_ops_dir_exists(self):
        assert file_exists("blood/logs/night_operations"), "blood/logs/night_operations/ missing"

    def test_deep_scan_findings_exist(self):
        assert file_exists("blood/logs/night_operations/deep_scan_findings.json")
