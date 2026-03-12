"""Tests for the Hunter backend abstraction layer (hunter/backends/).

Verifies:
    - Factory function ``create_controller()`` modes (local, auto, fly, invalid)
    - Budget passthrough from factory to controller
    - WorktreeManager.push() no-op
    - Protocol structural satisfaction (WorktreeManager, HunterController)
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hunter.backends import create_controller
from hunter.backends.base import ControlBackend, WorktreeBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_worktree():
    """Mock WorktreeManager that avoids real git operations."""
    wt = MagicMock()
    wt.worktree_path = Path("/tmp/fake-worktree")
    wt.branch = "hunter/live"
    wt.is_setup.return_value = True
    return wt


@pytest.fixture
def mock_budget():
    """Mock BudgetManager that avoids real file I/O."""
    budget = MagicMock()
    budget.check_budget.return_value = MagicMock(hard_stop=False, alert=False)
    return budget


@pytest.fixture
def _clean_fly_env(monkeypatch):
    """Ensure FLY_APP_NAME is not set."""
    monkeypatch.delenv("FLY_APP_NAME", raising=False)


# ---------------------------------------------------------------------------
# create_controller() tests
# ---------------------------------------------------------------------------

class TestCreateControllerLocal:
    """Factory returns a working HunterController in local mode."""

    @patch("hunter.worktree.WorktreeManager.__init__", return_value=None)
    @patch("hunter.budget.BudgetManager.__init__", return_value=None)
    def test_returns_hunter_controller(self, MockBudgetInit, MockWTInit):
        """create_controller() returns a HunterController instance."""
        from hunter.control import HunterController
        controller = create_controller(mode="local")
        assert isinstance(controller, HunterController)

    @patch("hunter.worktree.WorktreeManager.__init__", return_value=None)
    @patch("hunter.budget.BudgetManager.__init__", return_value=None)
    def test_creates_worktree_and_budget(self, MockBudgetInit, MockWTInit):
        """Factory calls WorktreeManager() and BudgetManager()."""
        controller = create_controller(mode="local")
        MockWTInit.assert_called_once()
        MockBudgetInit.assert_called_once()

    @patch("hunter.worktree.WorktreeManager.__init__", return_value=None)
    def test_passes_budget_through(self, MockWTInit, mock_budget):
        """Custom BudgetManager is used instead of creating a new one."""
        controller = create_controller(mode="local", budget=mock_budget)
        assert controller.budget is mock_budget


class TestCreateControllerAuto:
    """Auto-detection defaults to local when FLY_APP_NAME is absent."""

    @patch("hunter.worktree.WorktreeManager.__init__", return_value=None)
    @patch("hunter.budget.BudgetManager.__init__", return_value=None)
    def test_auto_defaults_to_local(self, MockBudgetInit, MockWTInit, _clean_fly_env):
        """Auto mode selects local when no FLY_APP_NAME."""
        from hunter.control import HunterController
        controller = create_controller(mode="auto")
        assert isinstance(controller, HunterController)

    def test_auto_selects_fly_when_env_set(self, monkeypatch):
        """Auto mode selects fly when FLY_APP_NAME is present."""
        monkeypatch.setenv("FLY_APP_NAME", "test-app")
        with pytest.raises(NotImplementedError, match="Fly.io backend"):
            create_controller(mode="auto")


class TestCreateControllerFly:
    """Fly.io backend is not yet implemented."""

    def test_fly_raises_not_implemented(self):
        """mode='fly' raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="Fly.io backend"):
            create_controller(mode="fly")


class TestCreateControllerInvalidMode:
    """Unknown mode raises ValueError."""

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown backend mode"):
            create_controller(mode="remote-ssh")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Unknown backend mode"):
            create_controller(mode="")


# ---------------------------------------------------------------------------
# WorktreeManager.push() tests
# ---------------------------------------------------------------------------

class TestWorktreeManagerPush:
    """push() exists and is a no-op for local worktrees."""

    def test_has_push_method(self):
        """WorktreeManager has a callable push() method."""
        from hunter.worktree import WorktreeManager
        assert hasattr(WorktreeManager, "push")
        assert callable(getattr(WorktreeManager, "push"))

    def test_push_is_noop(self, tmp_path):
        """push() doesn't raise or perform any git operations."""
        # Create a minimal git repo to construct a WorktreeManager
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init"], cwd=repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=repo, capture_output=True, check=True,
        )

        from hunter.worktree import WorktreeManager
        wt = WorktreeManager(repo_root=repo, worktree_path=tmp_path / "wt")
        # push() should not raise even when worktree isn't set up
        wt.push()  # No-op — just returns


# ---------------------------------------------------------------------------
# Protocol satisfaction tests
# ---------------------------------------------------------------------------

class TestProtocolSatisfaction:
    """Verify that existing classes structurally match the protocols."""

    def test_worktree_manager_satisfies_protocol(self):
        """WorktreeManager is structurally compatible with WorktreeBackend."""
        from hunter.worktree import WorktreeManager
        # runtime_checkable Protocol uses isinstance()
        # We can't fully check without an instance, but we can verify
        # all required methods exist on the class.
        required_methods = [
            "setup", "teardown", "is_setup", "is_clean",
            "read_file", "write_file", "edit_file", "delete_file", "list_files",
            "commit", "rollback", "diff", "diff_since",
            "get_head_commit", "get_recent_commits", "push",
        ]
        for method in required_methods:
            assert hasattr(WorktreeManager, method), f"Missing method: {method}"
            assert callable(getattr(WorktreeManager, method)), f"Not callable: {method}"

        # Check attributes exist (set in __init__)
        assert "worktree_path" in WorktreeManager.__init__.__code__.co_varnames
        assert "branch" in WorktreeManager.__init__.__code__.co_varnames

    def test_hunter_controller_satisfies_protocol(self):
        """HunterController is structurally compatible with ControlBackend."""
        from hunter.control import HunterController
        required_methods = [
            "spawn", "kill", "redeploy", "get_status", "get_logs",
        ]
        for method in required_methods:
            assert hasattr(HunterController, method), f"Missing method: {method}"
            assert callable(getattr(HunterController, method)), f"Not callable: {method}"

        # Check properties
        assert isinstance(
            HunterController.is_running, property
        ), "is_running should be a property"
        assert isinstance(
            HunterController.current, property
        ), "current should be a property"
        assert isinstance(
            HunterController.history, property
        ), "history should be a property"
