# Phase A: Backend Abstraction — Implementation Plan

## Goal

Introduce a `ControlBackend` / `WorktreeBackend` protocol layer and a controller factory so that all tool handlers go through a swappable backend. Ship with only the local backend — the abstraction is in place, the Fly.io backend comes in Phase B.

**By the end of Phase A:**
- All 337 existing tests pass unchanged (zero behavior change)
- Controller construction is centralized in a single factory
- `WorktreeManager` satisfies the `WorktreeBackend` protocol (including a new `push()` no-op)
- Protocol definitions document the interface contract for Phase B

---

## Prerequisites

- Phase 1 complete (Tasks 1–12, 337 tests passing)
- Python 3.11+ with active venv

---

## Design Decisions

### Why not wrap HunterController inside LocalControlBackend?

The self-recursive deployment doc proposes `LocalControlBackend` wrapping `HunterController` wrapping `HunterProcess` — three layers of delegation. But tools need `controller.worktree` and `controller.budget` directly, so the wrapper would need to expose everything the controller already exposes. This adds indirection without value.

Instead: define protocols that existing classes **already satisfy structurally** (via `typing.Protocol`), and add a factory to centralize construction. Phase B is where the real refactoring happens — either `HunterController` gets refactored to delegate to a `ControlBackend`, or a `FlyHunterController` is created as an alternative.

### What the factory replaces

Currently, the same 7-line construction block is duplicated in 6 places:

```python
# Duplicated in: process_tools, inject_tools, code_tools, budget_tools, overseer, cli
from hunter.budget import BudgetManager
from hunter.control import HunterController
from hunter.worktree import WorktreeManager

worktree = WorktreeManager()
budget = BudgetManager()
controller = HunterController(worktree=worktree, budget=budget)
```

After Phase A, all 6 become:

```python
from hunter.backends import create_controller
controller = create_controller()
```

### Protocol design: wide, not narrow

The doc's proposed `ControlBackend` only has `spawn/kill/get_status/get_logs/is_alive`. But tool handlers also access `controller.worktree`, `controller.budget`, `controller.current`, `controller.is_running`, `controller.redeploy()`, and `controller.history`. The protocol should match the actual usage, not an idealized minimal interface. We can narrow it in Phase B when we know what the remote backend actually needs.

---

## Task Overview

| # | Task | Depends On | Complexity |
|---|------|------------|------------|
| A1 | Protocol definitions (`hunter/backends/base.py`) | — | Low |
| A2 | WorktreeManager `push()` no-op | — | Trivial |
| A3 | Controller factory (`hunter/backends/__init__.py`) | A1 | Low |
| A4 | Update tool modules to use factory | A3 | Low |
| A5 | Update OverseerLoop to use factory | A3 | Low |
| A6 | Update CLI to use factory | A3 | Low |
| A7 | New tests (`tests/test_hunter_backends.py`) | A3 | Low |
| A8 | Verify all existing tests pass | A4–A7 | Trivial |

---

## Task A1: Protocol Definitions

**Goal:** Define `ControlBackend` and `WorktreeBackend` as `typing.Protocol` classes.

### File to create: `hunter/backends/base.py`

**`WorktreeBackend(Protocol)`** — matches `WorktreeManager`'s public API:

| Method / Property | Signature | Notes |
|---|---|---|
| `worktree_path` | `Path` (attribute) | Needed by `HunterController.spawn()` |
| `branch` | `str` (attribute) | Informational |
| `setup()` | `-> None` | Idempotent setup |
| `teardown()` | `-> None` | Remove worktree |
| `is_setup()` | `-> bool` | Branch + worktree exist? |
| `is_clean()` | `-> bool` | No uncommitted changes? |
| `read_file(path)` | `-> str` | Read from worktree |
| `write_file(path, content)` | `-> None` | Write to worktree |
| `edit_file(path, old_str, new_str)` | `-> bool` | Find-and-replace |
| `delete_file(path)` | `-> bool` | Delete file |
| `list_files(dir, pattern)` | `-> List[str]` | Glob search |
| `commit(message, files)` | `-> str` | Stage + commit, return hash |
| `rollback(commit)` | `-> None` | Hard reset |
| `diff(staged)` | `-> str` | Show changes |
| `diff_since(commit)` | `-> str` | Compare to HEAD |
| `get_head_commit()` | `-> str` | Current HEAD hash |
| `get_recent_commits(n)` | `-> List[CommitInfo]` | Last N commits |
| `push()` | `-> None` | **New.** No-op for local, git push for remote |

