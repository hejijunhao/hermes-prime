# Tasks 8 & 9: Code Tools + Budget Tools — Implementation Plan

**Date:** 2026-03-11
**Depends on:** Tasks 1–7 (all DONE)
**Blocks:** Task 10 (Overseer main loop), Task 12 (CLI entry points)

---

## Overview

Tasks 8 and 9 complete the Overseer's tool arsenal. Together with Tasks 6 (process tools) and 7 (inject tools), they give the Overseer all 13 tools listed in the `hunter-overseer` toolset.

| Task | Tools | Estimated Size | Purpose |
|------|-------|----------------|---------|
| 8 | `hunter_code_edit`, `hunter_code_read`, `hunter_diff`, `hunter_rollback`, `hunter_redeploy` | ~280 lines | Code modification + redeployment |
| 9 | `budget_status`, `hunter_model_set` | ~180 lines | Cost visibility + model tier control |

**After these tasks, the Overseer can:**
1. Read/edit the Hunter's source code in the worktree *(Task 8)*
2. Commit changes and view diffs *(Task 8)*
3. Rollback bad changes *(Task 8)*
4. Kill + restart the Hunter with updated code *(Task 8)*
5. Check budget status and remaining funds *(Task 9)*
6. Change the Hunter's model tier for cost optimisation *(Task 9)*

---

## Task 8: Code Tools (`hunter/tools/code_tools.py`)

### Architecture

These tools are the Overseer's **hard intervention** mechanism. They wrap `WorktreeManager` (Task 3) and `HunterController.redeploy()` (Task 4) to let the Overseer LLM modify the Hunter's codebase and restart it with new code.

```
Overseer LLM
    │
    ├─ hunter_code_read(path)           → WorktreeManager.read_file()
    ├─ hunter_code_edit(path, old, new) → WorktreeManager.edit_file()
    ├─ hunter_diff(staged?, since?)     → WorktreeManager.diff() / diff_since()
    ├─ hunter_rollback(commit)          → WorktreeManager.rollback()
    └─ hunter_redeploy(model?, resume?) → HunterController.redeploy()
```

### Shared Infrastructure

Same patterns as Tasks 6 & 7:

1. **Controller singleton** — `_controller` / `_get_controller()` / `_set_controller()` with deferred imports from `hunter.budget`, `hunter.control`, `hunter.worktree`.
2. **Elephantasm helper** — `_extract_overseer_event(text, meta)` for best-effort memory logging. Fire-and-forget, never crashes.
3. **Error handling** — all handlers return JSON strings. Errors are `{"error": "..."}`, never exceptions.
4. **Registration** — `SCHEMA` dict + `registry.register()` call per tool.

### 8.1 `hunter_code_read` — Read a File from the Worktree

**Purpose:** Let the Overseer inspect the Hunter's source code before deciding what to change.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | Relative path within the worktree (e.g., `"skills/security/idor/SKILL.md"`) |

**Handler logic:**
```python
def _handle_hunter_code_read(args: dict, **kwargs) -> str:
    path = args.get("path", "")
    if not path:
        return json.dumps({"error": "path is required"})

    controller = _get_controller()
    worktree = controller.worktree

    try:
        content = worktree.read_file(path)
    except FileNotFoundError:
        return json.dumps({"error": f"File not found in worktree: {path}"})
    except WorktreeError as e:
        return json.dumps({"error": str(e)})

    return json.dumps({
        "path": path,
        "content": content,
        "size_bytes": len(content.encode("utf-8")),
    })
```

**Returns:** `{"path": "...", "content": "...", "size_bytes": N}` or `{"error": "..."}`

**Edge cases to test:**
- Missing `path` parameter → error
- File doesn't exist → `FileNotFoundError` → JSON error
- Worktree not set up → `WorktreeError` → JSON error
- Binary file / encoding error → UTF-8 decode error → JSON error
- Normal read → content returned with byte size

