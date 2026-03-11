# Task 7: Overseer Tools — Runtime Injection — Completion

**Status:** DONE
**Date:** 2026-03-11
**File:** `hunter/tools/inject_tools.py` (~240 lines)
**Tests:** `tests/test_hunter_inject_tools.py` — 33/33 passing

---

## What Was Built

Three Overseer tools registered in the `hunter-overseer` toolset, giving the Overseer runtime control over the Hunter without redeploying.

### hunter_inject

Pushes an instruction into the Hunter's next iteration via file-based IPC.

- **Parameters:** `instruction` (required string), `priority` (optional enum: normal/high/critical, default normal)
- **Behaviour:** Writes instruction to `~/.hermes/hunter/injections/current.md` with priority prefix. The Hunter's step_callback reads and consumes it on its next iteration, appending to the ephemeral system prompt.
- **Priority prefixes:** normal = none, high = `HIGH PRIORITY: `, critical = `CRITICAL — DROP CURRENT TASK: `
- **Returns:** `{"status": "injected", "priority": "...", "instruction_length": N}`
- **Error cases:** missing/empty instruction, invalid priority, file I/O failure — all return `{"error": "..."}`
- **Elephantasm:** Best-effort event logging via `_extract_overseer_event()`

### hunter_interrupt

Signals the Hunter to stop gracefully via the interrupt flag file.

- **Parameters:** `message` (optional string, default "Overseer requested interrupt.")
- **Behaviour:** Writes interrupt flag to `~/.hermes/hunter/interrupt.flag`. Waits up to 30s for the Hunter's step_callback to detect it and exit gracefully. Falls back to `controller.kill()` (SIGTERM → SIGKILL) on timeout.
- **Returns:** `{"status": "interrupted_gracefully", "message": "..."}` or `{"status": "force_killed", "message": "..."}` or `{"status": "no_hunter_running"}`
- **Race condition handling:** Checks `controller.current` after `is_running` to handle the case where the process exits between checks.

### hunter_logs

Returns recent Hunter stdout/stderr from the in-memory rolling buffer.

- **Parameters:** `tail` (optional integer, default 100)
- **Behaviour:** Delegates to `controller.get_logs(tail=N)`.
- **Returns:** `{"logs": "...", "lines": N, "hunter_running": bool}`

### Controller Singleton

Same pattern as `process_tools.py` — module-level `_controller` with `_get_controller()` / `_set_controller()`. Deferred imports avoid circular dependencies.

### Elephantasm Helper

`_extract_overseer_event(text, meta)` — best-effort memory logging. Gets the Overseer's Anima ID from the local cache, creates a temporary `OverseerMemoryBridge`, and calls `extract_decision()`. All exceptions are caught and logged at debug level. Never crashes.

---

## Files Modified

| File | Change |
|------|--------|
| `hunter/tools/inject_tools.py` | Full implementation replacing stub (~240 lines) |
| `model_tools.py` | Added `"hunter.tools.inject_tools"` to `_modules` discovery list |
| `tests/test_hunter_inject_tools.py` | New test file (33 tests) |
| `hjjh/completions/task-07-inject-tools.md` | This file |
| `hjjh/changelog.md` | Updated with 1.4.0 entry |

---

## Tests

33/33 passing across 7 test classes:

| Class | Tests | Coverage |
|-------|-------|----------|
| TestGetController | 3 | Lazy init, caching, test override |
| TestHunterInject | 10 | All priorities, missing/empty/invalid args, dir creation, overwrite, Elephantasm logging + error resilience |
| TestHunterInterrupt | 6 | No hunter, graceful exit, force kill, default message, flag file write, race condition |
| TestHunterLogs | 4 | Default tail, custom tail, empty output, JSON structure |
| TestToolRegistration | 6 | Registry presence, toolset, schema params for all three tools, OpenAI format |
| TestDispatchIntegration | 4 | Dispatch inject/interrupt/logs, unexpected exception handling |

---

## Design Decisions

- **File I/O tests use real filesystem:** The `_isolate_hermes_home` autouse fixture redirects `HERMES_HOME` to a temp dir, so inject/interrupt tests verify actual file writes without mocking `Path`.
- **Separate controller singleton:** Each tool module gets its own `_controller` instance (same type, independent lifecycle). Keeps test isolation clean and matches the established pattern.
- **Priority validation in handler:** Invalid priority values return a structured error rather than KeyError crash, keeping the LLM in the loop.
- **Interrupt uses `controller.current` property:** Public API instead of `controller._current` (improvement over the spec's suggestion).
- **`_extract_overseer_event` is fire-and-forget:** Creates a temporary bridge, extracts, closes. No persistent state. If Elephantasm is down or unconfigured, silently skipped.
