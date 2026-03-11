# Task 1: Package Scaffolding — Completion Notes

**Status:** Complete
**Date:** 2026-03-11

---

## What Was Done

Created the `hunter/` Python package with the full module structure needed for Phase 1. All modules are importable and the package is registered with setuptools.

---

## Files Created (14 source files)

### Package Core

| File | Purpose | Content |
|------|---------|---------|
| `hunter/__init__.py` | Package init | Version string (`0.1.0`), module docstring listing all submodules |
| `hunter/config.py` | **Paths, constants, defaults** | 10 path functions, 8 constants, `ensure_hunter_home()` — the single source of truth for all Hunter paths and config values |

### Stub Modules (to be implemented in later tasks)

| File | Task | Key Classes/Functions It Will Contain |
|------|------|---------------------------------------|
| `hunter/budget.py` | Task 2 | `BudgetManager`, `BudgetStatus` |
| `hunter/worktree.py` | Task 3 | `WorktreeManager` |
| `hunter/control.py` | Task 4 | `HunterProcess`, `HunterController`, `HunterStatus` |
| `hunter/runner.py` | Task 4 | `main()` entry point for the Hunter subprocess |
| `hunter/memory.py` | Task 5 | `AnimaManager`, `OverseerMemoryBridge`, `HunterMemoryBridge` |
| `hunter/overseer.py` | Task 10 | `OverseerLoop` |
| `hunter/cli.py` | Task 12 | `register_hunter_commands()`, `handle_hunter_command()` |

### Tool Stubs

| File | Task | Tools It Will Register |
|------|------|-----------------------|
| `hunter/tools/__init__.py` | — | Package init with module listing |
| `hunter/tools/process_tools.py` | Task 6 | `hunter_spawn`, `hunter_kill`, `hunter_status` |
| `hunter/tools/inject_tools.py` | Task 7 | `hunter_inject`, `hunter_interrupt`, `hunter_logs` |
| `hunter/tools/code_tools.py` | Task 8 | `hunter_code_edit`, `hunter_code_read`, `hunter_diff`, `hunter_rollback`, `hunter_redeploy` |
| `hunter/tools/budget_tools.py` | Task 9 | `budget_status`, `hunter_model_set` |

### Directory Created

| Path | Purpose |
|------|---------|
| `hunter/prompts/` | Will hold `overseer_system.md` (Task 11) |

---

## Files Modified (1 file)

### `pyproject.toml`

Three edits:

1. **Added `hunter` optional dependency group** (line 56):
   ```toml
   hunter = ["elephantasm"]
   ```
   This keeps `elephantasm` optional — only installed when the hunter subsystem is needed.

2. **Added `hermes-agent[hunter]` to the `all` extras** (line 70):
   ```toml
   "hermes-agent[hunter]",
   ```
   So `uv pip install -e ".[all,dev]"` installs elephantasm automatically.

3. **Added `hunter` and `hunter.tools` to setuptools package discovery** (line 80):
   ```toml
   include = ["tools", "hermes_cli", "gateway", "cron", "honcho_integration", "hunter", "hunter.tools"]
   ```
   This ensures setuptools finds and includes the hunter package when building/installing.

---

## `hunter/config.py` — Detailed Reference

This is the only substantive file (everything else is a stub). Here's what it defines:

### Path Functions

| Function | Returns | Example |
|----------|---------|---------|
| `get_hunter_home()` | Root for all hunter state | `~/.hermes/hunter/` |
| `get_hunter_worktree_path()` | Git worktree location | `~/.hermes/hunter/worktree/` |
| `get_hunter_state_db_path()` | Operational SQLite | `~/.hermes/hunter/state.db` |
| `get_budget_config_path()` | Watched budget YAML | `~/.hermes/hunter/budget.yaml` |
| `get_spend_ledger_path()` | Append-only spend log | `~/.hermes/hunter/spend.jsonl` |
| `get_injection_dir()` | Injection file directory | `~/.hermes/hunter/injections/` |
| `get_injection_path()` | Active injection file | `~/.hermes/hunter/injections/current.md` |
| `get_interrupt_flag_path()` | Interrupt signal file | `~/.hermes/hunter/interrupt.flag` |
| `get_hunter_log_dir()` | Process log directory | `~/.hermes/hunter/logs/` |
| `get_anima_cache_path()` | Elephantasm ID cache | `~/.hermes/hunter/animas.json` |

### `ensure_hunter_home()`

Creates three directories if they don't exist:
- `~/.hermes/hunter/`
- `~/.hermes/hunter/injections/`
- `~/.hermes/hunter/logs/`

Other paths (budget.yaml, spend.jsonl, state.db, worktree) are created by their respective modules when needed.

### Constants

| Constant | Value | Used By |
|----------|-------|---------|
| `HUNTER_BRANCH` | `"hunter/live"` | WorktreeManager (Task 3) |
| `HUNTER_DEFAULT_TOOLSETS` | `["hermes-cli"]` | HunterProcess spawn (Task 4) |
| `HUNTER_DEFAULT_MODEL` | `"qwen/qwen3.5-32b"` | HunterProcess spawn (Task 4) |
| `HUNTER_MAX_ITERATIONS` | `200` | HunterProcess spawn (Task 4) |
| `OVERSEER_ANIMA_NAME` | `"hermes-overseer"` | AnimaManager (Task 5) |
| `HUNTER_ANIMA_NAME` | `"hermes-hunter"` | AnimaManager (Task 5) |
| `OVERSEER_DEFAULT_CHECK_INTERVAL` | `30.0` | OverseerLoop (Task 10) |
| `OVERSEER_MAX_ITERATIONS_PER_LOOP` | `20` | OverseerLoop (Task 10) |

---

## Design Decisions

### Why `~/.hermes/hunter/` and not `~/.hermes/`?

Isolation. The hunter subsystem has its own state (budget, spend ledger, worktree, injection files, logs) that should not collide with the main Hermes agent's state. A dedicated subdirectory keeps things clean and makes cleanup trivial (`rm -rf ~/.hermes/hunter/`).

### Why `elephantasm` is an optional dependency

Not everyone using Hermes needs the hunter subsystem. Making it optional via `hunter = ["elephantasm"]` in `pyproject.toml` means:
- Standard Hermes users aren't forced to install elephantasm
- `uv pip install -e ".[all,dev]"` still gets it
- Individual installs via `uv pip install -e ".[hunter]"` work too

### Why stub files instead of creating modules on demand

Each Task in the implementation plan references specific modules by import path. Having the stubs in place means:
- Tasks can be worked on in parallel without import errors
- The full package structure is visible in the IDE from day one
- Each stub's docstring documents what it will contain and which task implements it

### Why `config.py` uses functions not constants for paths

Paths are computed from `get_hermes_home()` which reads `HERMES_HOME` env var. If we used module-level constants, they'd be frozen at import time and couldn't be overridden by tests or different environments. Functions re-evaluate each call.

---

## Verification

All 14 modules import successfully:
```
from hunter import __version__                    # "0.1.0"
from hunter.config import get_hunter_home         # ~/.hermes/hunter
from hunter.config import ensure_hunter_home      # Creates directories
from hunter.tools.process_tools import *          # (stub, no exports yet)
```

`ensure_hunter_home()` creates the expected directory tree at `~/.hermes/hunter/`.

---

## What's Next

**Task 2 (Budget System)** and **Task 3 (Worktree Manager)** can now be built in parallel — both depend only on `hunter/config.py` which is complete.

**Task 5 (Elephantasm Integration)** can also start in parallel once `elephantasm` is installed (`uv pip install -e ".[hunter]"`).
