# Task 4: Hunter Process Controller — Completion Notes

**Status:** Complete
**Date:** 2026-03-11

---

## What Was Done

Implemented `hunter/control.py` — the Hunter process lifecycle manager, and `hunter/runner.py` — the subprocess entry point that runs an AIAgent with interrupt/injection hooks. Together, these form the core IPC bridge between the Overseer and Hunter.

---

## Files Modified

### `hunter/control.py` (replaced stub)

**~370 lines.** Contains:

### Classes

| Class | Purpose |
|-------|---------|
| `HunterProcess` | Single process lifecycle — spawn, kill, poll, output capture |
| `HunterController` | Singleton ensuring one Hunter at a time, budget-gated spawning |
| `HunterStatus` | Dataclass: running, pid, session_id, model, uptime, exit_code, error |

### HunterProcess Methods

#### Lifecycle

| Method | Purpose |
|--------|---------|
| `spawn(instruction)` | Launch `python -m hunter.runner` as subprocess with output capture |
| `kill(timeout)` | Three-stage shutdown: flag file → SIGTERM → SIGKILL |
| `wait(timeout)` | Block until process exits. Raises `TimeoutError` |

#### Status

| Method | Returns | Purpose |
|--------|---------|---------|
| `poll()` | `HunterStatus` | Non-blocking health check |
| `is_alive()` | `bool` | Quick running check |
| `uptime_seconds` | `float` | Property — runtime duration |
| `get_logs(tail)` | `str` | Last N lines from rolling buffer |
| `get_full_log_path()` | `Path` | Persistent log file on disk |

#### Internal

| Method | Purpose |
|--------|---------|
| `_build_command(instruction)` | Assemble `python -m hunter.runner` CLI args |
| `_build_env()` | Set PYTHONPATH to include worktree |
| `_capture_output()` | Background thread: stdout → rolling buffer + log file |
| `_mark_exited()` | Record exit code and uptime on process death |
| `_write_interrupt_flag(msg)` | Write flag file for graceful shutdown |
| `_clear_interrupt_flag()` | Clean up flag file after process exits |

### HunterController Methods

| Method | Purpose |
|--------|---------|
| `spawn(model, instruction, resume, session_id)` | Budget check → kill existing → create HunterProcess → spawn |
| `kill()` | Kill current Hunter, record to history |
| `redeploy(resume, model)` | Kill + spawn from (potentially modified) worktree |
| `get_status()` | Current HunterStatus or "not started" default |
| `get_logs(tail)` | Delegate to current process |
| `is_running` | Property — is Hunter alive? |
| `current` | Property — current HunterProcess or None |
| `history` | Property — list of past process run summaries |

---

### `hunter/runner.py` (replaced stub)

**~230 lines.** Standalone entry point for the Hunter subprocess.

| Function | Purpose |
|----------|---------|
| `main()` | Parse args → load session → create AIAgent → run → report results |
| `_read_injection_file()` | Read and consume Overseer's injection (rename to .consumed) |
| `_check_interrupt_flag()` | Check for Overseer's interrupt flag file |
| `_build_hunter_ephemeral_prompt()` | Assemble ephemeral prompt from memory + injections |
| `_make_step_callback(agent)` | Create iteration hook for interrupt/injection polling |
| `_load_session_history(session_id)` | Load conversation history from SessionDB for resume |

---

## How It Works

### Process Lifecycle

```
Overseer calls controller.spawn():
  1. Check budget → refuse if hard_stop
  2. Kill any existing Hunter (record to history)
  3. Ensure worktree is set up
  4. Create HunterProcess(worktree_path, model, session_id)
  5. process.spawn(instruction)
     → subprocess.Popen("python -m hunter.runner --session-id X --model Y ...")
     → CWD = worktree path
     → PYTHONPATH includes worktree (so Hunter loads its own code)
     → Daemon thread captures stdout → rolling buffer + log file
  6. Return HunterProcess to caller
```

### Three-Stage Kill

```
controller.kill():
  1. Write interrupt.flag  → Hunter's step_callback sees it → agent.interrupt()
     Wait timeout/3...
  2. SIGTERM             → OS-level graceful termination
     Wait timeout/3...
  3. SIGKILL             → Force kill (last resort)
     Wait timeout/3...
  4. Clear interrupt flag
```

### Runner Entry Point (hunter/runner.py)

```
python -m hunter.runner --session-id abc --model qwen/qwen3.5-32b

  1. Parse args
  2. Read initial injection file (if any)
  3. Build ephemeral system prompt (memory + injection)
  4. Create AIAgent(model, toolsets, ephemeral_system_prompt, ...)
  5. Wire step_callback that checks:
     - interrupt.flag → agent.interrupt(msg)
     - injections/current.md → append to ephemeral_system_prompt
  6. Run agent.run_conversation(instruction)
  7. Print final response to stdout (captured by Overseer)
  8. Exit
```

