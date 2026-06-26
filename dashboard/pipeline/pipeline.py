"""CC.2 — 6-stage execution pipeline with live WebSocket streaming.

Stages:
  1. brainstorm  — explore intent, extract goals
  2. plan        — build structured action plan
  3. confirm     — present plan to user (WebSocket confirm gate)
  4. implement   — execute each action
  5. test        — validate outputs
  6. wire        — commit, update workspace state
"""

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STAGES = ["brainstorm", "plan", "confirm", "implement", "test", "wire"]
STAGE_ICONS = {
    "brainstorm": "🧠",
    "plan": "📋",
    "confirm": "✋",
    "implement": "⚙️",
    "test": "🧪",
    "wire": "🔗",
}


class Pipeline:
    def __init__(
        self,
        client_id: str,
        prompt: str,
        mode: str,
        send_fn: Callable[[dict], Awaitable[None]],
        confirm_fn: Callable[[dict], Awaitable[bool]],
    ) -> None:
        self.client_id = client_id
        self.prompt = prompt
        self.mode = mode  # "full" | "brainstorm"
        self._send = send_fn
        self._confirm = confirm_fn
        self.started_at = time.monotonic()
        self.stages_completed: list[str] = []
        self.plan: dict = {}
        self.results: list[dict] = {}

    # ── Messaging helpers ─────────────────────────────────────────────────────

    async def _msg(self, msg_type: str, **kwargs: Any) -> None:
        await self._send({"type": msg_type, "ts": datetime.now().isoformat(), **kwargs})

    async def _log(self, level: str, icon: str, content: str) -> None:
        await self._msg("log", level=level, icon=icon, content=content)

    async def _set_stage(self, stage: str, status: str = "active") -> None:
        await self._msg("stage", stage=stage, status=status)

    async def _progress(self, stage: str, pct: int, label: str = "") -> None:
        await self._msg("progress", stage=stage, pct=pct, label=label)

    # ── Stage 1: Brainstorm ───────────────────────────────────────────────────

    async def _brainstorm(self) -> dict:
        await self._set_stage("brainstorm")
        await self._log("info", "🧠", f"Brainstorming: {self.prompt[:80]}")
        await self._progress("brainstorm", 20, "Extracting intent...")

        # Classify intent via dispatcher
        intent_data: dict = {}
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "dispatcher"))
            from intent_classifier import classify
            results = classify(self.prompt)
            if results:
                name, conf, entry = results[0]
                intent_data = {
                    "intent": name,
                    "confidence": round(conf, 3),
                    "command": entry.get("command", ""),
                    "description": entry.get("description", ""),
                }
                await self._log("info", "🎯", f"Intent: {name} ({int(conf*100)}% confidence)")
        except Exception as e:
            await self._log("warn", "⚠️", f"Intent classification skipped: {e}")

        # Pull brain context
        brain_context = ""
        try:
            sys.path.insert(0, os.path.join(WORKSPACE, "tools"))
            from brain_injector import inject
            brain_context = inject(self.prompt)
            if brain_context:
                await self._log("info", "📚", "Brain context injected from Obsidian vault")
        except Exception:
            pass

        await self._progress("brainstorm", 100, "Done")
        await self._set_stage("brainstorm", "done")

        return {
            "intent_data": intent_data,
            "brain_context": brain_context,
            "prompt": self.prompt,
        }

    # ── Stage 2: Plan ─────────────────────────────────────────────────────────

    async def _plan(self, brainstorm_result: dict) -> dict:
        await self._set_stage("plan")
        await self._log("info", "📋", "Building action plan...")
        await self._progress("plan", 30, "Structuring steps...")

        intent_data = brainstorm_result.get("intent_data", {})
        command = intent_data.get("command", "")
        description = intent_data.get("description", f"Execute: {self.prompt[:60]}")

        steps = []
        if command:
            steps.append({
                "id": 1,
                "action": description,
                "command": command,
                "args": intent_data.get("args", []),
                "safe": True,
            })
        else:
            # No matched command — suggest workspace doctor as fallback
            steps.append({
                "id": 1,
                "action": f"Run workspace health check (no specific command matched for: {self.prompt[:50]})",
                "command": "agent-doctor",
                "args": [],
                "safe": True,
            })

        plan = {
            "title": description,
            "prompt": self.prompt,
            "steps": steps,
            "estimated_steps": len(steps),
            "brain_context_available": bool(brainstorm_result.get("brain_context")),
        }
        await self._progress("plan", 100, f"{len(steps)} step(s) planned")
        await self._set_stage("plan", "done")
        return plan

    # ── Stage 3: Confirm ──────────────────────────────────────────────────────

    async def _confirm_stage(self, plan: dict) -> bool:
        await self._set_stage("confirm")
        await self._log("info", "✋", "Waiting for plan approval...")
        approved = await self._confirm(plan)
        if approved:
            await self._log("info", "✅", "Plan approved — proceeding")
            await self._set_stage("confirm", "done")
        else:
            await self._log("warn", "❌", "Plan rejected — stopping")
            await self._set_stage("confirm", "skipped")
        return approved

    # ── Stage 4: Implement ────────────────────────────────────────────────────

    async def _implement(self, plan: dict) -> list[dict]:
        await self._set_stage("implement")
        results = []
        steps = plan.get("steps", [])
        bin_dir = os.path.join(WORKSPACE, "bin")

        for i, step in enumerate(steps):
            cmd_name = step.get("command", "")
            args = step.get("args", [])
            pct = int((i / max(len(steps), 1)) * 90) + 5
            await self._progress("implement", pct, f"Step {i+1}/{len(steps)}: {step.get('action','')[:40]}")
            await self._log("info", "⚙️", f"Running: {cmd_name} {' '.join(str(a) for a in args)}")

            bin_path = os.path.join(bin_dir, cmd_name)
            cmd = [bin_path] + [str(a) for a in args] if os.path.exists(bin_path) else [cmd_name] + [str(a) for a in args]

            t0 = time.monotonic()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=WORKSPACE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                duration_ms = int((time.monotonic() - t0) * 1000)
                out = (stdout or b"").decode("utf-8", errors="replace")
                err = (stderr or b"").decode("utf-8", errors="replace")
                success = proc.returncode == 0
                if out:
                    for line in out.splitlines()[:20]:
                        await self._log("output", "  ", line)
                if not success and err:
                    await self._log("error", "✗", err[:200])
                status = "success" if success else "fail"
                await self._log("info" if success else "error", "✓" if success else "✗",
                                f"Step {i+1} {status} ({duration_ms}ms)")
                results.append({"step": i+1, "command": cmd_name, "status": status,
                                 "duration_ms": duration_ms, "stdout": out[:500]})
                # Write telemetry trace
                _write_telemetry(cmd_name, status, duration_ms)
            except asyncio.TimeoutError:
                await self._log("error", "⏱", f"Step {i+1} timed out after 120s")
                results.append({"step": i+1, "command": cmd_name, "status": "fail", "reason": "timeout"})
            except Exception as e:
                await self._log("error", "✗", f"Step {i+1} error: {e}")
                results.append({"step": i+1, "command": cmd_name, "status": "fail", "reason": str(e)})

        await self._progress("implement", 100, "Complete")
        await self._set_stage("implement", "done")
        return results

    # ── Stage 5: Test ─────────────────────────────────────────────────────────

    async def _test(self, impl_results: list[dict]) -> dict:
        await self._set_stage("test")
        await self._log("info", "🧪", "Validating outputs...")
        await self._progress("test", 50, "Checking results...")

        passed = sum(1 for r in impl_results if r.get("status") == "success")
        failed = len(impl_results) - passed
        outcome = "pass" if failed == 0 else "partial" if passed > 0 else "fail"

        await self._log(
            "info" if outcome == "pass" else "warn",
            "✓" if outcome != "fail" else "✗",
            f"Test: {passed} passed, {failed} failed → {outcome.upper()}"
        )
        await self._progress("test", 100, outcome.upper())
        await self._set_stage("test", "done")
        return {"outcome": outcome, "passed": passed, "failed": failed}

    # ── Stage 6: Wire ─────────────────────────────────────────────────────────

    async def _wire(self, plan: dict, impl_results: list[dict], test_result: dict) -> dict:
        await self._set_stage("wire")
        await self._log("info", "🔗", "Wiring workspace state...")
        await self._progress("wire", 50, "Updating session handoff...")

        # Update SESSION_HANDOFF.md
        handoff_path = os.path.join(WORKSPACE, "agent-system", "memory", "SESSION_HANDOFF.md")
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = (
                f"\n## Control Center — {ts}\n"
                f"**Prompt:** {plan.get('prompt','')[:100]}\n"
                f"**Outcome:** {test_result.get('outcome','unknown')}\n"
                f"**Steps:** {test_result.get('passed',0)} passed, {test_result.get('failed',0)} failed\n"
            )
            with open(handoff_path, "a") as f:
                f.write(entry)
            await self._log("info", "📝", "Session handoff updated")
        except Exception as e:
            await self._log("warn", "⚠️", f"Handoff update skipped: {e}")

        await self._progress("wire", 100, "Done")
        await self._set_stage("wire", "done")
        duration_ms = int((time.monotonic() - self.started_at) * 1000)
        return {
            "outcome": test_result.get("outcome", "unknown"),
            "duration_ms": duration_ms,
            "stages_completed": self.stages_completed,
        }

    # ── Orchestrator ──────────────────────────────────────────────────────────

    async def run(self) -> dict:
        try:
            # Stage 1
            brainstorm_result = await self._brainstorm()
            self.stages_completed.append("brainstorm")

            if self.mode == "brainstorm":
                await self._msg("result", outcome="brainstorm_only",
                                 brain_context=brainstorm_result.get("brain_context", ""),
                                 intent=brainstorm_result.get("intent_data", {}))
                return {"outcome": "brainstorm_only", "stages_completed": self.stages_completed}

            # Stage 2
            plan = await self._plan(brainstorm_result)
            self.stages_completed.append("plan")
            self.plan = plan

            # Stage 3
            approved = await self._confirm_stage(plan)
            self.stages_completed.append("confirm")
            if not approved:
                return {"outcome": "rejected", "stages_completed": self.stages_completed, "duration_ms": int((time.monotonic() - self.started_at) * 1000)}

            # Stage 4
            impl_results = await self._implement(plan)
            self.stages_completed.append("implement")

            # Stage 5
            test_result = await self._test(impl_results)
            self.stages_completed.append("test")

            # Stage 6
            wire_result = await self._wire(plan, impl_results, test_result)
            self.stages_completed.append("wire")

            await self._msg("result", **wire_result)
            return wire_result

        except Exception as e:
            await self._msg("error", message=f"Pipeline crashed: {e}")
            return {"outcome": "error", "stages_completed": self.stages_completed,
                    "duration_ms": int((time.monotonic() - self.started_at) * 1000)}


def _write_telemetry(task_type: str, outcome: str, duration_ms: int) -> None:
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "agent-system", "telemetry"))
        from telemetry_writer import write_trace
        write_trace("control_center", task_type, outcome, duration_ms)
    except Exception:
        pass
