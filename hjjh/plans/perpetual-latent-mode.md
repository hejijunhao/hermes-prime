# Plan: `/mode` — Perpetual vs Latent Agent Operation

## Summary

Add a `/mode` slash command to the Hermes CLI that toggles the agent between two operational modes:

- **Perpetual**: The agent runs continuously 24/7, self-prompting on a heartbeat timer when idle. It follows its SOUL.md directives autonomously. Questions to the human are non-blocking — if no reply arrives within a timeout, the agent decides on its own and continues.
- **Latent** (default): The agent completes its current work then waits for human input. Standard interactive mode.

---

## Architecture Analysis

### What already exists

1. **`process_loop()`** (`cli.py:4142`) — The main CLI loop. Polls `_pending_input` queue with 0.1s timeout. When empty, it just `continue`s. This is where we inject the heartbeat.

2. **Clarify timeout** (`cli.py:3080–3104`) — The clarify callback already has a countdown + "agent will decide" fallback when the human doesn't respond. This pattern extends naturally to all agent-to-human questions in perpetual mode.

3. **SOUL.md** (`agent/prompt_builder.py:359–383`) — Already loaded into the system prompt from cwd or `~/.hermes/SOUL.md`. The agent is told to "embody its persona and tone." We'll create a SOUL.md for the deployed Hermes Prime instance that describes its autonomous operating behavior.

4. **OverseerLoop** (`hunter/overseer.py`) — Already implements the continuous loop pattern: sleep → build prompt → run agent → record → sleep. The CLI perpetual mode is conceptually similar but operates within the interactive CLI framework rather than as a headless background process.

5. **Slash command system** (`hermes_cli/commands.py` + `cli.py:2480`) — Built-in commands are a dict in `commands.py` and dispatched in `process_command()`. Adding a new command is straightforward: add to `COMMANDS`, add an `elif` branch.

### What needs to be built

Three things:

1. **Mode state + `/mode` command** — Track the current mode, toggle it, persist across sessions
2. **Heartbeat mechanism** — When perpetual + idle, auto-inject a continuation prompt after a configurable delay
3. **Non-blocking question behavior** — Reduce/enforce timeouts on clarify, sudo, and approval callbacks when in perpetual mode

---

## Detailed Design

### 1. Mode State

```python
# In HermesCLI.__init__()
self._agent_mode: str = "latent"  # "perpetual" or "latent"
self._heartbeat_interval: float = 30.0  # seconds between heartbeats when idle
self._last_agent_finish: float = 0  # monotonic timestamp of last agent completion
```

**Persistence**: Store in `~/.hermes/agent_mode.json`:
```json
{"mode": "perpetual", "heartbeat_interval": 30}
```

On startup, load from file. On `/mode` toggle, write to file. This way the mode survives session resets (`/clear`) and restarts.

### 2. The `/mode` Slash Command

Add to `hermes_cli/commands.py`:
```python
"/mode": "Toggle between perpetual (autonomous 24/7) and latent (wait for input) modes",
```

Add handler in `cli.py` `process_command()`:
```python
elif cmd_lower.startswith("/mode"):
    parts = cmd_original.split(maxsplit=1)
    if len(parts) > 1:
        target = parts[1].strip().lower()
        if target in ("perpetual", "latent"):
            self._set_mode(target)
        elif target.startswith("interval"):
            # /mode interval 60
            ...
        else:
            print(f"  Unknown mode: {target}. Use 'perpetual' or 'latent'.")
    else:
        # Toggle
        new_mode = "latent" if self._agent_mode == "perpetual" else "perpetual"
        self._set_mode(new_mode)
```

`_set_mode()` prints a status message, updates `self._agent_mode`, writes to disk, and if switching to perpetual, immediately starts the heartbeat countdown.

### 3. Heartbeat Mechanism (The Core)

This is the key piece. When the agent finishes a response and no new user input arrives, the heartbeat kicks in after `_heartbeat_interval` seconds and injects a synthetic continuation prompt.

**Where it lives**: Inside `process_loop()` (`cli.py:4142`).

Current flow:
```python
def process_loop():
    while not self._should_exit:
        try:
            user_input = self._pending_input.get(timeout=0.1)
        except queue.Empty:
            continue  # ← This is where the heartbeat goes
        ...
```

Modified flow:
```python
def process_loop():
    while not self._should_exit:
        try:
            user_input = self._pending_input.get(timeout=0.1)
        except queue.Empty:
            # Heartbeat check: in perpetual mode, if the agent isn't running
            # and enough time has passed since it last finished, inject a
            # continuation prompt
            if (self._agent_mode == "perpetual"
                    and not self._agent_running
                    and self._last_agent_finish > 0):
                elapsed = time.monotonic() - self._last_agent_finish
                if elapsed >= self._heartbeat_interval:
                    self._last_agent_finish = time.monotonic()  # Reset timer
                    user_input = self._build_heartbeat_prompt()
                    # Fall through to the chat path below
                else:
                    continue
            else:
                continue
        ...
        # Existing command check and chat dispatch follows
```

