# Phase B: Fly.io Remote Backend — Completion Report

## Goal

Implement the Fly.io backend so the Overseer can manage a remote Hunter machine via the Fly Machines API and push code to a remote GitHub repo. All existing tool handlers continue working unchanged — the backend swap is transparent via the `ControlBackend` / `WorktreeBackend` protocols established in Phase A.

**Result:** `create_controller(mode="fly")` returns a working `FlyHunterController`. 2984 existing tests pass (zero regressions). 84 new tests added across 4 new test files + 2 updated test files. Integration test (B8) deferred until Fly.io infrastructure is provisioned.

---

## Prerequisites Met

- Phase A complete (protocols defined, factory in place)
- `httpx` available (already a Hermes dependency)

---

## Task B1: Fly Machines API Client

**Goal:** Thin, typed wrapper around the Fly.io Machines REST API.

### File created: `hunter/backends/fly_api.py` (230 lines)

**`FlyAPIError(Exception)`** — structured error with `status_code`, `message`, `response_body`.

**`FlyMachinesClient`** — sync `httpx.Client` wrapper against `https://api.machines.dev/v1`:

| Category | Methods |
|----------|---------|
| Lifecycle | `create_machine(config)`, `start_machine(id)`, `stop_machine(id, timeout)`, `destroy_machine(id, force)`, `wait_for_state(id, state, timeout)` |
| Status | `get_machine(id)`, `list_machines()` |
| Logs | `get_logs(id, tail)` |
| Internal | `_request(method, path, json, params, request_timeout)` — centralised HTTP dispatch with error handling |

**Design decisions:**
- Sync `httpx.Client`, not async — the Overseer loop is synchronous
- `User-Agent: hermes-prime/1.0` header on all requests
- `wait_for_state()` sets HTTP timeout = API timeout + 10s to avoid premature client-side timeout
- `get_logs()` gracefully returns `[]` on `FlyAPIError` (log endpoint may not be available for all machine states)
- `_request()` catches `httpx.TimeoutException` and `httpx.HTTPError`, wraps both as `FlyAPIError(status_code=0)`

### Tests: `tests/test_fly_api.py` (14 tests)

- Init: verifies correct headers, base URL, auth token
- Each endpoint method: correct HTTP verb + URL + params
- Error handling: 4xx, 5xx, timeout all raise `FlyAPIError`
- Logs: list response, error fallback to empty

---

## Task B2: Fly Configuration

**Goal:** Define all Fly-specific configuration in one place, loaded from environment variables.

### File created: `hunter/backends/fly_config.py` (128 lines)

**`FlyConfig` (dataclass):**

| Field | Env Var | Required | Default |
|-------|---------|----------|---------|
| `fly_api_token` | `FLY_API_TOKEN` | Yes | — |
| `hunter_app_name` | `HUNTER_FLY_APP` | Yes | — |
| `github_pat` | `GITHUB_PAT` | Yes | — |
| `hunter_repo` | `HUNTER_REPO` | Yes | — |
| `machine_image` | `HUNTER_FLY_IMAGE` | Yes | — |
| `elephantasm_api_key` | `ELEPHANTASM_API_KEY` | Yes | — |
| `openrouter_api_key` | `OPENROUTER_API_KEY` | Yes | — |
| `machine_cpu_kind` | `HUNTER_FLY_CPU_KIND` | No | `"shared"` |
| `machine_cpus` | `HUNTER_FLY_CPUS` | No | `2` |
| `machine_memory_mb` | `HUNTER_FLY_MEMORY_MB` | No | `2048` |
| `machine_region` | `HUNTER_FLY_REGION` | No | `""` (auto) |

**`from_env()`** — loads from environment, raises `ValueError` listing all missing vars (not just the first).

**`to_machine_config(model, session_id, instruction, resume)`** — builds the Fly Machines API config dict:
- Sets `auto_destroy: True`, `restart.policy: "no"` (ephemeral machines)
- Passes API keys, model, session ID as env vars to the Hunter machine
- Optional `instruction` and `resume` flag
- Region set at top level only when non-empty

### Tests: `tests/test_fly_config.py` (11 tests)

- `from_env()`: all vars, missing vars, defaults, overrides
- `to_machine_config()`: structure, env vars, instruction, resume flag, region

---

## Task B3: FlyWorktreeManager

**Goal:** `WorktreeBackend` implementation using a local git clone of the Hunter's GitHub repo, with a real `push()`.

### File created: `hunter/backends/fly_worktree.py` (127 lines)

**`FlyWorktreeManager(WorktreeManager)`** — subclass strategy (Option A from the plan):

| Method | Behavior |
|--------|----------|
| `__init__` | Sets `worktree_path`, `branch="main"`, `repo_root` — does NOT call `super().__init__()` |
| `setup()` | Clones from GitHub if not present, `git pull --ff-only` if exists |
| `teardown()` | `shutil.rmtree()` the clone directory |
| `is_setup()` | Checks `.git` is a directory (not a file like worktrees) + `git status` sanity check |
| `push()` | `git push origin main` — the key difference from local |
| `_safe_url()` | Redacts PAT from URL for logging |
| `_require_setup()` | Guard for `push()` |
| `_find_repo_root()` | Overridden to raise — not used for clones |

