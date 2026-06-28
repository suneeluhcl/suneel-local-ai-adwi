"""Tests for heart/ organ — model router, quota tracker, goals, scheduler."""

import pytest
from tests.conftest import file_exists, read_json, import_ok, symlink_valid, WORKSPACE


class TestHeartStructure:
    def test_nerve_json_exists(self):
        assert file_exists("heart/nerve.json")

    def test_readme_exists(self):
        assert file_exists("heart/README.md")

    def test_model_router_dir_exists(self):
        assert file_exists("heart/model_router"), "heart/model_router/ missing"

    def test_router_py_exists(self):
        assert file_exists("heart/model_router/router.py")

    def test_model_registry_exists(self):
        assert file_exists("heart/model_router/model_registry.json")

    def test_quota_tracker_exists(self):
        assert file_exists("heart/model_router/quota_tracker.py")

    def test_model_rotator_exists(self):
        assert file_exists("heart/model_router/model_rotator.py")

    def test_health_checker_exists(self):
        assert file_exists("heart/model_router/health_checker.py")


class TestHeartNerveJson:
    def test_nerve_json_valid(self):
        nerve = read_json("heart/nerve.json")
        assert nerve.get("organ") == "heart"
        assert nerve.get("version") == "1.1"
        assert len(nerve.get("provides", {})) >= 2
        assert len(nerve.get("key_files", [])) >= 3


class TestHeartModelRouter:
    def test_router_imports(self):
        assert import_ok("heart.model_router.router"), "router import failed"

    def test_quota_tracker_imports(self):
        assert import_ok("heart.model_router.quota_tracker"), "quota_tracker import failed"

    def test_model_rotator_imports(self):
        assert import_ok("heart.model_router.model_rotator"), "model_rotator import failed"

    def test_get_best_model_returns_model(self):
        from heart.model_router.router import get_best_model
        model = get_best_model("general")
        assert model is not None
        # Returns dict with "id" key
        assert "id" in model, f"Expected dict with 'id' key, got: {type(model)} {model}"

    def test_get_best_model_for_task_returns_dict(self):
        from heart.model_router.model_rotator import get_best_model_for_task
        model = get_best_model_for_task("general")
        assert model is not None
        assert isinstance(model, dict)

    def test_model_registry_valid(self):
        registry = read_json("heart/model_router/model_registry.json")
        assert "models" in registry, "model_registry.json missing 'models' key"
        assert len(registry["models"]) > 0, "No models in registry"


class TestHeartCLI:
    def test_model_rotate_command(self):
        assert symlink_valid("model-rotate"), "model-rotate symlink missing"