**The heartbeat prompt** is a synthetic user message that reminds the agent of its operating mode:

```python
def _build_heartbeat_prompt(self) -> str:
    """Build the synthetic continuation prompt for perpetual mode."""
    return (
        "[HEARTBEAT] You are in perpetual autonomous mode. "
        "Continue working according to your SOUL.md directives. "
        "Review your current state, decide what to do next, and take action. "
        "If you have nothing to do, check for new opportunities or perform maintenance. "
        "If you need input from the Creator, ask — but do not block on it."
    )
```

The `[HEARTBEAT]` prefix lets the agent (and SOUL.md) distinguish autonomous continuation from human messages.

**Timer reset**: After each `self.chat()` call completes (in the `finally` block at `cli.py:4204`), set `self._last_agent_finish = time.monotonic()`.

### 4. Non-Blocking Questions in Perpetual Mode

The clarify callback (`cli.py:3040–3104`) already has a timeout of 30s. For perpetual mode, we want:

- **Shorter timeout** (e.g., 10–15 seconds) — the agent shouldn't wait long
- **Different fallback message** — not just "use your best judgement" but "The Creator is not actively monitoring. Decide autonomously and note that you made this decision. You can flag important decisions for later review."

```python
# In _clarify_callback():
if self._agent_mode == "perpetual":
    timeout = 15  # Much shorter in perpetual mode
    fallback_msg = (
        "The Creator is not actively monitoring right now. "
        "Make this decision autonomously using your best judgement. "
        "If this is a high-stakes decision, note it for Creator review."
    )
else:
    timeout = 30
    fallback_msg = (
        "The user did not provide a response within the time limit. "
        "Use your best judgement to make the choice and proceed."
    )
```

Same pattern for `_approval_callback()` — in perpetual mode, auto-approve after timeout (or deny dangerous actions, depending on safety preference — see Open Questions).

### 5. SOUL.md for Hermes Prime

Create `SOUL.md` in the deployed instance's working directory (or `~/.hermes/SOUL.md`). This is what the agent reads when in perpetual mode. It should be derived from `hjjh/prime-blueprint.md` but condensed into the persona/behavioral form that SOUL.md expects.

```markdown
# Hermes Prime — SOUL

You are **Hermes Prime**, a meta-agent. Your mission is to build, deploy, monitor,
and continuously improve the Hunter — an autonomous bug bounty hunting agent.

## Perpetual Mode Behavior

When operating in perpetual mode (you'll see [HEARTBEAT] messages):

1. **Check Hunter status** — Is it running? Stuck? Producing output?
2. **Review recent activity** — Read logs, evaluate quality
3. **Decide intervention** — Do nothing / inject / edit code / redeploy
4. **Check budget** — Are you within limits?
5. **Record decisions** — Log what you observed and decided to Elephantasm

### When idle (no active Hunter, nothing to improve)
- Spawn the Hunter against a target
- Write or improve security skills
- Review and refine the Hunter's system prompt

### Non-blocking Creator interaction
- You may ask the Creator questions, but NEVER block on them
- If no response within ~15 seconds, decide autonomously
- Flag important autonomous decisions for later review
- Prefix questions with severity: [LOW], [MEDIUM], [HIGH]

### Heartbeat cadence
- Each heartbeat is a chance to evaluate and act
- Not every heartbeat needs action — sometimes "Hunter is doing fine, no intervention needed" is correct
- Avoid thrashing: don't make changes too frequently
```

### 6. Visual Feedback

When in perpetual mode, the CLI should show the mode in the status line (the bottom bar of the TUI). This involves modifying the prompt_toolkit layout.

The status line already exists — we add mode indicator:

```
perpetual ● idle (next heartbeat: 12s) | budget: $4.20/$15.00 | model: qwen/qwen3.5-72b
```

Or when latent:
```
latent ○ waiting for input | session: overseer-20260315
```

This lives in the `_get_status_line()` or equivalent method that builds the bottom toolbar.

---

## File Changes

| File | Change |
|------|--------|
| `hermes_cli/commands.py` | Add `/mode` to `COMMANDS` dict |
| `cli.py` | Add mode state to `__init__`, handler in `process_command()`, heartbeat logic in `process_loop()`, mode-aware timeouts in `_clarify_callback()` / `_approval_callback()`, status line update, `_set_mode()` / `_load_mode()` / `_build_heartbeat_prompt()` methods |
| `agent/prompt_builder.py` | (Optional) Add mode indicator to system prompt so agent knows its operating mode |
| `SOUL.md` (new, deployed) | Perpetual mode behavioral directives — not checked into this repo, created on the deployed machine |

