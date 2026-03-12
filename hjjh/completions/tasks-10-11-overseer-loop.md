# Tasks 10 & 11: Overseer Loop + System Prompt — Completion

**Date:** 2026-03-12
**Status:** DONE — 71/71 tests passing, 0 regressions across 286 hunter tests
**Depends on:** Tasks 1–9 (all DONE)
**Blocks:** Task 12 (CLI integration)

---

## Summary

Implemented the Overseer's continuous monitoring loop (`OverseerLoop` in `hunter/overseer.py`) and the system prompt + reference documents that guide its behaviour. Together these form the "brain" of the Overseer — the component that uses the 13 tools from Tasks 6–9 to monitor, evaluate, and improve the Hunter.

---

## What Was Built

### Task 11: System Prompt & Reference Docs

**Files created:**

| File | Lines | Purpose |
|------|-------|---------|
| `hunter/prompts/overseer_system.md` | ~95 | Main system prompt: identity, intervention modes, decision framework, tool reference, rules |
| `hunter/prompts/references/budget-management.md` | ~45 | Model tier selection table, budget strategies at 3 thresholds |
| `hunter/prompts/references/intervention-strategy.md` | ~60 | When/how to intervene, sizing ladder, monitoring protocol, anti-patterns |

**Prompt loading function** in `hunter/overseer.py`:
- `_load_overseer_system_prompt()` — reads main prompt + appends all reference files from `references/` dir sorted alphabetically
- Raises `FileNotFoundError` if main prompt missing, tolerates missing `references/` dir

**Design decision — bundled files, not skills:** Reference docs are loaded directly from the package rather than using the Hermes skills system. This avoids adding the `skills` toolset to the Overseer (which would add 16+ extra tools and break the focused `hunter-overseer` tool surface).

### Task 10: Overseer Main Loop

**File:** `hunter/overseer.py` (~300 lines, replaced 12-line stub)

**Class: `OverseerLoop`**

Constructor parameters:
- `model` — LLM the Overseer itself uses (default: `anthropic/claude-opus-4.6`)
- `budget` — optional `BudgetManager` (created in `_setup()` if None)
- `memory` — optional `OverseerMemoryBridge` (created in `_setup()` if None)
- `controller` — optional `HunterController` (created in `_setup()` if None)
- `check_interval` — seconds between iterations (default 30)
- `history_max_messages` / `history_keep_messages` — conversation trim thresholds (40/20)

**Methods:**

| Method | Purpose |
|--------|---------|
| `run()` | Main loop — blocks until KeyboardInterrupt or `stop()`. Catches per-iteration errors without crashing. |
| `stop()` | Signal loop to exit after current iteration |
| `_setup()` | One-time init: create shared controller, inject into tool modules, ensure animas/budget/worktree, create AIAgent |
| `_create_agent()` | Build AIAgent with `hunter-overseer` toolset, quiet mode, skip context files/memory |
| `_iteration()` | Single loop step: budget check → memory inject → build prompt → run agent → update history → extract decision → record spend |
| `_build_iteration_prompt()` | Build user message with budget summary, Hunter status, recent logs, task options |
| `_shutdown()` | Extract final event, close memory bridge |

**Critical design decision — shared controller injection:**

Each tool module (`process_tools`, `inject_tools`, `code_tools`, `budget_tools`) has its own lazy `_controller` singleton. Without intervention, calling `hunter_spawn` via the tool registry creates a Hunter tracked by `process_tools._controller`, but the loop's `_controller.get_status()` would report "no Hunter spawned" — a split-brain problem.

**Solution:** `_setup()` creates one shared `HunterController` and injects it into all four tool modules via their `_set_controller()` functions. This ensures the loop and tools operate on the same process state.

**Conversation history management:** Only user/assistant message pairs are tracked (not internal tool_call/tool messages from `result["messages"]`). This prevents rapid context inflation. History is trimmed to the last `history_keep_messages` when it exceeds `history_max_messages`. Elephantasm memory provides long-term continuity beyond the trim window.

