# Phase A: Backend Abstraction — Completion Report

## Goal

Introduce a `ControlBackend` / `WorktreeBackend` protocol layer and a controller factory so that all tool handlers go through a swappable backend. Ship with only the local backend — the abstraction is in place, the Fly.io backend comes in Phase B.

**Result:** All 349 tests pass (337 existing + 12 new). Zero behavior change. Six duplicated construction blocks consolidated into one factory call.

---

## Prerequisites Met

- Phase 1 complete (Tasks 1–12, 337 tests passing)
- Python 3.11+ with active venv

---

## Task A1: Protocol Definitions

**Goal:** Define `ControlBackend` and `WorktreeBackend` as `typing.Protocol` classes.

### File created: `hunter/backends/base.py` (101 lines)

Two `@runtime_checkable` Protocol classes that capture the interfaces tool handlers and the Overseer loop actually use:

**`WorktreeBackend(Protocol)`** — 2 attributes + 17 methods:

| Category | Members |
|----------|---------|
| Attributes | `worktree_path: Path`, `branch: str` |
| Setup | `setup()`, `teardown()`, `is_setup()`, `is_clean()` |
| File ops | `read_file()`, `write_file()`, `edit_file()`, `delete_file()`, `list_files()` |
| Git ops | `commit()`, `rollback()`, `diff()`, `diff_since()`, `get_head_commit()`, `get_recent_commits()`, `push()` |

**`ControlBackend(Protocol)`** — 2 attributes + 5 methods + 3 properties:

| Category | Members |
|----------|---------|
| Attributes | `worktree: WorktreeBackend`, `budget: BudgetManager` |
| Lifecycle | `spawn(model, instruction, resume, session_id, detach)`, `kill()`, `redeploy(resume_session, model)` |
| Monitoring | `get_status()`, `get_logs(tail)` |
| Properties | `is_running`, `current`, `history` |

**Import strategy:** `from __future__ import annotations` + `TYPE_CHECKING` guard for `HunterStatus`, `HunterProcess`, `BudgetManager`, `CommitInfo`. No runtime imports of `control.py`, `budget.py`, or `worktree.py` from `base.py`.

**Design decision — wide protocols:** The plan's proposed minimal `ControlBackend` only had `spawn/kill/get_status/get_logs/is_alive`. But tool handlers also access `controller.worktree`, `controller.budget`, `controller.current`, `controller.is_running`, `controller.redeploy()`, and `controller.history`. The protocol matches actual usage. We can narrow it in Phase B when we know what the remote backend actually needs.

---

## Task A2: WorktreeManager `push()` No-Op

**Goal:** Add `push()` to `WorktreeManager` so it structurally satisfies `WorktreeBackend`.

### File modified: `hunter/worktree.py`

Added between `diff_since()` and the internal helpers section (lines 274–279):

```python
def push(self) -> None:
    """Push commits to remote. No-op for local worktrees.

    Remote backends (Phase B) will implement actual git push here.
    """
    logger.debug("Local worktree: push() is a no-op")
```

6 lines added. No git operations performed. No existing behavior changed.

---

## Task A3: Controller Factory

**Goal:** Centralize controller construction in a factory function with backend selection.

### Files created: `hunter/backends/__init__.py` (82 lines)

**`create_controller(mode="auto", budget=None) -> HunterController`:**

```python
# Auto-detection logic:
if mode == "auto":
    mode = "fly" if os.environ.get("FLY_APP_NAME") else "local"

# Mode dispatch:
if mode == "fly":
    raise NotImplementedError("Fly.io backend not yet implemented (Phase B)")

# Local backend (deferred imports):
from hunter.budget import BudgetManager
from hunter.control import HunterController
from hunter.worktree import WorktreeManager

worktree = WorktreeManager()
if budget is None:
    budget = BudgetManager()
return HunterController(worktree=worktree, budget=budget)
```

**Key design decisions:**

- **`budget` parameter exists** because `OverseerLoop` creates its own `BudgetManager` and needs to share it with the controller (and transitively with all tool modules).
- **Deferred imports** inside the function body (not at module level) to avoid circular dependencies and keep `hunter/` as an optional package.
- **`_VALID_MODES = {"auto", "local", "fly"}`** — explicit allowlist with `ValueError` on unknown modes.
- **Re-exports protocols** for convenience: `from hunter.backends import ControlBackend, WorktreeBackend`.

---

## Task A4: Update Tool Modules

**Goal:** Replace the duplicated `_get_controller()` in all 4 tool modules with the factory.

### Files modified (4 files, identical change in each)

**`hunter/tools/process_tools.py`** (lines 29–46), **`hunter/tools/inject_tools.py`** (lines 32–44), **`hunter/tools/code_tools.py`** (lines 33–45), **`hunter/tools/budget_tools.py`** (lines 29–41):

Before (7 lines, duplicated 4 times = 28 lines total):
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