**`ControlBackend(Protocol)`** — matches `HunterController`'s public API as used by tools:

| Method / Property | Signature | Notes |
|---|---|---|
| `worktree` | `WorktreeBackend` (attribute) | Code tools access this directly |
| `budget` | `BudgetManager` (attribute) | Budget tools access this directly |
| `spawn(model, instruction, resume, session_id, detach)` | `-> HunterProcess` | Deploy new Hunter |
| `kill()` | `-> bool` | Three-stage shutdown |
| `redeploy(resume_session, model)` | `-> HunterProcess` | Kill + restart |
| `get_status()` | `-> HunterStatus` | Health snapshot |
| `get_logs(tail)` | `-> str` | Recent output |
| `is_running` | `bool` (property) | Quick alive check |
| `current` | `Optional[HunterProcess]` (property) | Current/recent process |
| `history` | `List[Dict]` (property) | Past run summaries |

**Import strategy:** Use `from __future__ import annotations` and `TYPE_CHECKING` guard for `HunterStatus`, `HunterProcess`, `BudgetManager`, `CommitInfo` to avoid circular imports. These are only needed for type annotations, not runtime.

### Acceptance criteria
- File exists with both protocols
- `mypy` (if available) accepts the protocols
- No runtime imports of control.py, budget.py, or worktree.py from base.py

---

## Task A2: WorktreeManager `push()` No-Op

**Goal:** Add `push()` to `WorktreeManager` so it structurally satisfies `WorktreeBackend`.

### File to modify: `hunter/worktree.py`

Add to the git operations section:

```python
def push(self) -> None:
    """Push commits to remote. No-op for local worktrees."""
    logger.debug("Local worktree: push() is a no-op")
```

### Acceptance criteria
- Method exists and is callable
- Does not perform any git operations
- Existing 20 worktree tests still pass

---

## Task A3: Controller Factory

**Goal:** Centralize controller construction in a factory function with backend selection.

### Files to create

**`hunter/backends/__init__.py`:**

```python
def create_controller(
    mode: str = "auto",
    budget: "BudgetManager" = None,
) -> "HunterController":
    """Create a HunterController with the appropriate backends.

    Args:
        mode: Backend mode. "auto" detects from environment.
              "local" for subprocess + worktree. "fly" for Fly.io (Phase B).
        budget: Pre-configured BudgetManager. Created if None.

    Returns:
        A configured HunterController.
    """
```

**Auto-detection logic:**
```python
if mode == "auto":
    mode = "fly" if os.environ.get("FLY_APP_NAME") else "local"
```

**For Phase A:** Only "local" is implemented. "fly" raises `NotImplementedError("Fly.io backend not yet implemented (Phase B)")`.

**Local construction:**
```python
# Deferred imports to avoid circular deps
from hunter.budget import BudgetManager
from hunter.control import HunterController
from hunter.worktree import WorktreeManager

worktree = WorktreeManager()
if budget is None:
    budget = BudgetManager()
return HunterController(worktree=worktree, budget=budget)
```

The `budget` parameter exists because `OverseerLoop` creates its own `BudgetManager` and needs to share it with the controller.

### Acceptance criteria
- `create_controller()` returns a working `HunterController`
- `create_controller(mode="local")` works
- `create_controller(mode="fly")` raises `NotImplementedError`
- `create_controller(budget=existing_mgr)` passes the budget through

---

## Task A4: Update Tool Modules

**Goal:** Replace the duplicated `_get_controller()` in all 4 tool modules with the factory.

### Files to modify

**All 4 files** (`process_tools.py`, `inject_tools.py`, `code_tools.py`, `budget_tools.py`):

Replace:
```python
def _get_controller():
    global _controller
    if _controller is None:
        from hunter.budget import BudgetManager
        from hunter.control import HunterController
        from hunter.worktree import WorktreeManager

        worktree = WorktreeManager()
        budget = BudgetManager()
        _controller = HunterController(worktree=worktree, budget=budget)
    return _controller
```

