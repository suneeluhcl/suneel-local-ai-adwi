"""Tests for all Ollama-powered engines."""

import json
import urllib.request
import pytest
from tests.conftest import file_exists, import_ok, symlink_valid, WORKSPACE


class TestOllamaEngineFiles:
    def test_repair_engine_exists(self):
        assert file_exists("lab/autolab/ollama_repair_engine.py")

    def test_learning_engine_exists(self):
        assert file_exists("lab/autolab/ollama_learning_engine.py")

    def test_code_review_engine_exists(self):
        assert file_exists("lab/autolab/code_review_engine.py")

    def test_security_scanner_exists(self):
        assert file_exists("lab/autolab/security_scanner.py")

    def test_orchestrator_exists(self):
        assert file_exists("lab/autolab/ollama_orchestrator.py")

    def test_nerve_healer_exists(self):
        assert file_exists("nervous/nerve_healer.py")

    def test_memory_curator_exists(self):
        assert file_exists("brain/memory/memory_curator.py")

    def test_experiment_skill_generator_exists(self):
        assert file_exists("lab/autolab/experiment_skill_generator.py")

    def test_deep_scan_engine_exists(self):
        assert file_exists("lab/autolab/deep_scan_engine.py")


class TestOllamaEngineImports:
    def test_repair_engine_imports(self):
        assert import_ok("lab.autolab.ollama_repair_engine")

    def test_learning_engine_imports(self):
        assert import_ok("lab.autolab.ollama_learning_engine")

    def test_code_review_imports(self):
        assert import_ok("lab.autolab.code_review_engine")

    def test_security_scanner_imports(self):
        assert import_ok("lab.autolab.security_scanner")

    def test_orchestrator_imports(self):
        assert import_ok("lab.autolab.ollama_orchestrator")

    def test_nerve_healer_imports(self):
        assert import_ok("nervous.nerve_healer")

    def test_memory_curator_imports(self):
        assert import_ok("brain.memory.memory_curator")

    def test_experiment_skill_generator_imports(self):
        assert import_ok("lab.autolab.experiment_skill_generator")


class TestOllamaConnectivity:
    def test_ollama_server_running(self, ollama_available):
        assert ollama_available, "Ollama server not running at localhost:11434"

    def test_suneelworkspace_model_available(self, ollama_available):
        if not ollama_available:
            pytest.skip("Ollama not running")
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            data = json.loads(r.read())
            models = [m["name"] for m in data.get("models", [])]
            assert any("suneelworkspace" in m for m in models), \
                f"suneelworkspace model not found. Available: {models}"

    def test_ollama_can_generate(self, ollama_available):
        if not ollama_available:
            pytest.skip("Ollama not running")
        payload = json.dumps({
            "model": "llama3.2",
            "prompt": "Reply with exactly: OK",
            "stream": False,
            "options": {"num_ctx": 128, "num_predict": 8}
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        assert "response" in data
        assert len(data["response"]) > 0


class TestOllamaCLI:
    def test_ollama_review_command(self):
        assert symlink_valid("ollama-review")

    def test_security_scan_command(self):
        assert symlink_valid("security-scan")

    def test_ollama_stack_start_command(self):
        assert symlink_valid("ollama-stack-start")

    def test_ollama_stack_status_command(self):
        assert symlink_valid("ollama-stack-status")

    def test_memory_curate_command(self):
        assert symlink_valid("memory-curate")

    def test_nerve_heal_command(self):
        assert symlink_valid("nerve-heal")

    def test_ollama_orchestrate_command(self):
        assert symlink_valid("ollama-orchestrate")
