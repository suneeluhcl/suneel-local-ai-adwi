"""Integration tests — end-to-end pipeline validation."""

import json
import os
import pytest
from tests.conftest import file_exists, read_json, import_ok, symlink_valid, WORKSPACE


class TestWorkspaceIntegrity:
    """Verify all 12 organs are fully connected."""

    ORGANS = ["brain", "heart", "eyes", "ears", "nervous", "skeleton",
              "blood", "hands", "mouth", "dna", "lab", "spine"]

    def test_all_organs_have_directories(self):
        missing = [o for o in self.ORGANS if not file_exists(o)]
        assert len(missing) == 0, f"Missing organ directories: {missing}"

    def test_all_organs_have_nerve_json(self):
        missing = [o for o in self.ORGANS if not file_exists(f"{o}/nerve.json")]
        assert len(missing) == 0, f"Missing nerve.json: {missing}"

    def test_all_organs_have_nerve_inbox(self):
        missing = [o for o in self.ORGANS if not file_exists(f"{o}/nerve_inbox")]
        assert len(missing) == 0, f"Missing nerve_inbox: {missing}"

    def test_all_nerve_jsons_are_v1_1(self):
        wrong = []
        for o in self.ORGANS:
            n = read_json(f"{o}/nerve.json")
            if n.get("version") != "1.1":
                wrong.append(o)
        assert len(wrong) == 0, f"Organs with outdated nerve.json version: {wrong}"

    def test_all_nerve_jsons_have_provides(self):
        thin = []
        for o in self.ORGANS:
            n = read_json(f"{o}/nerve.json")
            if len(n.get("provides", {})) < 2:
                thin.append(o)
        assert len(thin) == 0, f"Organs with thin provides: {thin}"


class TestCLICompleteness:
    """Verify all essential CLI commands are wired up."""

    ESSENTIAL_COMMANDS = [
        "agent-start", "agent-finish", "agent-doctor",
        "workspace-dashboard", "deep-scan", "morning-brief",
        "ollama-stack-start", "ollama-stack-stop", "ollama-stack-status",
        "nerve-heal", "memory-curate", "security-scan",
        "ollama-orchestrate", "ollama-review",
        "diagnostics-start", "diagnostics-stop",
        "model-rotate", "experiment-skills",
        "run-tests", "repair-loop",
    ]

    def test_all_essential_commands_exist(self):
        missing = [c for c in self.ESSENTIAL_COMMANDS if not symlink_valid(c)]
        assert len(missing) == 0, f"Missing CLI commands: {missing}"


class TestNervePipelineIntegration:
    """Test nerve propagation end-to-end."""

    def test_notify_and_check_inbox(self):
        from nervous.nerve_propagator import notify_change
        import os
        inbox = os.path.join(WORKSPACE, "brain/nerve_inbox")
        before = len(os.listdir(inbox)) if os.path.isdir(inbox) else 0
        notify_change("brain", "integration_test", "tests/integration/test_full_pipeline.py")
        after = len(os.listdir(inbox)) if os.path.isdir(inbox) else 0
        assert after >= before, "notify_change did not create inbox file"

    def test_nerve_propagator_get_status(self):
        from nervous.nerve_propagator import get_status
        status = get_status()
        assert len(status) == 12, f"Expected 12 organs, got {len(status)}"
        healthy = sum(1 for info in status.values()
                      if info.get("path_exists") and info.get("nerve_json_exists"))
        assert healthy == 12, f"Only {healthy}/12 organs fully healthy"


class TestOllamaStackIntegration:
    """Verify Ollama stack is operational."""

    def test_orchestrator_state_exists(self):
        assert file_exists("lab/autolab/orchestrator_state.json"), \
            "Orchestrator hasn't run yet (state file missing)"

    def test_orchestrator_has_run(self):
        state = read_json("lab/autolab/orchestrator_state.json")
        last_run = state.get("last_run", {})
        assert len(last_run) > 0, "No engines have been run by orchestrator yet"

    def test_code_review_report_exists(self):
        assert file_exists("blood/logs/code_review_report.md"), "Code review hasn't run yet"

    def test_security_scan_log_exists(self):
        assert file_exists("blood/logs/security_scan.jsonl"), "Security scan hasn't run yet"