**Schema notes:**
- Description should suggest example paths: skills, tools, prompts, config files
- The Overseer uses this to read before editing (same pattern as Claude Code's Read tool)

### 8.2 `hunter_code_edit` — Edit a File in the Worktree

**Purpose:** Make find-and-replace edits to the Hunter's source code. This is the Overseer's primary code modification tool.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | Relative path within the worktree |
| `old_string` | string | yes | Text to find (must appear exactly once) |
| `new_string` | string | yes | Replacement text |
| `commit_message` | string | no | Git commit message. Default: `"overseer: edit {path}"` |

**Design decision — edit-only, no full-file write:**

The Phase 1 spec (§8.1) proposed two modes: full-file write (`content` param) and find-and-replace (`old_string`/`new_string`). We should implement **only the find-and-replace mode** for Task 8. Rationale:

1. **Safety:** Full-file writes are dangerous — the Overseer could accidentally overwrite a file with truncated content. Find-and-replace is inherently safer because the LLM must demonstrate it has read the file (by providing `old_string`).
2. **Auditability:** Diffs from find-and-replace are clear and reviewable. Full rewrites produce opaque diffs.
3. **Consistency:** This mirrors Claude Code's own `Edit` tool, which only supports find-and-replace.
4. **New files:** If the Overseer needs to *create* a new file, `old_string=""` with `new_string=<content>` can be handled as a special case using `worktree.write_file()`. This keeps one tool with clear semantics.

**Handler logic:**
```python
def _handle_hunter_code_edit(args: dict, **kwargs) -> str:
    path = args.get("path", "")
    if not path:
        return json.dumps({"error": "path is required"})

    old_string = args.get("old_string")
    new_string = args.get("new_string")

    if old_string is None or new_string is None:
        return json.dumps({"error": "old_string and new_string are required"})

    if old_string == new_string:
        return json.dumps({"error": "old_string and new_string are identical — no change"})

    controller = _get_controller()
    worktree = controller.worktree

    # Special case: empty old_string → create/overwrite file
    if old_string == "":
        try:
            worktree.write_file(path, new_string)
        except WorktreeError as e:
            return json.dumps({"error": str(e)})
    else:
        # Standard find-and-replace
        try:
            found = worktree.edit_file(path, old_string, new_string)
        except FileNotFoundError:
            return json.dumps({"error": f"File not found in worktree: {path}"})
        except WorktreeError as e:
            # Ambiguous edit (old_string appears multiple times)
            return json.dumps({"error": str(e)})

        if not found:
            return json.dumps({"error": "old_string not found in file"})

    # Auto-commit
    commit_msg = args.get("commit_message", f"overseer: edit {path}")
    try:
        commit_hash = worktree.commit(commit_msg, files=[path])
    except WorktreeError as e:
        # Nothing to commit (shouldn't happen after a successful edit, but be safe)
        return json.dumps({"error": f"Edit succeeded but commit failed: {e}"})

    # Elephantasm logging
    _extract_overseer_event(
        f"Code edit: {path} (commit {commit_hash[:8]})",
        meta={"type": "code_edit", "path": path, "commit": commit_hash},
    )

    return json.dumps({
        "status": "edited_and_committed",
        "path": path,
        "commit": commit_hash,
    })
```

**Returns:** `{"status": "edited_and_committed", "path": "...", "commit": "..."}` or `{"error": "..."}`

**Edge cases to test:**
- Missing `path` → error
- Missing `old_string` or `new_string` → error
- `old_string == new_string` → no-op error
- Empty `old_string` → creates/overwrites file (write mode)
- `old_string` not found → `{"error": "old_string not found in file"}`
- `old_string` appears multiple times → `WorktreeError` (ambiguous) → JSON error
- File not found → `FileNotFoundError` → JSON error
- Worktree not set up → `WorktreeError` → JSON error
- Successful edit → auto-commits, returns commit hash
- Custom `commit_message` → used in commit
- Default `commit_message` → `"overseer: edit {path}"`
- Elephantasm logging fires (best-effort)

### 8.3 `hunter_diff` — View Changes in the Worktree

**Purpose:** Let the Overseer inspect uncommitted changes or compare against a previous commit.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `staged` | boolean | no | If true, show only staged changes. Default false (all changes). |
| `since_commit` | string | no | If provided, show changes between this commit and HEAD. |

**Handler logic:**
```python
def _handle_hunter_diff(args: dict, **kwargs) -> str:
    controller = _get_controller()
    worktree = controller.worktree

    since_commit = args.get("since_commit")

    try:
        if since_commit:
            diff_output = worktree.diff_since(since_commit)
        else:
            staged = args.get("staged", False)
            diff_output = worktree.diff(staged=staged)
    except WorktreeError as e:
        return json.dumps({"error": str(e)})

    return json.dumps({
        "diff": diff_output,
        "empty": diff_output.strip() == "",
    })
```

**Returns:** `{"diff": "...", "empty": bool}` or `{"error": "..."}`

**Design note:** The `empty` field is a convenience for the LLM — it doesn't have to parse the diff string to know "nothing changed." This follows the pattern of `hunter_status` including a `summary` field.

**Edge cases to test:**
- No args → unstaged diff (default)
- `staged: true` → staged changes only
- `since_commit` provided → calls `diff_since()`
- Both `staged` and `since_commit` → `since_commit` takes priority
- Empty diff → `{"diff": "", "empty": true}`
- Invalid commit hash → `WorktreeError` → JSON error
- Worktree not set up → `WorktreeError` → JSON error

### 8.4 `hunter_rollback` — Reset Worktree to a Previous Commit

**Purpose:** Undo a bad code change by hard-resetting the worktree to a known-good commit.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `commit` | string | yes | Full or short commit hash to reset to. |

**Handler logic:**
```python
def _handle_hunter_rollback(args: dict, **kwargs) -> str:
    commit_hash = args.get("commit", "")
    if not commit_hash:
        return json.dumps({"error": "commit hash is required"})

    controller = _get_controller()
    worktree = controller.worktree

    try:
        worktree.rollback(commit_hash)
    except WorktreeError as e:
        return json.dumps({"error": str(e)})

    # Get the new HEAD for confirmation
    try:
        new_head = worktree.get_head_commit()
    except WorktreeError:
        new_head = commit_hash  # Fallback

    # Elephantasm logging
    _extract_overseer_event(
        f"Rolled back worktree to {commit_hash[:8]}",
        meta={"type": "rollback", "target_commit": commit_hash},
    )

    return json.dumps({
        "status": "rolled_back",
        "to_commit": new_head,
    })
```

**Returns:** `{"status": "rolled_back", "to_commit": "..."}` or `{"error": "..."}`

**Edge cases to test:**
- Missing `commit` → error
- Valid short hash → rollback succeeds
- Valid full hash → rollback succeeds
- Invalid hash → `WorktreeError` (git reset fails) → JSON error
- Worktree not set up → `WorktreeError` → JSON error
- Elephantasm event fires (best-effort)

### 8.5 `hunter_redeploy` — Kill + Restart the Hunter with New Code

**Purpose:** After code changes, kill the running Hunter and restart it so it picks up the new code.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `resume_session` | boolean | no | Resume the previous session (default true). |
| `model` | string | no | Override the model for the new Hunter instance. |

**Handler logic:**
```python
def _handle_hunter_redeploy(args: dict, **kwargs) -> str:
    controller = _get_controller()

    resume = args.get("resume_session", True)
    model = args.get("model")

    try:
        process = controller.redeploy(
            resume_session=resume,
            model=model,
        )
    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    # Elephantasm logging
    _extract_overseer_event(
        f"Redeployed Hunter (session={process.session_id}, model={process.model}, resumed={resume})",
        meta={"type": "redeploy", "model": process.model, "resumed": resume},
    )

    return json.dumps({
        "status": "redeployed",
        "session_id": process.session_id,
        "model": process.model,
        "pid": process._pid,
        "resumed": resume,
    })
```

**Returns:** `{"status": "redeployed", "session_id": "...", "model": "...", "pid": N, "resumed": bool}` or `{"error": "..."}`

**Design note:** This differs from `hunter_spawn` (Task 6) in two ways:
1. It **always kills the current Hunter first** (spawn only kills if one is already running).
2. It defaults to **resume_session=True** (spawn defaults to False) — the assumption is that a redeploy preserves continuity while spawn starts fresh.

**Edge cases to test:**
- No args → default resume=True, no model override
- `resume_session: false` → fresh session
- `model` provided → passed to `controller.redeploy()`
- No Hunter running → redeploy still works (spawns fresh)
- Budget exhausted → `RuntimeError` → JSON error
- Elephantasm event fires (best-effort)

### 8.6 Integration Points

**model_tools.py** — add to `_modules` list:
```python
"hunter.tools.code_tools",
```

**toolsets.py** — already lists all 5 tools in `hunter-overseer`. No changes needed.

### 8.7 Test Plan (`tests/test_hunter_code_tools.py`)

Target: ~35 tests across 8 test classes.

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestGetController` | 3 | Lazy init, caching, test override |
| `TestHunterCodeRead` | 5 | Normal read, missing path param, file not found, worktree not setup, content with size |
| `TestHunterCodeEdit` | 10 | Normal edit, create file (empty old_string), file not found, old_string not found, ambiguous edit, identical strings, missing params, custom commit message, default commit message, Elephantasm logging |
| `TestHunterDiff` | 5 | Unstaged diff, staged diff, diff since commit, empty diff, worktree error |
| `TestHunterRollback` | 4 | Valid rollback, missing commit, invalid hash, Elephantasm logging |
| `TestHunterRedeploy` | 5 | Default args, no resume, model override, budget error, no hunter running |
| `TestToolRegistration` | 5 | All 5 tools in registry, correct toolset, schema validation |
| `TestDispatchIntegration` | 5 | Dispatch each tool + exception handling |

**Test fixtures:**
- `mock_controller` — `MagicMock(spec=HunterController)` with `.worktree` as `MagicMock(spec=WorktreeManager)`
- `_set_controller(mock_controller)` in setup, `_set_controller(None)` in teardown
- `_isolate_hermes_home` autouse fixture (from conftest) for filesystem isolation

---

## Task 9: Budget Tools (`hunter/tools/budget_tools.py`)

### Architecture

These tools give the Overseer **visibility into spending** and **control over model costs**.

```
Overseer LLM
    │
    ├─ budget_status()                  → BudgetManager.check_budget()
    └─ hunter_model_set(model)          → Pending model update + optional injection
```

### 9.1 `budget_status` — Get Current Budget State

**Purpose:** Let the Overseer check how much budget remains, whether alerts have triggered, and whether it's approaching a hard stop.

**Parameters:** None (no-args tool, like `hunter_kill` and `hunter_status`).

**Handler logic:**
```python
def _handle_budget_status(args: dict, **kwargs) -> str:
    controller = _get_controller()
    budget = controller.budget

    # Reload to pick up any human config changes
    budget.reload()
    status = budget.check_budget()

    result = status.to_dict()
    result["summary"] = status.summary()

    # Add spend history context (last 5 entries for quick reference)
    recent = budget.get_spend_history(limit=5)
    result["recent_spend"] = recent

    # Add daily summary
    daily = budget.get_daily_summary()
    result["daily_breakdown"] = daily

    return json.dumps(result)
```

**Returns:** Full `BudgetStatus` dict + `summary` string + `recent_spend` list + `daily_breakdown` dict.

**Design note:** We include `recent_spend` and `daily_breakdown` proactively so the Overseer LLM has full context in a single tool call. This avoids the need for separate "budget history" and "daily summary" tools — keeping the tool count low.

**Edge cases to test:**
- Default config → normal status returned
- Budget exhausted → `hard_stop: true`, `allowed: false`
- Alert threshold hit → `alert: true`
- Daily mode → `daily_limit` populated, `total_limit` null
- Total mode → both limits populated
- Config file changed on disk → `reload()` picks it up
- No ledger file → `spend_today: 0`, `spend_total: 0`
- Spend history empty → `recent_spend: []`

### 9.2 `hunter_model_set` — Change the Hunter's Model Tier

**Purpose:** Let the Overseer switch the Hunter to a cheaper or more capable model. This is the primary cost optimisation lever.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `model` | string | yes | Model identifier (e.g., `"qwen/qwen3.5-7b"`, `"qwen/qwen3.5-72b"`) |
| `apply_immediately` | boolean | no | If true and Hunter is running, trigger a redeploy. Default false (apply on next redeploy/spawn). |

**Design decision — model persistence:**

The model choice needs to survive Hunter restarts. Two options:

- **Option A:** Store in a file (`~/.hermes/hunter/model_override.txt`). The runner reads this on startup.
- **Option B:** Store on the `HunterController` instance (in-memory only). Lost on Overseer restart.

**Decision: Option A** (file-based persistence). The model override is written to `~/.hermes/hunter/model_override.txt`. The runner checks this file at startup and uses it if present. This survives both Hunter and Overseer restarts.

**Handler logic:**
```python
def _handle_hunter_model_set(args: dict, **kwargs) -> str:
    model = args.get("model", "")
    if not model:
        return json.dumps({"error": "model is required"})

    apply_immediately = args.get("apply_immediately", False)

    controller = _get_controller()

    # Get old model for logging
    old_model = None
    if controller.current:
        old_model = controller.current.model

    # Persist model override to file
    model_override_path = _get_model_override_path()
    try:
        model_override_path.parent.mkdir(parents=True, exist_ok=True)
        model_override_path.write_text(model, encoding="utf-8")
    except OSError as e:
        return json.dumps({"error": f"Failed to persist model override: {e}"})

    result = {
        "status": "model_updated",
        "old_model": old_model,
        "new_model": model,
        "apply_immediately": apply_immediately,
    }

    # Optionally trigger redeploy
    if apply_immediately and controller.is_running:
        try:
            process = controller.redeploy(resume_session=True, model=model)
            result["redeployed"] = True
            result["session_id"] = process.session_id
            result["pid"] = process._pid
        except RuntimeError as e:
            result["redeployment_error"] = str(e)
            result["redeployed"] = False
    else:
        result["redeployed"] = False
        if controller.is_running:
            result["note"] = "Model change takes effect on next redeploy or spawn."
        else:
            result["note"] = "Model change takes effect on next spawn."

    # Elephantasm logging
    _extract_overseer_event(
        f"Model changed: {old_model} → {model} (immediate={apply_immediately})",
        meta={"type": "model_change", "old_model": old_model, "new_model": model},
    )

    return json.dumps(result)


def _get_model_override_path() -> Path:
    from hunter.config import get_hunter_home
    return get_hunter_home() / "model_override.txt"
```

**Returns:** `{"status": "model_updated", "old_model": "...", "new_model": "...", "redeployed": bool, ...}` or `{"error": "..."}`

**Edge cases to test:**
- Missing `model` → error
- Valid model, no immediate apply → persists to file, returns note
- Valid model, `apply_immediately: true`, Hunter running → triggers redeploy
- Valid model, `apply_immediately: true`, no Hunter → persists only (no error)
- File write failure → OSError → JSON error
- Budget exhausted on immediate redeploy → `redeployment_error` in response
- Old model captured from `controller.current`
- No current Hunter → `old_model: null`
- Elephantasm event fires (best-effort)

### 9.3 Helper: `_get_model_override_path()`

Small utility returning `~/.hermes/hunter/model_override.txt`. This should also be added to `hunter/config.py` as a proper path helper for consistency — but for Task 9 scope, a local helper in `budget_tools.py` is sufficient. Can be moved to config.py in a future cleanup.

**Note for Task 10 (Overseer loop):** The Overseer loop should read this file when spawning/redeploying to pick up model overrides. This is a TODO for Task 10, not Task 9.

### 9.4 Integration Points

**model_tools.py** — add to `_modules` list:
```python
"hunter.tools.budget_tools",
```

**toolsets.py** — already lists `budget_status` and `hunter_model_set` in `hunter-overseer`. No changes needed.

**hunter/config.py** — optionally add `get_model_override_path()`. Deferred to cleanup.

### 9.5 Test Plan (`tests/test_hunter_budget_tools.py`)

Target: ~25 tests across 6 test classes.

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestGetController` | 3 | Lazy init, caching, test override |
| `TestBudgetStatus` | 6 | Normal status, exhausted, alert, daily mode, total mode, reload picks up changes |
| `TestHunterModelSet` | 8 | Normal set, missing model, apply immediately with running Hunter, apply immediately no Hunter, file persistence, file write error, budget error on redeploy, Elephantasm logging |
| `TestModelOverridePath` | 2 | Returns correct path, parent directory creation |
| `TestToolRegistration` | 4 | Both tools in registry, correct toolset, schema validation |
| `TestDispatchIntegration` | 3 | Dispatch budget_status, dispatch model_set, exception handling |

---

## Implementation Order

### Step 1: Task 8 — Code Tools (~280 lines, ~35 tests)

1. **Write `hunter/tools/code_tools.py`:**
   - Controller singleton (copy pattern from inject_tools.py)
   - Elephantasm helper (copy from inject_tools.py)
   - 5 handlers: `_handle_hunter_code_read`, `_handle_hunter_code_edit`, `_handle_hunter_diff`, `_handle_hunter_rollback`, `_handle_hunter_redeploy`
   - 5 schemas: `HUNTER_CODE_READ_SCHEMA`, `HUNTER_CODE_EDIT_SCHEMA`, `HUNTER_DIFF_SCHEMA`, `HUNTER_ROLLBACK_SCHEMA`, `HUNTER_REDEPLOY_SCHEMA`
   - 5 `registry.register()` calls

2. **Update `model_tools.py`:** Add `"hunter.tools.code_tools"` to `_modules`.

3. **Write `tests/test_hunter_code_tools.py`:** ~35 tests.

4. **Run tests:** `python -m pytest tests/test_hunter_code_tools.py -q`

5. **Write `hjjh/completions/task-08-code-tools.md`**

### Step 2: Task 9 — Budget Tools (~180 lines, ~25 tests)

1. **Write `hunter/tools/budget_tools.py`:**
   - Controller singleton
   - Elephantasm helper
   - 2 handlers: `_handle_budget_status`, `_handle_hunter_model_set`
   - `_get_model_override_path()` helper
   - 2 schemas + 2 `registry.register()` calls

2. **Update `model_tools.py`:** Add `"hunter.tools.budget_tools"` to `_modules`.

3. **Write `tests/test_hunter_budget_tools.py`:** ~25 tests.

4. **Run tests:** `python -m pytest tests/test_hunter_budget_tools.py -q`

5. **Write `hjjh/completions/task-09-budget-tools.md`**

### Step 3: Full Regression

```bash
python -m pytest tests/test_hunter_process_tools.py tests/test_hunter_inject_tools.py tests/test_hunter_code_tools.py tests/test_hunter_budget_tools.py -q
```

Verify no regressions across all hunter tool tests.

---

## Risk Assessment

### Low Risk
- **Code repetition:** Both tasks follow the exact same pattern as Tasks 6 & 7. The controller singleton, Elephantasm helper, schema format, and test structure are all established.
- **WorktreeManager API surface:** All 5 code tool handlers wrap methods that already exist and are tested (Task 3).
- **BudgetManager API surface:** Both budget tool handlers wrap methods that already exist and are tested (Task 2).

### Medium Risk
- **`hunter_code_edit` auto-commit:** If the edit succeeds but commit fails (e.g., nothing to commit because the edit was a no-op), the handler should report the discrepancy clearly. The "identical strings" check catches the obvious case, but edge cases like `old_string` and `new_string` being functionally identical (e.g., whitespace differences that normalize) could be tricky.
- **`hunter_model_set` file persistence:** The model override file adds a new file to `~/.hermes/hunter/` that other components (runner.py, control.py) don't currently read. Task 10 needs to wire this up. For now, the file is written but not consumed — that's fine for testing.

### Low-Medium Risk
- **`hunter_redeploy` vs `hunter_spawn`:** These tools have overlapping functionality. The Overseer LLM needs clear schema descriptions to distinguish them. The schema descriptions should emphasise: spawn = fresh start, redeploy = code update with continuity.

---

## Files Modified (Summary)

| File | Change | Task |
|------|--------|------|
| `hunter/tools/code_tools.py` | Full implementation (~280 lines) | 8 |
| `hunter/tools/budget_tools.py` | Full implementation (~180 lines) | 9 |
| `model_tools.py` | Add 2 module imports to `_modules` list | 8, 9 |
| `tests/test_hunter_code_tools.py` | New test file (~35 tests) | 8 |
| `tests/test_hunter_budget_tools.py` | New test file (~25 tests) | 9 |
| `hjjh/completions/task-08-code-tools.md` | Completion doc | 8 |
| `hjjh/completions/task-09-budget-tools.md` | Completion doc | 9 |
| `hjjh/changelog.md` | Version bump entries | 8, 9 |

---

## Deferred Decisions (for Task 10+)

1. **Model override consumption:** `hunter/runner.py` and `control.py` should read `model_override.txt` when spawning. Wired up in Task 10.
2. **`get_model_override_path()` in config.py:** Move from local helper to `hunter/config.py` for consistency. Cleanup task.
3. **File listing tool:** The spec doesn't include a `hunter_code_list` tool, but the Overseer may need to browse the worktree. `WorktreeManager.list_files()` exists but has no tool wrapper. Consider adding in Phase 2.
4. **Commit history tool:** `WorktreeManager.get_recent_commits()` exists but has no tool wrapper. The Overseer needs this for rollback decisions. Consider adding alongside the code tools or in Phase 2.
