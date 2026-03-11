"""Entry point for the Hunter subprocess.

Invoked by the Overseer via HunterProcess.spawn(). This runs an AIAgent
from the Hunter's worktree with injection file polling and interrupt flag
checking wired into the iteration loop.

Usage:
    python -m hunter.runner --session-id <id> --model <model> [--resume] [--instruction "..."]

The runner integrates with the Overseer's control mechanisms:
    - Interrupt flag: ~/.hermes/hunter/interrupt.flag
      Checked after each agent iteration. If present, the agent exits gracefully.
    - Injection file: ~/.hermes/hunter/injections/current.md
      Checked after each iteration. If present, its content is appended to the
      agent's ephemeral system prompt for the next API call, then consumed
      (renamed to .consumed).

Elephantasm integration is deferred to Task 5 — the hooks are in place
but use no-op stubs until then.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Injection file handling
# =============================================================================

def _read_injection_file() -> Optional[str]:
    """Read and consume the Overseer's injection file if it exists.

    Returns the instruction text, or None if no injection is pending.
    Renames the file to .consumed so it isn't re-read.
    """
    from hunter.config import get_injection_path

    injection_path = get_injection_path()
    if not injection_path.exists():
        return None

    try:
        content = injection_path.read_text(encoding="utf-8").strip()
        if not content:
            injection_path.unlink(missing_ok=True)
            return None

        # Consume: rename to .consumed so the Overseer knows it was read
        consumed_path = injection_path.with_suffix(".md.consumed")
        try:
            injection_path.rename(consumed_path)
        except OSError:
            # If rename fails, just delete — better than re-reading
            injection_path.unlink(missing_ok=True)

        logger.info("Consumed injection: %s", content[:200])
        return content
    except OSError as e:
        logger.warning("Failed to read injection file: %s", e)
        return None


def _check_interrupt_flag() -> Optional[str]:
    """Check if the Overseer has requested an interrupt.

    Returns the interrupt message if the flag file exists, otherwise None.
    Does NOT remove the flag — that's the Overseer's responsibility after
    the process exits.
    """
    from hunter.config import get_interrupt_flag_path

    flag_path = get_interrupt_flag_path()
    if not flag_path.exists():
        return None

    try:
        return flag_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


# =============================================================================
# Ephemeral prompt building
# =============================================================================

def _build_hunter_ephemeral_prompt(
    memory_context: Optional[str] = None,
    injection: Optional[str] = None,
) -> Optional[str]:
    """Build the Hunter's ephemeral system prompt from memory + injections.

    This prompt is appended at API-call time but never persisted to
    conversation history, so it doesn't pollute the session.
    """
    parts = []

    if memory_context:
        parts.append("## Elephantasm Memory Context")
        parts.append(memory_context)

    if injection:
        parts.append("## Overseer Instruction")
        parts.append(injection)

    if not parts:
        return None
    return "\n\n".join(parts)


# =============================================================================
# Step callback — the hook wired into AIAgent's iteration loop
# =============================================================================

def _make_step_callback(agent):
    """Create a step_callback that checks for interrupts and injections.

    This is called by AIAgent after each tool-calling iteration. It:
    1. Checks for the interrupt flag and calls agent.interrupt() if found.
    2. Checks for injection files and updates the ephemeral prompt.
    3. Logs iteration progress.

    Args:
        agent: The AIAgent instance to control.

    Returns:
        A callable suitable for AIAgent.step_callback.
    """
    _iteration_count = [0]  # Mutable counter in closure

    def step_callback(api_call_count, prev_tools):
        _iteration_count[0] += 1
        iteration = _iteration_count[0]

        # Check interrupt flag
        interrupt_msg = _check_interrupt_flag()
        if interrupt_msg:
            logger.info(
                "Interrupt flag detected at iteration %d: %s",
                iteration, interrupt_msg[:200],
            )
            agent.interrupt(interrupt_msg)
            return

        # Check for new injection
        injection = _read_injection_file()
        if injection:
            # Update the ephemeral system prompt for the next API call
            current = agent.ephemeral_system_prompt or ""
            new_section = f"\n\n## Overseer Instruction (injected at iteration {iteration})\n{injection}"
            agent.ephemeral_system_prompt = current + new_section
            logger.info("Applied injection at iteration %d", iteration)

        # Progress logging
        if iteration % 10 == 0:
            tool_names = ", ".join(prev_tools) if prev_tools else "none"
            logger.info(
                "Hunter iteration %d (api_calls=%d, last_tools=%s)",
                iteration, api_call_count, tool_names,
            )

    return step_callback


# =============================================================================
# Main entry point
# =============================================================================

def main():
    """Run the Hunter agent as a subprocess."""
    parser = argparse.ArgumentParser(
        description="Hermes Hunter — autonomous vulnerability hunting agent subprocess.",
    )
    parser.add_argument(
        "--session-id",
        required=True,
        help="Unique session identifier for persistence and tracking.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model to use (e.g., 'qwen/qwen3.5-32b').",
    )
    parser.add_argument(
        "--toolsets",
        default=None,
        help="Comma-separated list of toolsets to enable.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum LLM iterations before stopping.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the previous session's conversation history.",
    )
    parser.add_argument(
        "--instruction",
        default="Begin autonomous vulnerability hunting.",
        help="Initial instruction (user message) for the Hunter.",
    )

    args = parser.parse_args()

    # Deferred imports to avoid loading heavy deps at parse time
    from hunter.config import (
        HUNTER_DEFAULT_MODEL,
        HUNTER_DEFAULT_TOOLSETS,
        HUNTER_MAX_ITERATIONS,
    )

    model = args.model or HUNTER_DEFAULT_MODEL
    toolsets = args.toolsets.split(",") if args.toolsets else list(HUNTER_DEFAULT_TOOLSETS)
    max_iterations = args.max_iterations or HUNTER_MAX_ITERATIONS

    # Configure logging for subprocess
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info(
        "Hunter runner starting: session=%s model=%s toolsets=%s max_iter=%d resume=%s",
        args.session_id, model, toolsets, max_iterations, args.resume,
    )

    # ── Elephantasm memory (Task 5 stub) ─────────────────────────────────
    # The memory bridge will be wired in Task 5. For now, we skip injection
    # and extraction but leave the hooks in place.
    memory_context = None

    # ── Check for initial injection ──────────────────────────────────────
    initial_injection = _read_injection_file()

    # ── Build ephemeral prompt ───────────────────────────────────────────
    ephemeral = _build_hunter_ephemeral_prompt(
        memory_context=memory_context,
        injection=initial_injection,
    )

    # ── Create the agent ─────────────────────────────────────────────────
    try:
        from run_agent import AIAgent
    except ImportError:
        logger.error(
            "Cannot import AIAgent from run_agent. "
            "Ensure the Hermes repo is on PYTHONPATH."
        )
        sys.exit(1)

    conversation_history = None
    if args.resume:
        conversation_history = _load_session_history(args.session_id)

    agent = AIAgent(
        model=model,
        enabled_toolsets=toolsets,
        max_iterations=max_iterations,
        ephemeral_system_prompt=ephemeral,
        session_id=args.session_id,
        quiet_mode=True,
        platform="hunter",
    )

    # Wire up the step callback for interrupt/injection polling
    agent.step_callback = _make_step_callback(agent)

    # ── Run ──────────────────────────────────────────────────────────────
    logger.info("Hunter agent running...")
    start_time = time.monotonic()

    try:
        result = agent.run_conversation(
            user_message=args.instruction,
            conversation_history=conversation_history,
            task_id=args.session_id,
        )
    except KeyboardInterrupt:
        logger.info("Hunter interrupted by signal.")
        result = {"interrupted": True, "final_response": ""}
    except Exception as e:
        logger.error("Hunter agent error: %s", e, exc_info=True)
        result = {"failed": True, "error": str(e), "final_response": ""}

    elapsed = time.monotonic() - start_time

    # ── Report results ───────────────────────────────────────────────────
    final_response = result.get("final_response", "")
    interrupted = result.get("interrupted", False)
    failed = result.get("failed", False)

    logger.info(
        "Hunter finished: elapsed=%.0fs interrupted=%s failed=%s response_len=%d",
        elapsed, interrupted, failed, len(final_response),
    )

    # Print final response to stdout (captured by Overseer's log reader)
    if final_response:
        print(f"\n--- Hunter Final Response ---\n{final_response}\n---")

    # Exit with appropriate code
    if failed:
        sys.exit(1)
    sys.exit(0)


# =============================================================================
# Session resume helper
# =============================================================================

def _load_session_history(session_id: str):
    """Load conversation history from SessionDB for resume.

    Returns a list of message dicts, or None if the session is not found.
    """
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        session = db.get_session(session_id)
        if session is None:
            logger.info("No previous session found for %s — starting fresh.", session_id)
            return None
        history = db.get_messages_as_conversation(session_id)
        logger.info(
            "Resumed session %s with %d messages.",
            session_id, len(history),
        )
        return history
    except ImportError:
        logger.warning("SessionDB not available — cannot resume session.")
        return None
    except Exception as e:
        logger.warning("Failed to load session %s: %s", session_id, e)
        return None


if __name__ == "__main__":
    main()