**Design decisions:**
- Subclass `WorktreeManager` to inherit all file/git operations (`read_file`, `write_file`, `edit_file`, `commit`, `diff`, etc.)
- Authenticated URL: `https://{PAT}@github.com/{repo}.git`
- `is_setup()` distinguishes clones (`.git` is a directory) from worktrees (`.git` is a file)
- Clone timeout: 120 seconds

### Tests: `tests/test_fly_worktree.py` (13 tests)

- Init: attributes, authenticated URL, PAT redaction
- Setup: clone when missing, pull when exists
- Teardown: removes directory, no error if absent
- is_setup: no dir, no .git, valid clone, .git-as-file rejection
- Push: correct git command, raises if not setup
- Inherited methods: commit, read_file, write_file all work with clone path

---

## Task B4: FlyHunterController

**Goal:** `ControlBackend` implementation using the Fly Machines API for Hunter lifecycle management.

### File created: `hunter/backends/fly_control.py` (318 lines)

**`FlyHunterProcess` (dataclass):**

| Field | Purpose |
|-------|---------|
| `machine_id` | Fly machine ID |
| `session_id` | Hunter session identifier |
| `model` | LLM model name |
| `started_at` | UTC datetime of machine creation |
| `fly_app` | Fly app name |
| `pid` (property) | Returns `machine_id` (remote equivalent of PID) |
| `uptime_seconds` (property) | Elapsed time since `started_at` |

**`FlyHunterController`:**

| Method | Behavior |
|--------|----------|
| `spawn()` | Budget check → kill existing → setup worktree → `create_machine()` → `wait_for_state("started")` → return `FlyHunterProcess` |
| `kill()` | `stop_machine()` → `wait_for_state("stopped")` → `destroy_machine()` → record history → clear current |
| `redeploy()` | `worktree.push()` → `kill()` → `spawn()` (push before respawn is the key difference from local) |
| `get_status()` | Queries `get_machine()` → maps Fly state to `HunterStatus` |
| `get_logs()` | Fetches via `fly_client.get_logs()`, joins messages |
| `inject()` | Sends via Elephantasm event (falls back gracefully if unavailable) |
| `interrupt()` | `stop_machine()` (hard interrupt — no flag file needed) |
| `recover()` | `list_machines()` → find running → reconstruct `FlyHunterProcess` from machine metadata |

**Design decisions:**
- `spawn()` cleans up failed machines on start timeout (force-destroy)
- `kill()` tolerates API errors at each step (stop, wait, destroy) — logs warnings instead of raising
- `inject()` uses Elephantasm with graceful fallback — never raises
- `interrupt()` is a hard stop (machine stop); soft interrupt uses `inject()` with critical priority
- `recover()` reconnects to orphaned machines by parsing env vars from machine config
- `is_running` property queries the Fly API each time (no cached state)

### Tests: `tests/test_fly_control.py` (40 tests)

- **FlyHunterProcess:** pid, uptime
- **Spawn:** creates + waits, budget check, budget exhausted, kills existing, worktree setup, create failure, start timeout + cleanup, session ID generation, explicit session ID
- **Kill:** stop → wait → destroy sequence, returns false when no machine, records history, tolerates stop failure
- **Redeploy:** push → kill → spawn, session preservation on resume
- **Status:** running, stopped, no machine, API error
- **Logs:** returns messages, empty when no machine
- **Inject:** Elephantasm attempt, graceful fallback
- **Interrupt:** stops machine, noop when no machine
- **Recovery:** recovers running machine, returns None (no machines / all stopped / API error)
- **Properties:** worktree, budget, is_running (false/true/error), history (empty/copy)

---

## Task B5: Injection Adapter (Protocol Extension)

**Goal:** Add `inject()` and `interrupt()` to the `ControlBackend` protocol.

### File modified: `hunter/backends/base.py`

Added two methods to `ControlBackend(Protocol)`:

```python
def inject(self, instruction: str, priority: str = "normal") -> None: ...
def interrupt(self) -> None: ...
```

This extends the protocol so both local and remote backends expose the same injection interface. The inject tools call these instead of writing files directly.

---

## Task B7: Protocol Extensions + Local Parity

**Goal:** Implement `inject()` and `interrupt()` on the local `HunterController`, then update the inject tools to use them.

### File modified: `hunter/control.py` (+30 lines)

Added two methods to `HunterController`:

**`inject(instruction, priority)`:**
- Maps priority to prefix (`""`, `"HIGH PRIORITY: "`, `"CRITICAL — DROP CURRENT TASK: "`)
- Writes `{prefix}{instruction}` to `get_injection_path()`
- Preserves exact same file-based IPC behavior as before

**`interrupt()`:**
- Writes `"interrupt"` to `get_interrupt_flag_path()`
- Same flag file mechanism the Hunter's step_callback already polls

