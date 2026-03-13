"""Hunter backend abstraction layer.

Provides a factory function ``create_controller()`` that centralises
controller construction. All tool modules, the Overseer loop,
and the CLI call this instead of manually wiring backends together.

Two backends are available:
    - ``"local"``: subprocess + git worktree on this machine.
    - ``"fly"``: Fly.io Machines API for remote Hunter machines.

Usage::

    from hunter.backends import create_controller

    controller = create_controller()                  # Auto-detect
    controller = create_controller(mode="local")      # Explicit local
    controller = create_controller(mode="fly")        # Fly.io remote
    controller = create_controller(budget=my_budget)   # Share a BudgetManager
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hunter.budget import BudgetManager

# Re-export protocols for convenience
from hunter.backends.base import ControlBackend, WorktreeBackend

__all__ = ["create_controller", "ControlBackend", "WorktreeBackend"]

_VALID_MODES = {"auto", "local", "fly"}


def create_controller(
    mode: str = "auto",
    budget: "BudgetManager" = None,
) -> ControlBackend:
    """Create a controller with the appropriate backends.

    Args:
        mode: Backend mode.
            - ``"auto"``: detect from environment (``FLY_APP_NAME`` present
              selects Fly.io, otherwise local).
            - ``"local"``: subprocess + git worktree on this machine.
            - ``"fly"``: Fly.io Machines API for remote Hunter machines.
        budget: Pre-configured BudgetManager instance. If ``None``, a fresh
            one is created with default config paths. Pass an existing one
            when you need to share budget state (e.g., the Overseer loop
            shares its BudgetManager with tool modules).

    Returns:
        A configured controller (ControlBackend).

    Raises:
        ValueError: If *mode* is not one of the valid modes.
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Unknown backend mode {mode!r}. Must be one of: {sorted(_VALID_MODES)}"
        )

    if mode == "auto":
        mode = "fly" if os.environ.get("FLY_APP_NAME") else "local"

    if mode == "fly":
        from hunter.backends.fly_api import FlyMachinesClient
        from hunter.backends.fly_config import FlyConfig
        from hunter.backends.fly_control import FlyHunterController
        from hunter.backends.fly_worktree import FlyWorktreeManager

        config = FlyConfig.from_env()
        fly_client = FlyMachinesClient(config.hunter_app_name, config.fly_api_token)
        worktree = FlyWorktreeManager(
            repo_url=config.hunter_repo,
            clone_path=Path("/data/hunter-repo"),
            github_pat=config.github_pat,
        )
        if budget is None:
            from hunter.budget import BudgetManager
            budget = BudgetManager()
        return FlyHunterController(
            worktree=worktree,
            budget=budget,
            fly_client=fly_client,
            fly_config=config,
        )

    # --- Local backend ---
    # Deferred imports to avoid circular dependencies and keep hunter/ optional.
    from hunter.budget import BudgetManager as BM
    from hunter.control import HunterController
    from hunter.worktree import WorktreeManager

    worktree = WorktreeManager()
    if budget is None:
        budget = BM()
    return HunterController(worktree=worktree, budget=budget)
