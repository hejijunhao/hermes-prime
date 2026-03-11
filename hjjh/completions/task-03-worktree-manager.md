# Task 3: Git Worktree Manager — Completion Notes

**Status:** Complete
**Date:** 2026-03-11

---

## What Was Done

Implemented `hunter/worktree.py` — full git worktree lifecycle management for the Hunter's codebase. The Overseer uses this to modify the Hunter's source code and redeploy without affecting its own codebase.

---

## File Modified

### `hunter/worktree.py` (replaced stub)

**~280 lines.** Contains:

### Classes

| Class | Purpose |
|-------|---------|
| `WorktreeManager` | Main class — manages the hunter/live branch and git worktree |
| `CommitInfo` | Dataclass: `hash`, `short_hash`, `message` |
| `WorktreeError` | Custom exception for git operation failures |

### WorktreeManager Methods

#### Setup & Teardown

| Method | Purpose |
|--------|---------|
| `setup()` | One-time: create `hunter/live` branch from HEAD + create worktree. Idempotent |
| `teardown()` | Remove worktree (keeps branch for history). Re-attachable via `setup()` |

#### Status Queries

| Method | Returns | Purpose |
|--------|---------|---------|
| `is_setup()` | `bool` | Branch + worktree both exist and valid? |
| `is_clean()` | `bool` | No uncommitted changes? |
| `get_head_commit()` | `str` (40-char SHA) | Current HEAD of the worktree |
| `get_recent_commits(n)` | `List[CommitInfo]` | Last N commits on the hunter branch |

#### File Operations

| Method | Purpose |
|--------|---------|
| `read_file(path)` | Read file from worktree. Raises `FileNotFoundError` |
| `write_file(path, content)` | Write file, create parent dirs. Does NOT auto-commit |
| `edit_file(path, old_str, new_str)` | Find-and-replace (unique match required). Returns `bool` |
| `delete_file(path)` | Delete file from worktree. Returns `bool` |
| `list_files(dir, pattern)` | Glob files recursively, returns paths relative to worktree root |

#### Git Operations

| Method | Purpose |
|--------|---------|
| `commit(message, files)` | Stage + commit. Files=None stages all. Returns commit hash |
| `rollback(commit_hash)` | Hard reset to a specific commit |
| `diff(staged)` | Show uncommitted changes |
| `diff_since(commit_hash)` | Show changes between a commit and HEAD |

---

## How It Works

### Branch + Worktree Lifecycle

```
First run (setup()):
  1. Check if "hunter/live" branch exists → if not, create from HEAD
  2. Check if worktree exists at ~/.hermes/hunter/worktree/ → if not, create
  3. Log: "Worktree ready: branch=hunter/live path=... head=abc123"

Subsequent runs:
  setup() detects both exist → no-op (idempotent)

Teardown:
  git worktree remove <path> --force
  Branch preserved → full commit history intact
  Re-setup creates a new worktree attached to the same branch
```

### Safety Invariants

1. **All git commands default to `cwd=self.worktree_path`** — they target the worktree, not the main repo
2. **`_ensure_branch()` and `_ensure_worktree()` run git commands against `cwd=self.repo_root`** — these are the only methods that touch the main repo (to create branch/worktree)
3. **`edit_file()` requires a unique match** — if `old_str` appears more than once, it raises `WorktreeError` instead of silently replacing the wrong instance
4. **`commit()` checks for staged changes** — raises `WorktreeError("Nothing to commit")` instead of creating empty commits
5. **`_find_repo_root()` walks up from `__file__`** — doesn't rely on CWD, so it works regardless of where the Overseer is invoked from

### How the Overseer Uses This

```python
wt = WorktreeManager()
wt.setup()

# Modify a skill file
wt.write_file("skills/security/idor.md", "# IDOR Detection\n...")
before = wt.get_head_commit()
wt.commit("feat(hunter): add IDOR detection skill")

# If the change was bad:
wt.rollback(before)

# Read Hunter code for analysis:
content = wt.read_file("tools/terminal_tool.py")

# Targeted edit:
wt.edit_file("agent/prompt_builder.py", "old prompt text", "new prompt text")
wt.commit("refactor(hunter): improve system prompt")
```

---

## Design Decisions

### Why `edit_file` requires unique match

Ambiguous edits are a source of subtle bugs. If `old_str` appears twice and we replace the wrong one, the Hunter could break in hard-to-diagnose ways. Requiring a unique match forces the Overseer to provide enough context for a precise edit — the same principle as the `Edit` tool in Claude Code.

### Why `write_file` doesn't auto-commit

Separating write from commit lets the Overseer:
1. Make multiple file changes, then commit them together as one logical change
2. Inspect changes with `diff()` before committing
3. Discard changes by calling `rollback()` without a spurious commit in history

The `hunter_code_edit` tool (Task 8) will auto-commit — that's the tool's policy, not the worktree manager's.

### Why teardown keeps the branch

Branch history is valuable — it's the complete evolution log of the Hunter's codebase. Teardown only removes the worktree (the working copy). The branch can be re-attached via `setup()` at any time, preserving all commits.

### Why `_run_git` has a 30-second timeout

Git operations should be fast. If a git command hangs for 30 seconds, something is wrong (network issue, lock contention, corrupt repo). Better to fail fast and let the Overseer diagnose than hang indefinitely.

---

## Tests Run (20/20 passed)

| # | Test | What It Verifies |
|---|------|-----------------|
| 1 | setup | Creates branch + worktree from scratch |
| 2 | idempotent setup | Calling setup() twice doesn't error |
| 3 | is_clean | Clean worktree correctly detected |
| 4 | read_file | Reads file content from worktree |
| 5 | read_file missing | Raises FileNotFoundError for missing files |
| 6 | write_file | Creates file + parent directories, worktree becomes dirty |
| 7 | commit | Stages and commits, returns valid 40-char SHA |
| 8 | get_head_commit | Returns correct hash after commit |
| 9 | get_recent_commits | Returns CommitInfo list with correct messages |
| 10 | edit_file | Find-and-replace modifies file correctly |
| 11 | edit_file not found | Returns False when old_str missing |
| 12 | edit_file ambiguous | Raises WorktreeError when old_str appears multiple times |
| 13 | diff | Runs without error |
| 14 | diff_since | Shows changes between two commits |
| 15 | rollback | Reverts HEAD and file system to previous commit |
| 16 | commit nothing | Raises WorktreeError when no staged changes |
| 17 | delete_file | Deletes file, returns False when already deleted |
| 18 | list_files | Globs files recursively in worktree |
| 19 | teardown | Removes worktree directory |
| 20 | re-setup | Worktree can be recreated after teardown, branch history preserved |

All tests use a temporary git repo — nothing touches the real Hermes repo.

---

## What's Next

The worktree manager is consumed by:
- **Task 4** (`HunterProcess`): uses `worktree_path` as the Hunter's CWD
- **Task 6** (`hunter_spawn`): calls `setup()` before spawning
- **Task 8** (code tools): `hunter_code_edit`, `hunter_code_read`, `hunter_diff`, `hunter_rollback` all wrap WorktreeManager methods
- **Task 10** (Overseer loop): calls `setup()` during `_setup()`