### File modified: `hunter/tools/inject_tools.py` (-48/+37 lines, net -11)

**Before:** Handlers directly wrote to injection/interrupt files, built priority prefixes, managed paths.

**After:** Handlers are thin dispatchers that call `controller.inject()` / `controller.interrupt()`. The logic moved into the controller where it can be backend-specific.

Key changes:
- `_handle_hunter_inject()` → calls `controller.inject(instruction, priority)` instead of file writes
- `_handle_hunter_interrupt()` → calls `controller.interrupt()` then `current.wait()` with fallback to `controller.kill()`
- Priority validation stays in the handler (input validation belongs at the boundary)
- Elephantasm logging remains as best-effort in the handler

### File modified: `tests/test_hunter_inject_tools.py` (-85/+94 lines)

Rewrote tests to mock `controller.inject()` / `controller.interrupt()` instead of checking file writes:
- All 3 priority levels verify `controller.inject()` called with correct args
- Interrupt tests verify `controller.interrupt()` delegation
- Added OSError handling test for `controller.inject()`
- Dispatch integration tests preserved

---

## Task B6: Wire Up the Factory

**Goal:** `create_controller(mode="fly")` returns a working `FlyHunterController`.

### File modified: `hunter/backends/__init__.py`

**Before:** `mode="fly"` raised `NotImplementedError`.

**After:**
```python
if mode == "fly":
    config = FlyConfig.from_env()
    fly_client = FlyMachinesClient(config.hunter_app_name, config.fly_api_token)
    worktree = FlyWorktreeManager(
        repo_url=config.hunter_repo,
        clone_path=Path("/data/hunter-repo"),
        github_pat=config.github_pat,
    )
    return FlyHunterController(worktree=worktree, budget=budget,
                                fly_client=fly_client, fly_config=config)
```

- Return type broadened from `HunterController` to `ControlBackend`
- Auto-detection: `FLY_APP_NAME` env var → Fly backend, otherwise local
- Clone path: `/data/hunter-repo` (Fly persistent volume mount point)

### File modified: `tests/test_hunter_backends.py`

- `TestCreateControllerFly` — no longer expects `NotImplementedError`, verifies `isinstance(controller, FlyHunterController)`
- `test_fly_passes_budget` — verifies custom `BudgetManager` is passed through
- `test_auto_selects_fly_when_env_set` — verifies auto-detection returns `FlyHunterController`
- Protocol satisfaction test updated to include `inject` and `interrupt`

---

## Task B8: Integration Test

**Status:** Deferred until Fly.io infrastructure is provisioned. The plan calls for `tests/integration/test_fly_integration.py` with `@pytest.mark.integration` (excluded from default runs), testing real machine lifecycle, clone + push, and controller spawn/kill against live Fly.io.

---

## Files Changed Summary

| File | Action | Lines | Purpose |
|------|--------|-------|---------|
| `hunter/backends/fly_api.py` | **Created** | 230 | Fly Machines REST API client |
| `hunter/backends/fly_config.py` | **Created** | 128 | Environment-based configuration |
| `hunter/backends/fly_worktree.py` | **Created** | 127 | WorktreeBackend via local clone + push |
| `hunter/backends/fly_control.py` | **Created** | 318 | ControlBackend via Fly Machines API |
| `hunter/backends/base.py` | Modified | +4 | Added `inject()`, `interrupt()` to ControlBackend |
| `hunter/backends/__init__.py` | Modified | rewritten | Wired up Fly backend in factory |
| `hunter/control.py` | Modified | +30 | Added `inject()`, `interrupt()` methods |
| `hunter/tools/inject_tools.py` | Modified | -48/+37 | Delegated to `controller.inject()` |
| `tests/test_fly_api.py` | **Created** | 208 | API client unit tests (14 tests) |
| `tests/test_fly_config.py` | **Created** | 125 | Configuration tests (11 tests) |
| `tests/test_fly_worktree.py` | **Created** | 166 | FlyWorktreeManager tests (13 tests) |
| `tests/test_fly_control.py` | **Created** | 310 | FlyHunterController tests (40 tests) |
| `tests/test_hunter_backends.py` | Modified | ~+40/-10 | Updated factory + protocol tests |
| `tests/test_hunter_inject_tools.py` | Modified | -85/+94 | Updated for controller-based injection |

**Totals:** ~803 lines production code, ~809 lines tests. 84 new tests, 2984 total passing.

---

## Success Criteria Checklist

1. `create_controller(mode="fly")` returns a working `FlyHunterController` — **done**
2. All existing tests pass (no behavior change for local mode) — **done** (2984 pass)
3. New unit tests pass (~84 new tests, all mocked) — **done**
4. Integration test passes against real Fly.io — **deferred** (B8)
5. Overseer can spawn a Hunter on a Fly machine, push code, read logs, kill it — **done** (via controller methods)
6. Injection works via Elephantasm / controller method instead of file-based IPC — **done**
7. Overseer restart reconnects to existing Hunter machine via `recover()` — **done**
