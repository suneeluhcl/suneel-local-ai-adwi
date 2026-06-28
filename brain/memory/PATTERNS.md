# Patterns

## System Intelligence Pattern

For broad upgrade or self-improvement requests, inspect first, then refresh the system profile, audit, gap analysis, tool inventory, recommendations, and improvement plan. Use plain files and MCP resources so later agents can verify the state.

## Research Engine Pattern

Use `idea-run` for rough ideas that need planning. It creates capture, research-plan, analysis, and decision-draft files without installing tools or changing external services.

## Identity Voice Pattern

For user-facing output, use Suneel's voice: short, direct, casual, conversational, smart, structured, softened, and never harsh or condescending. Use autopilot for safe work and ask only for serious system risk or safety-gated actions.

## Adaptive Identity Pattern

Record meaningful accept/edit/reject/adjust signals in `dna/dna/identity/adaptive/feedback_log.json`. Extract repeated patterns into `signal_memory.json`, propose small updates in `pattern_updates.json`, and enforce `drift_guardrails.json` before any behavior shift.

## Anticipation Pattern

Record command and workflow events in `brain/anticipation/prediction_memory.json`. Use `brain/anticipation/behavior_patterns.json` and learned sequences to suggest next actions. Suggestions are planning hints only and must not auto-execute safety-gated work.

## Intent And Ranked Suggestions Pattern

Before acting, infer intent and store it in `brain/anticipation/current_context.json`. After meaningful actions, show only ranked top 3-5 next actions using `[HIGH]`, `[MED]`, or `[LOW]`. Filter suggestions by current intent and never auto-execute them.


---
*Added by memory curator — 2026-06-28*

## Anticipation Pattern Update

With the integration of Ollama and Hermes, we can now anticipate potential issues and suggest next actions more accurately. This pattern should be updated to reflect this new capability.

### Updated Content

* Record command and workflow events in `brain/anticipation/prediction_memory.json` with consideration for Ollama's repair and learning engines.

