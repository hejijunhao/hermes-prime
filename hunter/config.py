"""Hunter subsystem configuration — paths, constants, and defaults.

All Hunter-specific state lives under ~/.hermes/hunter/ to keep it
isolated from the main Hermes agent state. This module is the single
source of truth for path resolution and default values.
"""

from pathlib import Path

from hermes_cli.config import get_hermes_home


# =============================================================================
# Paths
# =============================================================================

def get_hunter_home() -> Path:
    """~/.hermes/hunter/ — root for all Hunter-specific state."""
    return get_hermes_home() / "hunter"


def get_hunter_worktree_path() -> Path:
    """Where the Hunter's git worktree lives on disk."""
    return get_hunter_home() / "worktree"


def get_hunter_state_db_path() -> Path:
    """Local SQLite for operational state (targets queue, reports queue)."""
    return get_hunter_home() / "state.db"


def get_budget_config_path() -> Path:
    """~/.hermes/hunter/budget.yaml — watched config for budget constraints."""
    return get_hunter_home() / "budget.yaml"


def get_spend_ledger_path() -> Path:
    """Append-only JSONL spend log for cost tracking."""
    return get_hunter_home() / "spend.jsonl"


def get_injection_dir() -> Path:
    """Directory for Overseer → Hunter runtime instruction files."""
    return get_hunter_home() / "injections"


def get_injection_path() -> Path:
    """The current active injection file the Hunter polls each iteration."""
    return get_injection_dir() / "current.md"


def get_interrupt_flag_path() -> Path:
    """Flag file the Overseer writes to signal the Hunter to stop."""
    return get_hunter_home() / "interrupt.flag"


def get_hunter_log_dir() -> Path:
    """Directory for Hunter process stdout/stderr logs."""
    return get_hunter_home() / "logs"


def get_anima_cache_path() -> Path:
    """Local cache of Elephantasm Anima IDs."""
    return get_hunter_home() / "animas.json"


def ensure_hunter_home():
    """Create the ~/.hermes/hunter/ directory structure if it doesn't exist."""
    dirs = [
        get_hunter_home(),
        get_injection_dir(),
        get_hunter_log_dir(),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Git
# =============================================================================

HUNTER_BRANCH = "hunter/live"


# =============================================================================
# Agent defaults
# =============================================================================

# The toolset the Hunter agent runs with. In Phase 1 this is the standard
# CLI toolset; Phase 2 will add a dedicated "hermes-prime" toolset with
# security-specific tools.
HUNTER_DEFAULT_TOOLSETS = ["hermes-cli"]

# Default open-source model for the Hunter (medium tier).
# The Overseer can change this at runtime via hunter_model_set.
HUNTER_DEFAULT_MODEL = "qwen/qwen3.5-32b"

# Maximum LLM iterations per Hunter session before it stops.
HUNTER_MAX_ITERATIONS = 200


# =============================================================================
# Elephantasm
# =============================================================================

OVERSEER_ANIMA_NAME = "hermes-prime"
HUNTER_ANIMA_NAME = "hermes-prime-hunter"


# =============================================================================
# Overseer
# =============================================================================

# Seconds between Overseer loop iterations (how often it checks on the Hunter).
OVERSEER_DEFAULT_CHECK_INTERVAL = 30.0

# Max LLM iterations the Overseer uses per loop iteration (not total).
OVERSEER_MAX_ITERATIONS_PER_LOOP = 20
