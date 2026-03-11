# Task 8: Code Tools — Completion

**Date:** 2026-03-11
**Status:** DONE
**Depends on:** Tasks 1–7 (all DONE)
**Blocks:** Task 10 (Overseer main loop)

---

## Summary

Implemented the five Overseer code modification tools in `hunter/tools/code_tools.py`. These give the Overseer the ability to read, edit, diff, rollback, and redeploy the Hunter's codebase — the core "hard intervention" mechanism described in the architecture.

---

## What Was Built

### `hunter/tools/code_tools.py` (~310 lines)

Five tool handlers + controller singleton + Elephantasm helper:

| Tool | Purpose | Wraps |
|------|---------|-------|
| `hunter_code_read` | Read a file from the Hunter's worktree | `WorktreeManager.read_file()` |
| `hunter_code_edit` | Find-and-replace + auto-commit | `WorktreeManager.edit_file()` / `write_file()` + `commit()` |
| `hunter_diff` | View uncommitted changes or compare commits | `WorktreeManager.diff()` / `diff_since()` |
| `hunter_rollback` | Hard-reset worktree to a previous commit | `WorktreeManager.rollback()` |
| `hunter_redeploy` | Kill + restart Hunter with updated code | `HunterController.redeploy()` |

### Integration

- **`model_tools.py`** — added `"hunter.tools.code_tools"` to the `_modules` discovery list
- **`toolsets.py`** — already listed all 5 tools in `hunter-overseer` (no change needed)

---

## Design Decisions

### Edit-only, no full-file write

The plan proposed edit-only mode (no raw `content` write). We followed this:
- **Safety:** find-and-replace requires proving you've read the file (`old_string`)
- **Auditability:** diffs are clear and reviewable
- **New files:** handled via `old_string=""` → `worktree.write_file()` special case

### `since_commit` takes priority over `staged`

In `hunter_diff`, when both `since_commit` and `staged` are provided, `since_commit` wins. This avoids confusing combination semantics and matches how git works (you can't stage-diff against a specific commit).

### Redeploy defaults to resume

`hunter_redeploy` defaults to `resume_session=True` (unlike `hunter_spawn` which defaults to `False`). This matches the use case: code updates should preserve session continuity.

### Exception handling uses broad `except Exception`

Unlike the plan which specified `WorktreeError`, the handlers catch `Exception` broadly. This is more robust — if `WorktreeManager` raises an unexpected exception type (e.g., `subprocess.TimeoutExpired`), the handler still returns a clean JSON error instead of crashing the registry dispatch.

---

## Tests

### `tests/test_hunter_code_tools.py` — 49 tests, all passing

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestGetController` | 3 | Lazy init, caching, test override |
| `TestHunterCodeRead` | 6 | Normal read, missing/empty path, file not found, worktree error, UTF-8 byte size |
| `TestHunterCodeEdit` | 13 | Normal edit, create file, missing path/old/new, identical strings, old not found, ambiguous edit, file not found, custom/default commit message, Elephantasm logging, commit failure |
| `TestHunterDiff` | 6 | Unstaged, staged, since_commit (priority over staged), empty, worktree error, invalid commit |
| `TestHunterRollback` | 6 | Valid rollback, missing/empty commit, invalid hash, Elephantasm logging, HEAD query failure fallback |
| `TestHunterRedeploy` | 5 | Defaults (resume=true), no resume, model override, budget error, Elephantasm logging |
| `TestToolRegistration` | 5 | All 5 tools registered, correct toolset, edit schema requires path/old/new, rollback requires commit, OpenAI format validation |
| `TestDispatchIntegration` | 5 | Dispatch read/edit/diff/rollback, unexpected exception handling |

---

## Files Modified

| File | Change |
|------|--------|
| `hunter/tools/code_tools.py` | Full implementation (~310 lines, was 8-line stub) |
| `model_tools.py` | Added `"hunter.tools.code_tools"` to `_modules` |
| `tests/test_hunter_code_tools.py` | New test file (49 tests) |
