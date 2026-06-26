"""Tests for P3.5 DAG validator and runner."""

import sys
import tempfile
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE / "orchestrator" / "dag"))

from dag_validator import validate


VALID_PIPELINE = """
name: test_pipeline
steps:
  - id: step_a
    command: agent-doctor
    execution_level: SAFE
  - id: step_b
    command: agent-doctor
    depends_on: [step_a]
    execution_level: SAFE
"""

CYCLE_PIPELINE = """
name: cycle_test
steps:
  - id: step_a
    command: agent-doctor
    depends_on: [step_b]
    execution_level: SAFE
  - id: step_b
    command: agent-doctor
    depends_on: [step_a]
    execution_level: SAFE
"""

MISSING_DEP_PIPELINE = """
name: missing_dep
steps:
  - id: step_a
    command: agent-doctor
    depends_on: [nonexistent]
    execution_level: SAFE
"""

INVALID_LEVEL_PIPELINE = """
name: bad_level
steps:
  - id: step_a
    command: agent-doctor
    execution_level: SUPERMODE
"""


def _write_tmp(content: str) -> str:
    import tempfile, os
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    f.write(content)
    f.close()
    return f.name


def test_valid_pipeline_passes():
    path = _write_tmp(VALID_PIPELINE)
    ok, errors = validate(path)
    assert ok, f"Expected PASS but got errors: {errors}"
    assert errors == []


def test_cycle_detected():
    path = _write_tmp(CYCLE_PIPELINE)
    ok, errors = validate(path)
    assert not ok
    assert any("circular" in e.lower() or "cycle" in e.lower() for e in errors)


def test_missing_dep_detected():
    path = _write_tmp(MISSING_DEP_PIPELINE)
    ok, errors = validate(path)
    assert not ok
    assert any("nonexistent" in e for e in errors)


def test_invalid_execution_level():
    path = _write_tmp(INVALID_LEVEL_PIPELINE)
    ok, errors = validate(path)
    assert not ok
    assert any("execution_level" in e or "SUPERMODE" in e for e in errors)


def test_seed_pipelines_valid():
    """All 3 seed pipelines must pass validation."""
    pipelines_dir = WORKSPACE / "orchestrator" / "dag" / "pipelines"
    for yaml_file in pipelines_dir.glob("*.yaml"):
        ok, errors = validate(str(yaml_file))
        assert ok, f"Pipeline {yaml_file.name} failed: {errors}"


def test_empty_pipeline_fails():
    path = _write_tmp("name: empty\nsteps: []\n")
    ok, errors = validate(path)
    assert not ok
    assert any("no steps" in e.lower() for e in errors)