With:
```python
def _get_controller():
    global _controller
    if _controller is None:
        from hunter.backends import create_controller
        _controller = create_controller()
    return _controller
```

**`_set_controller()` stays exactly as-is** — tests depend on it for mock injection.

### Acceptance criteria
- All 4 modules use the factory
- `_set_controller()` unchanged
- All 138 tool tests pass (29 + 33 + 49 + 27)

---

## Task A5: Update OverseerLoop

**Goal:** `_setup()` uses the factory instead of direct construction.

### File to modify: `hunter/overseer.py`

**In `_setup()`**, replace:
```python
worktree = WorktreeManager()
...
self._controller = self.controller or HunterController(
    worktree=worktree, budget=self.budget,
)
```

With:
```python
if self.controller is not None:
    self._controller = self.controller
else:
    from hunter.backends import create_controller
    self._controller = create_controller(budget=self.budget)
```

Keep the worktree setup check afterward:
```python
if not self._controller.worktree.is_setup():
    self._controller.worktree.setup()
```

**Remove** the top-level `from hunter.control import HunterController` and `from hunter.worktree import WorktreeManager` imports (they're now handled by the factory). Keep `from hunter.budget import BudgetManager` (used elsewhere in the file).

### Acceptance criteria
- OverseerLoop still works identically
- All 53 overseer tests pass
- No unnecessary imports at module level

---

## Task A6: Update CLI

**Goal:** `_cmd_spawn()` uses the factory.

### File to modify: `hunter/cli.py`

**In `_cmd_spawn()`**, replace:
```python
from hunter.budget import BudgetManager
from hunter.control import HunterController
from hunter.worktree import WorktreeManager

wt = WorktreeManager()
budget = BudgetManager()
controller = HunterController(worktree=wt, budget=budget)
```

With:
```python
from hunter.backends import create_controller
controller = create_controller()
```

**`_cmd_setup()` stays as-is** — it creates `WorktreeManager` and `BudgetManager` directly because setup is a bootstrapping operation that must work before the full system is ready.

### Acceptance criteria
- `hermes hunter spawn` works identically
- All 51 CLI tests pass

---

## Task A7: New Tests

**Goal:** Test the factory and protocol definitions.

### File to create: `tests/test_hunter_backends.py`

| Test | What it verifies |
|------|-----------------|
| `test_create_controller_local` | Returns a `HunterController` instance |
| `test_create_controller_auto_defaults_local` | Auto mode returns local when no `FLY_APP_NAME` |
| `test_create_controller_fly_not_implemented` | `mode="fly"` raises `NotImplementedError` |
| `test_create_controller_passes_budget` | Custom `BudgetManager` is used by the returned controller |
| `test_create_controller_invalid_mode` | Unknown mode raises `ValueError` |
| `test_worktree_manager_has_push` | `WorktreeManager` has a callable `push()` method |
| `test_push_is_noop` | `push()` doesn't raise or modify anything |
| `test_worktree_satisfies_protocol` | `WorktreeManager` is structurally compatible with `WorktreeBackend` |
| `test_controller_satisfies_protocol` | `HunterController` is structurally compatible with `ControlBackend` |

**Mock strategy:** Mock `WorktreeManager`, `BudgetManager` in factory tests to avoid real git/file operations. Use `tmp_path` for protocol satisfaction tests that need real instances.

### Acceptance criteria
- All new tests pass
- Tests don't write to `~/.hermes/` (use `_isolate_hermes_home` fixture)

---

## Task A8: Full Test Verification

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

All 337 + ~9 new = ~346 tests pass.

---

## Known Seams for Phase B

These are intentional gaps that Phase B will address:

1. **`inject_tools.py` file-based IPC** — writes directly to `get_injection_path()` and `get_interrupt_flag_path()`, bypassing the controller. Remote backends will need injection through the backend.

2. **`HunterController.spawn()` creates `HunterProcess` internally** — Phase B will need to delegate to `ControlBackend.spawn()` instead, or create `FlyHunterController` as an alternative implementation.

3. **`process_tools.py` accesses `process._pid`** (private attr) — Phase B should expose PID through a public interface or status dict.

4. **`WorktreeBackend.push()` is the only new method** — but for remote, `commit()` and `push()` are separate steps (edit locally, push to trigger remote redeploy). The Overseer's code tools will need to call `push()` after `commit()`.
