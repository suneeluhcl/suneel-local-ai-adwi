"""Tests for brain/ organ — memory, vector search, knowledge graph, anticipation."""

import pytest
from tests.conftest import file_exists, read_json, import_ok, symlink_valid, WORKSPACE


class TestBrainStructure:
    def test_nerve_json_exists(self):
        assert file_exists("brain/nerve.json"), "brain/nerve.json missing"

    def test_readme_exists(self):
        assert file_exists("brain/README.md"), "brain/README.md missing"

    def test_memory_files_exist(self):
        for f in ["MEMORY.md", "DECISIONS.md", "SESSION_HANDOFF.md"]:
            assert file_exists(f"brain/memory/{f}"), f"brain/memory/{f} missing"

    def test_memory_dir_exists(self):
        assert file_exists("brain/memory"), "brain/memory/ missing"


class TestBrainNerveJson:
    def test_nerve_json_valid(self):
        nerve = read_json("brain/nerve.json")
        assert nerve.get("organ") == "brain"
        assert nerve.get("version") == "1.1"
        assert "provides" in nerve
        assert "needs" in nerve
        assert len(nerve.get("key_files", [])) >= 3

    def test_nerve_json_has_provides(self):
        nerve = read_json("brain/nerve.json")
        provides = nerve.get("provides", {})
        assert len(provides) >= 3, f"Expected >=3 provides, got {len(provides)}"

    def test_nerve_inbox_exists(self):
        assert file_exists("brain/nerve_inbox"), "brain/nerve_inbox/ missing"


class TestBrainImports:
    def test_memory_curator_imports(self):
        assert import_ok("brain.memory.memory_curator"), "memory_curator import failed"


class TestBrainCLI:
    def test_memory_search_command(self):
        assert symlink_valid("memory-search"), "memory-search symlink missing"