### Injection Flow

```
Overseer writes: ~/.hermes/hunter/injections/current.md
  ↓
Hunter's step_callback (each iteration):
  - Reads current.md
  - Renames to current.md.consumed
  - Appends content to ephemeral_system_prompt
  - Next API call includes the instruction
  ↓
Overseer sees .consumed file → knows injection was received
```

---

## Design Decisions

### Why subprocess (not in-process)

Code evolution requires it. The Overseer must be able to:
1. Kill the Hunter without affecting itself
2. Modify the Hunter's source code on disk
3. Restart with the modified code (new Python import)
4. Run different versions of the codebase simultaneously

### Why merged stdout/stderr (`stderr=subprocess.STDOUT`)

Simplifies output capture — one stream, one thread, one buffer. The Hunter's structured output (tool calls, findings) goes to stdout; errors and warnings also go there. The Overseer doesn't need to distinguish between them for monitoring.

### Why line-buffered output

`bufsize=1` + `text=True` gives us line-by-line capture. This means the Overseer sees Hunter output in real-time (as each line is flushed), not in chunks. Essential for monitoring and log display.

### Why rolling buffer + persistent log file

The in-memory buffer (capped at ~1MB) is for quick `get_logs(tail=50)` calls — what the Overseer reads each iteration. The persistent log file (`~/.hermes/hunter/logs/<session>-<timestamp>.log`) is for post-mortem analysis and debugging.

### Why Elephantasm is stubbed

Task 5 handles Elephantasm integration. The runner has the hooks in place (`memory_context = None` + injection reading), so Task 5 can wire in without restructuring.

### Why `_build_env` puts worktree on PYTHONPATH

When the Overseer modifies the Hunter's code and redeploys, the new code must be what the subprocess loads. By prepending the worktree path to PYTHONPATH, `import run_agent` resolves to the worktree's version, not the main repo's.

---

## Tests Run (35/35 passed)

| # | Test | What It Verifies |
|---|------|-----------------|
| 1 | HunterStatus running summary | Correct format with pid, session, model |
| 2 | HunterStatus stopped summary | Shows exit code |
| 3 | HunterStatus to_dict | Serialisation works |
| 4 | spawn and poll | Real subprocess starts, poll() reports running |
| 5 | kill graceful | Three-stage kill terminates process |
| 6 | kill when not running | Returns False |
| 7 | process exit detected | poll() detects natural exit |
| 8 | nonzero exit code | Exit code 42 captured as error |
| 9 | output capture | stdout → rolling buffer + log file |
| 10 | wait timeout | Raises TimeoutError on stuck process |
| 11 | spawn twice raises | RuntimeError if already running |
| 12 | uptime increases | uptime_seconds grows while running |
| 13 | build command | Correct CLI args for hunter.runner |
| 14 | build env PYTHONPATH | Worktree prepended to PYTHONPATH |
| 15 | controller spawn | Creates running process, budget-gated |
| 16 | controller spawn kills existing | Old Hunter killed, recorded to history |
| 17 | budget hard stop | RuntimeError when budget exhausted |
| 18 | controller kill none | Returns False when no Hunter |
| 19 | controller status none | Sensible defaults when never spawned |
| 20 | controller logs none | Empty string when no Hunter |
| 21 | controller redeploy | Kill + restart with same session_id |
| 22 | redeploy model change | Model override applied to new process |
| 23 | controller repr | Works for both states |
| 24 | interrupt flag write/read | Flag file round-trip |
| 25 | no interrupt flag | Returns None |
| 26 | injection read and consume | File read + renamed to .consumed |
| 27 | no injection | Returns None |
| 28 | empty injection | Cleaned up, returns None |
| 29 | ephemeral with memory + injection | Both sections in prompt |
| 30 | ephemeral injection only | Only injection section |
| 31 | ephemeral nothing | Returns None |
| 32 | ephemeral memory only | Only memory section |
| 33 | step callback interrupt | Detects flag, calls agent.interrupt() |
| 34 | step callback injection | Reads file, updates ephemeral prompt |
| 35 | E2E interrupt via flag file | Real subprocess exits on flag file |

All tests use temporary git repos and mock paths — nothing touches `~/.hermes/`.

---

## What's Next

The control layer is consumed by:
- **Task 5** (`memory.py`): Wires Elephantasm into runner.py's memory_context and step_callback
- **Task 6** (`process_tools.py`): `hunter_spawn`, `hunter_kill`, `hunter_status` wrap HunterController
- **Task 7** (`inject_tools.py`): `hunter_inject` writes the injection file, `hunter_interrupt` writes the flag file
- **Task 8** (`code_tools.py`): `hunter_redeploy` calls HunterController.redeploy()
- **Task 10** (`overseer.py`): OverseerLoop uses HunterController for all process management
- **Task 12** (`cli.py`): `hermes hunter spawn/kill/status` delegate to HunterController
