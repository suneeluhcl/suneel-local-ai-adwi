"""Tests for eyes/ organ — dashboard, widgets, nerve monitor."""

import pytest
from tests.conftest import file_exists, read_json, import_ok, symlink_valid, WORKSPACE


class TestEyesStructure:
    def test_nerve_json_exists(self):
        assert file_exists("eyes/nerve.json")

    def test_readme_exists(self):
        assert file_exists("eyes/README.md")

    def test_dashboard_server_exists(self):
        assert file_exists("eyes/dashboard/server.py")

    def test_dashboard_index_exists(self):
        assert file_exists("eyes/dashboard/index.html")

    def test_widgets_dir_exists(self):
        assert file_exists("eyes/dashboard/widgets")

    def test_nerve_monitor_widget_exists(self):
        assert file_exists("eyes/dashboard/widgets/nerve_monitor.py")

    def test_ollama_status_widget_exists(self):
        assert file_exists("eyes/dashboard/widgets/ollama_status.py")

    def test_hermes_status_widget_exists(self):
        assert file_exists("eyes/dashboard/widgets/hermes_status.py")


class TestEyesNerveJson:
    def test_nerve_json_valid(self):
        nerve = read_json("eyes/nerve.json")
        assert nerve.get("organ") == "eyes"
        assert nerve.get("version") == "1.1"
        assert len(nerve.get("provides", {})) >= 3
        assert "nerve_monitor" in nerve.get("provides", {})


class TestEyesImports:
    def test_nerve_monitor_imports(self):
        assert import_ok("eyes.dashboard.widgets.nerve_monitor")

    def test_ollama_status_imports(self):
        assert import_ok("eyes.dashboard.widgets.ollama_status")

    def test_hermes_status_imports(self):
        assert import_ok("eyes.dashboard.widgets.hermes_status")


class TestEyesNerveMonitor:
    def test_nerve_monitor_get_data(self):
        from eyes.dashboard.widgets.nerve_monitor import get_data
        data = get_data()
        assert "organs" in data
        assert "healthy_count" in data
        assert "total_organs" in data
        assert data["total_organs"] == 12, f"Expected 12 organs, got {data['total_organs']}"

    def test_nerve_monitor_render_html(self):
        from eyes.dashboard.widgets.nerve_monitor import render_html
        html = render_html()
        assert isinstance(html, str)
        assert len(html) > 100


class TestEyesCLI:
    def test_workspace_dashboard_command(self):
        assert symlink_valid("workspace-dashboard"), "workspace-dashboard symlink missing"

    def test_run_tests_command(self):
        assert symlink_valid("run-tests"), "run-tests symlink missing"
