"""Tests for nervous/ organ — nerve propagator, registry, connections, MCP."""

import os
import pytest
from tests.conftest import file_exists, read_json, import_ok, symlink_valid, WORKSPACE, check_inbox


class TestNervousStructure:
    def test_nerve_propagator_exists(self):
        assert file_exists("nervous/nerve_propagator.py")

    def test_nerve_registry_exists(self):
        assert file_exists("nervous/nerve_registry.json")

    def test_nerve_json_exists(self):
        assert file_exists("nervous/nerve.json")

    def test_mcp_server_dir_exists(self):
        assert file_exists("nervous/mcp"), "nervous/mcp/ missing"

    def test_nerve_healer_exists(self):
        assert file_exists("nervous/nerve_healer.py")


class TestNervousNerveJson:
    def test_nerve_json_valid(self):
        nerve = read_json("nervous/nerve.json")
        assert nerve.get("organ") == "nervous"
        assert nerve.get("version") == "1.1"
        assert "nerve_propagator" in nerve.get("provides", {})


class TestNervePropagator:
    def test_nerve_propagator_imports(self):
        assert import_ok("nervous.nerve_propagator"), "nerve_propagator import failed"

    def test_nerve_healer_imports(self):
        assert import_ok("nervous.nerve_healer"), "nerve_healer import failed"

    def test_notify_change_works(self):
        from nervous.nerve_propagator import notify_change
        event = notify_change("brain", "test", "test from test suite")
        assert event is not None
        assert event["source_organ"] == "brain"
        assert event["event_type"] == "test"

    def test_notify_change_creates_inbox_file(self):
        from nervous.nerve_propagator import notify_change
        notify_change("heart", "test_event", "test suite validation")
        inbox_path = os.path.join(WORKSPACE, "heart/nerve_inbox")
        if os.path.isdir(inbox_path):
            files = os.listdir(inbox_path)
            assert any(f.endswith(".json") for f in files), \
                "No inbox file created after notify_change"

    def test_get_status_works(self):
        from nervous.nerve_propagator import get_status
        status = get_status()
        assert isinstance(status, dict)
        assert "brain" in status
        assert "heart" in status
        for organ, info in status.items():
            assert "path_exists" in info
            assert "nerve_json_exists" in info


class TestNerveRegistry:
    def test_nerve_registry_valid_json(self):
        registry = read_json("nervous/nerve_registry.json")
        assert isinstance(registry, dict)

    def test_all_12_organs_have_nerve_json(self):
        organs = ["brain", "heart", "eyes", "ears", "nervous", "skeleton",
                  "blood", "hands", "mouth", "dna", "lab", "spine"]
        missing = [o for o in organs if not file_exists(f"{o}/nerve.json")]
        assert len(missing) == 0, f"Organs missing nerve.json: {missing}"

    def test_all_nerve_jsons_have_version_1_1(self):
        organs = ["brain", "heart", "eyes", "ears", "nervous", "skeleton",
                  "blood", "hands", "mouth", "dna", "lab", "spine"]
        wrong_version = []
        for o in organs:
            n = read_json(f"{o}/nerve.json")
            if n.get("version") != "1.1":
                wrong_version.append(f"{o} ({n.get('version', 'missing')})")
        assert len(wrong_version) == 0, f"Organs with wrong nerve.json version: {wrong_version}"