After (3 lines, duplicated 4 times = 12 lines total):
```python
def _get_controller():
    global _controller
    if _controller is None:
        from hunter.backends import create_controller
        _controller = create_controller()
    return _controller
```

**`_set_controller()` stays exactly as-is** in all 4 modules — tests depend on it for mock injection, and `OverseerLoop._setup()` uses it to share a single controller across modules.

**Net reduction:** 16 lines of duplicated import/construction code removed, replaced by 4 single-line factory calls.

---

## Task A5: Update OverseerLoop

**Goal:** `_setup()` uses the factory instead of direct construction.

### File modified: `hunter/overseer.py`

**Change 1 — Module-level imports (line 34–42):**

Removed:
```python
from hunter.control import HunterController
from hunter.worktree import WorktreeManager
```

Kept:
```python
from hunter.budget import BudgetManager  # Still used directly in _setup()
from hunter.memory import AnimaManager, OverseerMemoryBridge  # Still used
```

**Change 2 — `_setup()` controller construction (lines 186–194):**

Before:
```python
# Create shared infrastructure
worktree = WorktreeManager()

if self.budget is None:
    self.budget = BudgetManager()

self._controller = self.controller or HunterController(
    worktree=worktree, budget=self.budget,
)
```

After:
```python
# Create shared infrastructure
if self.budget is None:
    self.budget = BudgetManager()

if self.controller is not None:
    self._controller = self.controller
else:
    from hunter.backends import create_controller
    self._controller = create_controller(budget=self.budget)
```

**Change 3 — Worktree setup check (line 214–215):**

Before (used local `worktree` variable):
```python
if not worktree.is_setup():
    worktree.setup()
```

After (accesses via controller):
```python
if not self._controller.worktree.is_setup():
    self._controller.worktree.setup()
```

**Why the explicit `if/else` instead of `or`:** The original `self.controller or HunterController(...)` always created a `WorktreeManager()` even when `self.controller` was provided (the local variable was used for the worktree check). The new pattern avoids unnecessary construction and makes the "provided controller" path clearer.

**Why `budget` parameter is passed:** The factory's `budget=self.budget` ensures the controller's BudgetManager is the same instance the Overseer uses for spend recording. Without this, the factory would create its own BudgetManager, causing spend to be tracked in two separate instances.

---

## Task A6: Update CLI

**Goal:** `_cmd_spawn()` uses the factory.

### File modified: `hunter/cli.py`

**In `_cmd_spawn()` (lines 290–291):**

Before:
```python
from hunter.budget import BudgetManager
from hunter.control import HunterController
from hunter.worktree import WorktreeManager

wt = WorktreeManager()
budget = BudgetManager()
controller = HunterController(worktree=wt, budget=budget)
```

After:
```python
from hunter.backends import create_controller
controller = create_controller()
```

**`_cmd_setup()` stays as-is:** It creates `WorktreeManager` and `BudgetManager` directly because setup is a bootstrapping operation that must work before the full system is ready. The factory itself calls these constructors, so using the factory for setup would be circular.

**`_cmd_status()`, `_cmd_budget()`, `_cmd_logs()` stay as-is:** These are stateless CLI commands that read from disk (PID files, config, log files) without needing a full controller. They create standalone `WorktreeManager` and `BudgetManager` for read-only status display.

---

## Task A7: New Tests

**Goal:** Test the factory and protocol definitions.

### File created: `tests/test_hunter_backends.py` (196 lines)

12 tests across 6 test classes:

| Class | Tests | What it verifies |
|-------|-------|-----------------|
| `TestCreateControllerLocal` | 3 | Returns `HunterController`, calls constructors, passes `budget` through |
| `TestCreateControllerAuto` | 2 | Auto defaults to local (no `FLY_APP_NAME`), selects fly when env set |
| `TestCreateControllerFly` | 1 | `mode="fly"` raises `NotImplementedError` |
| `TestCreateControllerInvalidMode` | 2 | Unknown mode and empty string raise `ValueError` |
| `TestWorktreeManagerPush` | 2 | Method exists + callable, no-op doesn't raise |
| `TestProtocolSatisfaction` | 2 | `WorktreeManager` has all 17 `WorktreeBackend` methods + attrs; `HunterController` has all 5 `ControlBackend` methods + 3 properties |

**Mock strategy:** Patches `WorktreeManager.__init__` and `BudgetManager.__init__` (returning `None`) to avoid real git/file operations while still testing that the factory produces real `HunterController` instances. The `push()` no-op test creates a temporary git repo via `tmp_path` fixture.

---

## Task A8: Existing Test Updates

**Goal:** All 337 existing tests pass with zero behavior change.

### File modified: `tests/test_hunter_overseer.py`

The 10 `TestSetup` tests all patched `hunter.overseer.WorktreeManager` and `hunter.overseer.HunterController` — module-level imports that no longer exist. These were updated to patch `hunter.backends.create_controller` instead.

**Pattern change (all 10 tests):**

