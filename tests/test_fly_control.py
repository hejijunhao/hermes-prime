"""Tests for hunter.backends.fly_control — FlyHunterController."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from hunter.backends.fly_api import FlyAPIError
from hunter.backends.fly_control import FlyHunterController, FlyHunterProcess
from hunter.backends.fly_config import FlyConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fly_config():
    return FlyConfig(
        fly_api_token="tok",
        hunter_app_name="test-hunter-app",
        github_pat="ghp_test",
        hunter_repo="user/hunter",
        machine_image="registry.fly.io/hunter:latest",
        elephantasm_api_key="elk-key",
        openrouter_api_key="or-key",
    )


@pytest.fixture
def mock_fly_client():
    client = MagicMock()
    client.create_machine.return_value = {"id": "m-abc123", "state": "created"}
    client.wait_for_state.return_value = {"id": "m-abc123", "state": "started"}
    client.get_machine.return_value = {"id": "m-abc123", "state": "started"}
    client.stop_machine.return_value = None
    client.destroy_machine.return_value = None
    client.list_machines.return_value = []
    client.get_logs.return_value = [{"message": "hello"}]
    return client


@pytest.fixture
def mock_worktree():
    wt = MagicMock()
    wt.is_setup.return_value = True
    return wt


@pytest.fixture
def mock_budget():
    budget = MagicMock()
    budget.check_budget.return_value = MagicMock(
        hard_stop=False, alert=False, percent_used=25.0,
    )
    return budget


@pytest.fixture
def controller(mock_worktree, mock_budget, mock_fly_client, fly_config):
    return FlyHunterController(
        worktree=mock_worktree,
        budget=mock_budget,
        fly_client=mock_fly_client,
        fly_config=fly_config,
    )


# ---------------------------------------------------------------------------
# FlyHunterProcess tests
# ---------------------------------------------------------------------------

class TestFlyHunterProcess:

    def test_pid_returns_machine_id(self):
        proc = FlyHunterProcess(
            machine_id="m-xyz",
            session_id="s-001",
            model="qwen/qwen3.5-32b",
            started_at=datetime.now(timezone.utc),
            fly_app="app",
        )
        assert proc.pid == "m-xyz"

    def test_uptime_seconds(self):
        proc = FlyHunterProcess(
            machine_id="m-xyz",
            session_id="s-001",
            model="qwen/qwen3.5-32b",
            started_at=datetime.now(timezone.utc),
            fly_app="app",
        )
        assert proc.uptime_seconds >= 0
        assert proc.uptime_seconds < 5  # Should be near-instant


# ---------------------------------------------------------------------------
# Spawn tests
# ---------------------------------------------------------------------------

class TestSpawn:

    def test_creates_machine_and_waits(self, controller, mock_fly_client):
        proc = controller.spawn(model="qwen/qwen3.5-32b")

        mock_fly_client.create_machine.assert_called_once()
        mock_fly_client.wait_for_state.assert_called_once_with(
            "m-abc123", "started", timeout=60,
        )
        assert proc.machine_id == "m-abc123"
        assert proc.model == "qwen/qwen3.5-32b"
        assert controller.current is proc

    def test_checks_budget(self, controller, mock_budget):
        controller.spawn()
        mock_budget.reload.assert_called_once()
        mock_budget.check_budget.assert_called_once()

    def test_raises_on_budget_exhausted(self, controller, mock_budget):
        mock_budget.check_budget.return_value = MagicMock(
            hard_stop=True, percent_used=110.0,
        )
        with pytest.raises(RuntimeError, match="Budget exhausted"):
            controller.spawn()

    def test_kills_existing_before_spawn(self, controller, mock_fly_client):
        # First spawn
        controller.spawn()
        # Second spawn should kill the first
        controller.spawn()

        # stop + destroy called for the first machine
        assert mock_fly_client.stop_machine.call_count >= 1
        assert mock_fly_client.destroy_machine.call_count >= 1

    def test_sets_up_worktree_if_needed(self, controller, mock_worktree):
        mock_worktree.is_setup.return_value = False
        controller.spawn()
        mock_worktree.setup.assert_called_once()

    def test_raises_on_machine_create_failure(self, controller, mock_fly_client):
        mock_fly_client.create_machine.side_effect = FlyAPIError(
            500, "Internal error",
        )
        with pytest.raises(RuntimeError, match="Failed to create"):
            controller.spawn()

    def test_cleans_up_on_start_timeout(self, controller, mock_fly_client):
        mock_fly_client.wait_for_state.side_effect = FlyAPIError(
            0, "Timed out waiting",
        )
        with pytest.raises(RuntimeError, match="failed to start"):
            controller.spawn()
        # Should try to destroy the failed machine
        mock_fly_client.destroy_machine.assert_called_once_with(
            "m-abc123", force=True,
        )

    def test_generates_session_id(self, controller):
        proc = controller.spawn()
        assert proc.session_id.startswith("hunter-")

    def test_uses_explicit_session_id(self, controller):
        proc = controller.spawn(session_id="custom-session")
        assert proc.session_id == "custom-session"


# ---------------------------------------------------------------------------
# Kill tests
# ---------------------------------------------------------------------------

class TestKill:

    def test_stops_waits_destroys(self, controller, mock_fly_client):
        controller.spawn()
        result = controller.kill()

        assert result is True
        mock_fly_client.stop_machine.assert_called_with("m-abc123", timeout=30)
        mock_fly_client.destroy_machine.assert_called_with("m-abc123")
        assert controller.current is None

    def test_returns_false_when_no_machine(self, controller):
        assert controller.kill() is False

    def test_records_history(self, controller):
        controller.spawn()
        controller.kill()
        assert len(controller.history) >= 1
        assert controller.history[-1]["machine_id"] == "m-abc123"

    def test_tolerates_stop_failure(self, controller, mock_fly_client):
        controller.spawn()
        mock_fly_client.stop_machine.side_effect = FlyAPIError(404, "not found")
        # Should not raise
        result = controller.kill()
        assert result is True


# ---------------------------------------------------------------------------
# Redeploy tests
# ---------------------------------------------------------------------------

class TestRedeploy:

    def test_pushes_then_kills_then_spawns(self, controller, mock_worktree, mock_fly_client):
        controller.spawn()
        mock_fly_client.create_machine.return_value = {"id": "m-new456"}
        mock_fly_client.wait_for_state.return_value = {"id": "m-new456", "state": "started"}

        proc = controller.redeploy()

        mock_worktree.push.assert_called_once()
        assert proc.machine_id == "m-new456"

    def test_preserves_session_on_resume(self, controller, mock_fly_client):
        first = controller.spawn(session_id="keep-me")
        mock_fly_client.create_machine.return_value = {"id": "m-new456"}
        mock_fly_client.wait_for_state.return_value = {"id": "m-new456", "state": "started"}

        proc = controller.redeploy(resume_session=True)
        assert proc.session_id == "keep-me"


# ---------------------------------------------------------------------------
# Status tests
# ---------------------------------------------------------------------------

class TestGetStatus:

    def test_running_status(self, controller, mock_fly_client):
        controller.spawn()
        mock_fly_client.get_machine.return_value = {"state": "started"}

        status = controller.get_status()
        assert status.running is True
        assert status.session_id != ""

    def test_stopped_status(self, controller, mock_fly_client):
        controller.spawn()
        mock_fly_client.get_machine.return_value = {"state": "stopped"}

        status = controller.get_status()
        assert status.running is False

    def test_no_machine_status(self, controller):
        status = controller.get_status()
        assert status.running is False
        assert "No Hunter" in status.error

    def test_api_error_status(self, controller, mock_fly_client):
        controller.spawn()
        mock_fly_client.get_machine.side_effect = FlyAPIError(500, "fail")

        status = controller.get_status()
        assert status.running is False
        assert "Failed to query" in status.error


# ---------------------------------------------------------------------------
# Logs tests
# ---------------------------------------------------------------------------

class TestGetLogs:

    def test_returns_log_messages(self, controller, mock_fly_client):
        controller.spawn()
        logs = controller.get_logs(tail=50)
        assert "hello" in logs
        mock_fly_client.get_logs.assert_called_once_with("m-abc123", tail=50)

    def test_empty_when_no_machine(self, controller):
        assert controller.get_logs() == ""


# ---------------------------------------------------------------------------
# Inject tests
# ---------------------------------------------------------------------------

class TestInject:

    @patch("hunter.backends.fly_control.OverseerMemoryBridge", create=True)
    @patch("hunter.backends.fly_control.AnimaManager", create=True)
    def test_inject_via_elephantasm(self, mock_anima_mgr, mock_bridge_cls, controller):
        """inject() attempts to use Elephantasm."""
        # Elephantasm will fail in tests (modules not available),
        # but we verify it doesn't raise
        controller.inject("Focus on IDOR", priority="high")
        # No exception = success (falls back gracefully)

    def test_inject_does_not_raise(self, controller):
        """inject() never raises even without Elephantasm."""
        controller.inject("test instruction", priority="normal")


# ---------------------------------------------------------------------------
# Interrupt tests
# ---------------------------------------------------------------------------

class TestInterrupt:

    def test_stops_machine(self, controller, mock_fly_client):
        controller.spawn()
        controller.interrupt()
        mock_fly_client.stop_machine.assert_called_with("m-abc123")

    def test_noop_when_no_machine(self, controller, mock_fly_client):
        controller.interrupt()
        mock_fly_client.stop_machine.assert_not_called()


# ---------------------------------------------------------------------------
# Recovery tests
# ---------------------------------------------------------------------------

class TestRecover:

    def test_recovers_running_machine(self, controller, mock_fly_client):
        mock_fly_client.list_machines.return_value = [
            {
                "id": "m-recovered",
                "state": "started",
                "created_at": "2026-03-10T12:00:00Z",
                "config": {
                    "env": {
                        "SESSION_ID": "s-old",
                        "HUNTER_MODEL": "qwen/qwen3.5-32b",
                    },
                },
            },
        ]

        proc = controller.recover()
        assert proc is not None
        assert proc.machine_id == "m-recovered"
        assert proc.session_id == "s-old"
        assert controller.current is proc

    def test_returns_none_when_no_machines(self, controller, mock_fly_client):
        mock_fly_client.list_machines.return_value = []
        assert controller.recover() is None

    def test_returns_none_when_all_stopped(self, controller, mock_fly_client):
        mock_fly_client.list_machines.return_value = [
            {"id": "m-stopped", "state": "stopped"},
        ]
        assert controller.recover() is None

    def test_handles_api_error(self, controller, mock_fly_client):
        mock_fly_client.list_machines.side_effect = FlyAPIError(500, "fail")
        assert controller.recover() is None


# ---------------------------------------------------------------------------
# Properties tests
# ---------------------------------------------------------------------------

class TestProperties:

    def test_worktree(self, controller, mock_worktree):
        assert controller.worktree is mock_worktree

    def test_budget(self, controller, mock_budget):
        assert controller.budget is mock_budget

    def test_is_running_false_initially(self, controller):
        assert controller.is_running is False

    def test_is_running_true_when_started(self, controller, mock_fly_client):
        controller.spawn()
        mock_fly_client.get_machine.return_value = {"state": "started"}
        assert controller.is_running is True

    def test_is_running_false_on_api_error(self, controller, mock_fly_client):
        controller.spawn()
        mock_fly_client.get_machine.side_effect = FlyAPIError(500, "fail")
        assert controller.is_running is False

    def test_history_starts_empty(self, controller):
        assert controller.history == []

    def test_history_returns_copy(self, controller):
        assert controller.history is not controller._history
