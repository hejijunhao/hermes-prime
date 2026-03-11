# Task 9: Budget Tools — Completion

**Date:** 2026-03-11
**Status:** DONE
**Depends on:** Tasks 1–7 (all DONE), Task 8 (DONE — shares controller pattern)
**Blocks:** Task 10 (Overseer main loop)

---

## Summary

Implemented the two Overseer budget and model management tools in `hunter/tools/budget_tools.py`. These give the Overseer visibility into spending and control over the Hunter's model tier — the primary levers for cost optimisation.

With Tasks 8 and 9 complete, all 13 tools in the `hunter-overseer` toolset are now implemented and registered.

---

## What Was Built

### `hunter/tools/budget_tools.py` (~215 lines)

Two tool handlers + controller singleton + Elephantasm helper + model override path helper:

| Tool | Purpose | Wraps |
|------|---------|-------|
| `budget_status` | Full budget snapshot + spend history + daily breakdown | `BudgetManager.reload()`, `.check_budget()`, `.get_spend_history()`, `.get_daily_summary()` |
| `hunter_model_set` | Change Hunter's LLM model, persist to file, optional immediate redeploy | File write + optional `HunterController.redeploy()` |

### Integration

- **`model_tools.py`** — added `"hunter.tools.budget_tools"` to the `_modules` discovery list
- **`toolsets.py`** — already listed both tools in `hunter-overseer` (no change needed)

---

## Design Decisions

### File-based model persistence

Model override is written to `~/.hermes/hunter/model_override.txt`. This survives both Hunter and Overseer restarts. The `runner.py` will read this file on startup (wired up in Task 10).

The path helper `_get_model_override_path()` lives in `budget_tools.py` for now. It can be moved to `hunter/config.py` in a future cleanup for consistency with other path helpers.

### Proactive response enrichment

`budget_status` returns `recent_spend` (last 5 entries) and `daily_breakdown` in a single call. This avoids the need for separate history/summary tools and gives the Overseer full context to make model-switching decisions in one tool call.

### Graceful redeploy failure

When `apply_immediately=True` and the redeploy fails (e.g., budget exhausted), the model file is still written but the response includes `redeployment_error` alongside `redeployed: false`. The model change takes effect on the next spawn/redeploy — no data is lost.

### Contextual notes

The response includes a `note` field that varies based on state:
- Hunter running, no immediate apply: `"Model change takes effect on next redeploy or spawn."`
- No Hunter running: `"Model change takes effect on next spawn."`

This helps the Overseer LLM understand what to do next without needing a follow-up status check.

---

## Tests

### `tests/test_hunter_budget_tools.py` — 27 tests, all passing

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestGetController` | 3 | Lazy init, caching, test override |
| `TestBudgetStatus` | 6 | Normal status, exhausted, alert threshold, recent spend, daily breakdown, no ledger |
| `TestHunterModelSet` | 8 | Basic set, missing/empty model, captures old model, apply immediately (running), apply immediately (not running), budget error on redeploy, note when running, Elephantasm logging |
| `TestModelOverridePath` | 2 | Path under hunter home, consistent across calls |
| `TestToolRegistration` | 4 | Both tools registered, correct toolset, model_set requires model, OpenAI format |
| `TestDispatchIntegration` | 3 | Dispatch budget_status, dispatch model_set, unexpected exception handling |

---

## Files Modified

| File | Change |
|------|--------|
| `hunter/tools/budget_tools.py` | Full implementation (~215 lines, was 8-line stub) |
| `model_tools.py` | Added `"hunter.tools.budget_tools"` to `_modules` |
| `tests/test_hunter_budget_tools.py` | New test file (27 tests) |

---

## All 13 Overseer Tools Now Complete

| # | Tool | Task | Status |
|---|------|------|--------|
| 1 | `hunter_spawn` | 6 | DONE |
| 2 | `hunter_kill` | 6 | DONE |
| 3 | `hunter_status` | 6 | DONE |
| 4 | `hunter_inject` | 7 | DONE |
| 5 | `hunter_interrupt` | 7 | DONE |
| 6 | `hunter_logs` | 7 | DONE |
| 7 | `hunter_code_read` | 8 | DONE |
| 8 | `hunter_code_edit` | 8 | DONE |
| 9 | `hunter_diff` | 8 | DONE |
| 10 | `hunter_rollback` | 8 | DONE |
| 11 | `hunter_redeploy` | 8 | DONE |
| 12 | `budget_status` | 9 | DONE |
| 13 | `hunter_model_set` | 9 | DONE |