Before (6 patches per test):
```python
@patch("hunter.overseer.ensure_hunter_home")
@patch("hunter.overseer.WorktreeManager")        # ← removed import
@patch("hunter.overseer.BudgetManager")
@patch("hunter.overseer.HunterController")        # ← removed import
@patch("hunter.overseer.AnimaManager")
@patch("run_agent.AIAgent")
def test_setup_X(self, _agent, _anima, _ctrl, _budget, _wt, _ensure):
```

After (5 patches per test):
```python
@patch("hunter.overseer.ensure_hunter_home")
@patch("hunter.backends.create_controller")        # ← factory
@patch("hunter.overseer.BudgetManager")
@patch("hunter.overseer.AnimaManager")
@patch("run_agent.AIAgent")
def test_setup_X(self, _agent, _anima, _budget, _factory, _ensure):
```

**Tests that check worktree behavior** (`test_setup_ensures_worktree`, `test_setup_worktree_already_setup`) now set `mock_factory.return_value = mock_ctrl` where `mock_ctrl.worktree.is_setup.return_value` controls the behavior, since the overseer now accesses the worktree via `self._controller.worktree`.

**Helper added:**
```python
@staticmethod
def _make_mock_controller(worktree_is_setup=True):
    ctrl = MagicMock()
    ctrl.worktree.is_setup.return_value = worktree_is_setup
    return ctrl
```

**New assertion added to `test_setup_uses_provided_controller`:**
```python
# Factory should NOT have been called — we provided our own controller
_factory.assert_not_called()
```

This verifies the optimization: when a controller is provided via `OverseerLoop(controller=...)`, the factory is never invoked.

---

## Final Test Results

```
$ python -m pytest tests/test_hunter_*.py -q
349 passed in 43.74s
```

| Test file | Count | Status |
|-----------|-------|--------|
| test_hunter_control.py | 35 | PASS |
| test_hunter_memory.py | 42 | PASS |
| test_hunter_process_tools.py | 29 | PASS |
| test_hunter_inject_tools.py | 33 | PASS |
| test_hunter_code_tools.py | 49 | PASS |
| test_hunter_budget_tools.py | 27 | PASS |
| test_hunter_overseer_prompts.py | 18 | PASS |
| test_hunter_overseer.py | 53 | PASS |
| test_hunter_cli.py | 51 | PASS |
| **test_hunter_backends.py** | **12** | **PASS** |
| **Total** | **349** | **ALL PASS** |

2 pre-existing failures in unrelated test files (`test_timezone.py`, `test_vision_tools.py`) confirmed not caused by Phase A changes.

---

## Files Changed Summary

| File | Action | Lines | Purpose |
|------|--------|-------|---------|
| `hunter/backends/__init__.py` | **Created** | 82 | Factory: `create_controller(mode, budget)` |
| `hunter/backends/base.py` | **Created** | 101 | Protocols: `WorktreeBackend`, `ControlBackend` |
| `hunter/worktree.py` | Modified | +6 | Added `push()` no-op |
| `hunter/tools/process_tools.py` | Modified | -4 | `_get_controller()` uses factory |
| `hunter/tools/inject_tools.py` | Modified | -4 | `_get_controller()` uses factory |
| `hunter/tools/code_tools.py` | Modified | -4 | `_get_controller()` uses factory |
| `hunter/tools/budget_tools.py` | Modified | -4 | `_get_controller()` uses factory |
| `hunter/overseer.py` | Modified | -3 net | Removed 2 imports, factory in `_setup()`, worktree access via controller |
| `hunter/cli.py` | Modified | -4 | `_cmd_spawn()` uses factory |
| `tests/test_hunter_backends.py` | **Created** | 196 | 12 tests for factory + protocols |
| `tests/test_hunter_overseer.py` | Modified | ~60 | 10 setup tests re-patched for factory |
| `hjjh/changelog.md` | Modified | +50 | Phase A changelog entry |

---

## Known Seams for Phase B

These are intentional gaps documented in the plan, confirmed during implementation:

1. **`inject_tools.py` file-based IPC** — writes directly to `get_injection_path()` and `get_interrupt_flag_path()`, bypassing the controller. Remote backends will need injection routed through the backend.

2. **`HunterController.spawn()` creates `HunterProcess` internally** — Phase B will need to delegate to `ControlBackend.spawn()` instead, or create `FlyHunterController` as an alternative implementation.

3. **`process_tools.py` accesses `process._pid`** (private attr) — Phase B should expose PID through a public interface or the status dict.

4. **`WorktreeBackend.push()` is the only new method** — for remote, `commit()` and `push()` are separate steps (edit locally, push to trigger remote redeploy). The Overseer's code tools will need to call `push()` after `commit()`.

5. **`_cmd_setup()` and read-only CLI commands (`_cmd_status`, `_cmd_budget`, `_cmd_logs`) bypass the factory** — these are bootstrapping/read-only operations that don't need a full controller. Phase B may want to revisit if remote setup differs significantly.