**Agent configuration:**
- `enabled_toolsets=["hunter-overseer"]` — only the 13 Overseer tools
- `max_iterations=20` per loop iteration (budget resets each `run_conversation()` call)
- `skip_context_files=True` — no AGENTS.md/SOUL.md pollution
- `skip_memory=True` — uses Elephantasm, not MEMORY.md
- `quiet_mode=True` — no progress output

**Spend tracking:** Overseer records its own API spend using rough token estimates (4000 input + 1000 output per API call). Actual token tracking would require AIAgent to expose usage data (future improvement).

---

## Tests

### `tests/test_hunter_overseer_prompts.py` — 18 tests, ALL PASSING

| Group | Count | What's tested |
|-------|-------|---------------|
| Real prompt files | 4 | Files exist on disk |
| Prompt content | 8 | Role, intervention modes, rules, decision framework, tool refs, references appended, dividers |
| Load function | 2 | `_load_overseer_system_prompt()` returns correct content |
| Edge cases | 4 | Missing refs dir OK, missing main raises, alphabetical sort, empty refs dir |

### `tests/test_hunter_overseer.py` — 53 tests, ALL PASSING

All tests mock `AIAgent` (no LLM calls) and use mock fixtures for `BudgetManager`, `OverseerMemoryBridge`, `HunterController`.

| Group | Count | What's tested |
|-------|-------|---------------|
| Setup | 10 | ensure_hunter_home, budget config, worktree, animas, controller injection into 4 tool modules, agent creation, non-fatal failures, provided controller |
| Iteration | 15 | Budget reload/check, hard stop kills Hunter + skips agent, memory inject, ephemeral prompt update, run_conversation called, history append, decision extract, spend recording, count increment, no-memory mode, zero-cost edge cases |
| History | 4 | Grows, trimmed at threshold, keeps recent, passed to agent |
| Prompt building | 8 | Budget summary, alert warning, Hunter running/stopped, logs, task section, iteration number |
| Run/shutdown | 7 | stop(), shutdown events, memory close, no-memory shutdown, running flag, error resilience, error extraction |
| Agent creation | 6 | Toolsets, quiet mode, skip flags, session ID format, model passthrough |
| First run | 2 | "not running" in prompt, spawn suggestion |

**Fix applied:** `test_iteration_error_extracted_to_memory` had a hanging bug — the test wrapper called `overseer.stop()` after `original_iteration()`, but when `run_conversation` raised `RuntimeError`, the exception propagated before `stop()` was reached, leaving `_running=True` and the loop spinning forever. Fixed by wrapping in `try/finally` so `stop()` is always called.

---

## Remaining Work

1. ~~**Fix loop tests**~~ — DONE (53/53 passing)
2. ~~**Update changelog**~~ — DONE (1.7.0 + 1.8.0 entries added)
3. **Write plan doc** — save implementation plan to `hjjh/plans/tasks-10-11-implementation-plan.md` (plan exists at `/Users/philippholke/.claude/plans/validated-mixing-walrus.md`)
4. **Update memory** — update `MEMORY.md` with Task 10/11 status
5. ~~**Run full test suite**~~ — DONE (286/286 hunter tests passing, 0 regressions)

---

## Files Modified/Created

| File | Action |
|------|--------|
| `hunter/prompts/overseer_system.md` | CREATED |
| `hunter/prompts/references/budget-management.md` | CREATED |
| `hunter/prompts/references/intervention-strategy.md` | CREATED |
| `hunter/overseer.py` | REWRITTEN (stub → ~300 lines) |
| `tests/test_hunter_overseer_prompts.py` | CREATED (~120 lines, 18 tests) |
| `tests/test_hunter_overseer.py` | CREATED (~500 lines, ~47 tests) |