**Estimated scope**: ~150–200 lines of new code in `cli.py`, ~5 lines in `commands.py`, optional SOUL.md template.

---

## Implementation Order

1. **Phase 1: Mode toggle** — Add `/mode` command, persist state, show in status line. No behavior change yet.
2. **Phase 2: Heartbeat** — Add the heartbeat timer in `process_loop()`, build continuation prompt. Agent starts self-prompting.
3. **Phase 3: Non-blocking questions** — Shorten timeouts in perpetual mode, improve fallback messages.
4. **Phase 4: SOUL.md template** — Write the perpetual mode behavioral guide, test on deployed instance.

---

## Key Design Decisions

### Why modify `process_loop()` instead of creating a separate loop?

The CLI already has a well-structured event loop with proper thread safety (queue-based communication, interrupt handling, clarify/approval state machines). Bolting a heartbeat onto this loop is much simpler and safer than running a parallel loop that would need its own synchronization.

### Why a synthetic user message instead of calling `run_conversation()` directly?

By injecting a heartbeat as a regular user message through the existing pipeline, we get:
- Proper conversation history management
- Session persistence to SQLite
- Interrupt handling (human can type while heartbeat-triggered agent is working)
- All existing display/formatting (tool progress, spinner, response box)
- Memory flush on context compression

### Why not reuse the OverseerLoop directly?

The OverseerLoop is designed for headless operation with a fixed toolset (`hunter-overseer`). The CLI perpetual mode needs to work with whatever toolsets the user has configured, support interactive features (clarify, approval, images), and integrate with the TUI. They share the *concept* but the implementation context is very different.

### Heartbeat prompt in conversation history

The `[HEARTBEAT]` messages will accumulate in conversation history. This is intentional — the agent needs to see its prior autonomous decisions for continuity. Context compression (`agent/context_compressor.py`) will naturally summarize old heartbeat turns as the conversation grows.

---

## Open Questions

1. **Approval callback in perpetual mode**: When the agent wants to run a dangerous command (detected by `tools/approval.py`) and the human doesn't respond, should it auto-approve or auto-deny? Current thinking: **auto-deny** for safety, since the human isn't watching. But this might prevent the agent from doing useful work. Should we have a configurable "trust level" or whitelist of auto-approvable commands?

2. **Heartbeat interval configurability**: Should `/mode interval 60` set the interval, or should it be in config.yaml? Or both (CLI overrides config)? The default 30s matches the OverseerLoop's default, but the deployed agent might want longer intervals (e.g., 5 minutes) to reduce cost.

3. **Budget integration**: Should perpetual mode have its own budget guard? e.g., "stop self-prompting when today's spend exceeds $X." The OverseerLoop has this via BudgetManager — should the CLI perpetual mode hook into the same system, or is this only relevant when the hunter-overseer toolset is active?

4. **Startup mode**: Should the agent start in perpetual mode automatically on machine boot (e.g., via an env var `HERMES_DEFAULT_MODE=perpetual`), or should it always start latent and require a `/mode perpetual` command? For the deployed Fly.io instance, auto-perpetual on boot seems right.

5. **SOUL.md vs separate perpetual config**: Should the perpetual mode behavior be entirely in SOUL.md (which is already loaded into the system prompt), or should there be a separate `perpetual.md` file? SOUL.md is simpler and already has the injection mechanism, but it means the perpetual behavior is always in the system prompt even in latent mode. Could add a conditional: only inject a `## Perpetual Mode` section when mode is active.

6. **Heartbeat prompt content**: Should the heartbeat prompt be static (always the same `[HEARTBEAT] Continue working...`) or dynamic (include current time, elapsed time since last action, any pending notifications from Telegram, etc.)? Dynamic would be more useful but adds complexity.

7. **Session continuity on restart**: If the machine reboots and the mode file says "perpetual", the agent will start self-prompting with an empty conversation history. Should it auto-resume the last session? The CLI already has `--resume` support. Could auto-resume in perpetual mode.

8. **Rate limiting / cost protection**: In perpetual mode, a misbehaving agent could burn through budget rapidly by self-prompting every 30s with long responses. Should there be a circuit breaker? e.g., "if the last N heartbeats produced no tool calls, increase interval exponentially" (backoff when idle).

9. **Multiple modes or just two?** You mentioned perpetual and latent. Should there be a third mode like "supervised" where the agent self-prompts but pauses for approval on every action? Or is that over-engineering it?

10. **Notification on mode switch**: When switching to perpetual, should the agent get a special message like "You are now in perpetual mode. The Creator may not be watching. Operate autonomously."? This ensures the agent's *next* response is mode-aware even before the heartbeat kicks in.
