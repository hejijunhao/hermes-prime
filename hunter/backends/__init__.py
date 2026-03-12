"""Hunter backend abstraction layer.

Provides a factory function ``create_controller()`` that centralises
HunterController construction. All tool modules, the Overseer loop,
and the CLI call this instead of manually wiring WorktreeManager +
BudgetManager + HunterController.

Phase A ships with only the "local" backend (subprocess + git worktree).
Phase B will add a "fly" backend (Fly.io Machines API).

Usage::

    from hunter.backends import create_controller

    controller = create_controller()                  # Auto-detect
    controller = create_controller(mode="local")      # Explicit local
    controller = create_controller(budget=my_budget)   # Share a BudgetManager
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hunter.budget import BudgetManager
    from hunter.control import HunterController

# Re-export protocols for convenience
from hunter.backends.base import ControlBackend, WorktreeBackend

__all__ = ["create_controller", "ControlBackend", "WorktreeBackend"]

_VALID_MODES = {"auto", "local", "fly"}


def create_controller(
    mode: str = "auto",
    budget: "BudgetManager" = None,
) -> "HunterController":
    """Create a HunterController with the appropriate backends.

    Args:
        mode: Backend mode.
            - ``"auto"``: detect from environment (``FLY_APP_NAME`` present
              selects Fly.io, otherwise local).
            - ``"local"``: subprocess + git worktree on this machine.
            - ``"fly"``: Fly.io Machines API (Phase B — not yet implemented).
        budget: Pre-configured BudgetManager instance. If ``None``, a fresh
            one is created with default config paths. Pass an existing one
            when you need to share budget state (e.g., the Overseer loop
            shares its BudgetManager with tool modules).

    Returns:
        A configured HunterController.

    Raises:
        ValueError: If *mode* is not one of the valid modes.
        NotImplementedError: If ``mode="fly"`` (Phase B).
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Unknown backend mode {mode!r}. Must be one of: {sorted(_VALID_MODES)}"
        )

    if mode == "auto":
        mode = "fly" if os.environ.get("FLY_APP_NAME") else "local"

    if mode == "fly":
        raise NotImplementedError(
            "Fly.io backend not yet implemented (Phase B). "
            "Use mode='local' or unset FLY_APP_NAME."
        )

    # --- Local backend ---
    # Deferred imports to avoid circular dependencies and keep hunter/ optional.
    from hunter.budget import BudgetManager
    from hunter.control import HunterController
    from hunter.worktree import WorktreeManager

    worktree = WorktreeManager()
    if budget is None:
        budget = BudgetManager()
    return HunterController(worktree=worktree, budget=budget)
