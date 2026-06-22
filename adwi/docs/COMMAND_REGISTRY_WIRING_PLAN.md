# CommandRegistry Live Wiring Plan
*Design note — prepared 2026-06-19. **IMPLEMENTED 2026-06-19/20 (Phases 7–23).***

---

## Current state (as of 2026-06-20)

`adwi/adwi_cli.py` dispatch is **dispatch-first via CommandRegistry**, with the legacy elif chain as fallback:

```
handle(line)
    │
    ├── _cmd_registry.dispatch(line, {})  ← checked first
    │       ├── match found → execute handler → return True
    │       └── no match   → return False
    │
    └── elif chain (legacy fallback for unregistered commands)
```

**Registry-dispatched clusters (Phases 7–23):** Gmail draft/editing/schedule/extract/triage/attachments/inbox, Remote/HA read-only, Diagnostics+viewer, Voice, Disk, System, Knowledge, Eval — 13 clusters, 320+ tests in `test_command_registry.py`.

**Intentionally NOT registered (`ELIF_ONLY`):** `/notify`, `/run-python`, `/run-bash`, `/implement-idea`, `/e2e-auto-loop` — these require interactive human confirmation and must stay in the elif chain. `TestElifFallbackIntegrity` and `TestSafetyBoundaryRegistry` enforce this continuously.

---

## Goal

Wire `CommandRegistry` into live dispatch so slash commands route through a single place. This:
- Removes the 177-branch `elif` chain
- Makes each command's metadata (risk, args, help) authoritative at dispatch time
- Enables future: tab-completion, `/capabilities` auto-generation, fine-tuning export, CommandRegistry → `_INTENT_SYSTEM` sync

---

## Proposed approach

### Phase 1: Parallel dispatch (safe, no regression risk)

Add at the top of `handle()`:
```python
if text.startswith("/"):
    cmd_name = text.split()[0]
    handler = _registry.lookup(cmd_name)  # returns None if not registered
    if handler is not None:
        args = text[len(cmd_name):].strip()
        return handler(args)
    # fall through to legacy elif chain
```

This lets us migrate one command at a time without touching the elif chain. The elif chain is the authoritative fallback until all commands are migrated.

### Phase 2: Incremental migration (low-risk commands first)

Migrate in this order:
1. `/help`, `/status` — read-only, no side effects
2. `/memory-stats`, `/memory-context`, `/backup-status` — read-only
3. `/model-status`, `/capabilities`, `/eval-routing` — read-only
4. `/test-adwi`, `/syntax-check`, `/validate-docs` — test/read
5. Then write-path commands with explicit confirmation gate checks

Skip: `/gmail-*`, `/aider`, `/patch-adwi`, `/e2e-auto-loop` — leave in elif until well-tested

### Phase 3: Remove elif chain

Only after every command is registered AND parallel dispatch has run clean for ≥1 eval cycle.

---

## Files to touch

| File | Change |
|------|--------|
| `adwi/adwi_cli.py` | Add registry lookup at top of `handle()`; migrate commands one by one |
| `adwi/simlab/tests/test_nlu_regex.py` | Add test that all `/commands` in `handle()` have a registry entry |
| `adwi/docs/NLU_REPAIR_BACKLOG.md` | Note this as a wiring item (not NLU) |

---

## What NOT to do

- Don't create a separate `command_registry.py` file — `CommandRegistry` already exists in `adwi_cli.py`
- Don't change risk-tier logic or confirmation gates during migration
- Don't auto-generate `_INTENT_SYSTEM` from registry yet (future phase)
- Don't delete the elif chain until all commands are verified in parallel dispatch

---

## Acceptance criteria

- `adwi/.venv/bin/python3 adwi/adwi_cli.py /test-adwi` → 4/4
- `adwi/.venv/bin/python3 adwi/adwi_cli.py /eval-routing` → 30/30
- `adwi/.venv/bin/python3 -m pytest adwi/simlab/tests -q` → same count or more
- No change in NLU pass rate (registry dispatch is slash-only, NLU path unchanged)
