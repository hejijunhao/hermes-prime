"""Tests for Overseer budget and model tools (hunter/tools/budget_tools.py).

Tests the two tools registered in the hunter-overseer toolset:
    - budget_status:    full budget snapshot + spend history
    - hunter_model_set: change the Hunter's model tier

All tests use a mock HunterController — no real subprocesses or git repos.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the controller singleton before each test."""
    import hunter.tools.budget_tools as mod
    original = mod._controller
    mod._controller = None
    yield
    mod._controller = original


@pytest.fixture
def mock_budget():
    """A mock BudgetManager with sensible defaults."""
    budget = MagicMock()
    budget.reload.return_value = False

    status = MagicMock()
    status.to_dict.return_value = {
        "allowed": True,
        "remaining_usd": 10.50,
        "percent_used": 30.0,
        "alert": False,
        "hard_stop": False,
        "mode": "daily",
        "spend_today": 4.50,
        "spend_total": 45.00,
        "daily_limit": 15.00,
        "total_limit": None,
        "daily_rate_limit": None,
    }
    status.summary.return_value = "$4.50 / $15.00 today (30% used, $10.50 remaining)"

    budget.check_budget.return_value = status
    budget.get_spend_history.return_value = []
    budget.get_daily_summary.return_value = {}
    return budget


@pytest.fixture
def mock_controller(mock_budget):
    """Provide a mock HunterController and inject it as the singleton."""
    import hunter.tools.budget_tools as mod

    controller = MagicMock()
    controller.budget = mock_budget
    controller.is_running = False
    controller.current = None
    mod._controller = controller
    return controller


@pytest.fixture
def mock_process():
    """A mock HunterProcess returned by controller.redeploy()."""
    proc = MagicMock()
    proc.session_id = "hunter-model-change-001"
    proc.model = "qwen/qwen3.5-7b"
    proc._pid = 8888
    return proc


# ---------------------------------------------------------------------------
# _get_controller tests
# ---------------------------------------------------------------------------

class TestGetController:
    """Lazy singleton initialisation."""

    def test_creates_controller_on_first_call(self):
        """_get_controller lazily creates a HunterController with default managers."""
        import hunter.tools.budget_tools as mod

        mock_wt = MagicMock()
        mock_bm = MagicMock()
        mock_hc = MagicMock()

        with patch("hunter.worktree.WorktreeManager", return_value=mock_wt) as PWT, \
             patch("hunter.budget.BudgetManager", return_value=mock_bm) as PBM, \
             patch("hunter.control.HunterController", return_value=mock_hc) as PHC:
            result = mod._get_controller()
            assert result is mock_hc
            PWT.assert_called_once()
            PBM.assert_called_once()
            PHC.assert_called_once_with(worktree=mock_wt, budget=mock_bm)

    def test_returns_same_instance_on_second_call(self, mock_controller):
        """Subsequent calls return the cached singleton."""
        import hunter.tools.budget_tools as mod

        result1 = mod._get_controller()
        result2 = mod._get_controller()
        assert result1 is result2
        assert result1 is mock_controller

    def test_set_controller_overrides_singleton(self):
        """_set_controller allows tests to inject a mock."""
        import hunter.tools.budget_tools as mod

        fake = MagicMock()
        mod._set_controller(fake)
        assert mod._get_controller() is fake


# ---------------------------------------------------------------------------
# budget_status tests
# ---------------------------------------------------------------------------

class TestBudgetStatus:
    """budget_status tool handler."""

    def test_normal_status(self, mock_controller, mock_budget):
        """Normal budget status returns all fields."""
        from hunter.tools.budget_tools import _handle_budget_status

        result = json.loads(_handle_budget_status({}))

        assert result["allowed"] is True
        assert result["remaining_usd"] == 10.50
        assert result["percent_used"] == 30.0
        assert result["mode"] == "daily"
        assert "summary" in result
        assert "recent_spend" in result
        assert "daily_breakdown" in result
        mock_budget.reload.assert_called_once()

    def test_budget_exhausted(self, mock_controller, mock_budget):
        """Exhausted budget shows hard_stop=True, allowed=False."""
        from hunter.tools.budget_tools import _handle_budget_status

        status = mock_budget.check_budget.return_value
        status.to_dict.return_value["allowed"] = False
        status.to_dict.return_value["hard_stop"] = True
        status.to_dict.return_value["percent_used"] = 100.0
        status.to_dict.return_value["remaining_usd"] = 0.0

        result = json.loads(_handle_budget_status({}))

        assert result["allowed"] is False
        assert result["hard_stop"] is True

    def test_alert_threshold(self, mock_controller, mock_budget):
        """Alert threshold shows alert=True."""
        from hunter.tools.budget_tools import _handle_budget_status

        status = mock_budget.check_budget.return_value
        status.to_dict.return_value["alert"] = True
        status.to_dict.return_value["percent_used"] = 85.0

        result = json.loads(_handle_budget_status({}))

        assert result["alert"] is True

    def test_recent_spend_included(self, mock_controller, mock_budget):
        """Recent spend entries are included in the response."""
        from hunter.tools.budget_tools import _handle_budget_status

        mock_budget.get_spend_history.return_value = [
            {"timestamp": "2026-03-11T10:00:00Z", "cost": 0.50, "model": "qwen/qwen3.5-32b"},
        ]

        result = json.loads(_handle_budget_status({}))

        assert len(result["recent_spend"]) == 1
        mock_budget.get_spend_history.assert_called_once_with(limit=5)

    def test_daily_breakdown_included(self, mock_controller, mock_budget):
        """Daily breakdown is included in the response."""
        from hunter.tools.budget_tools import _handle_budget_status

        mock_budget.get_daily_summary.return_value = {
            "2026-03-11": 4.50,
            "2026-03-10": 12.30,
        }

        result = json.loads(_handle_budget_status({}))

        assert result["daily_breakdown"]["2026-03-11"] == 4.50

    def test_no_ledger(self, mock_controller, mock_budget):
        """No ledger file returns empty spend data."""
        from hunter.tools.budget_tools import _handle_budget_status

        mock_budget.get_spend_history.return_value = []
        mock_budget.get_daily_summary.return_value = {}

        result = json.loads(_handle_budget_status({}))

        assert result["recent_spend"] == []
        assert result["daily_breakdown"] == {}


# ---------------------------------------------------------------------------
# hunter_model_set tests
# ---------------------------------------------------------------------------

class TestHunterModelSet:
    """hunter_model_set tool handler."""

    def test_set_model_basic(self, mock_controller):
        """Basic model set persists to file and returns status."""
        from hunter.tools.budget_tools import _handle_hunter_model_set, _get_model_override_path

        result = json.loads(_handle_hunter_model_set({"model": "qwen/qwen3.5-7b"}))

        assert result["status"] == "model_updated"
        assert result["new_model"] == "qwen/qwen3.5-7b"
        assert result["old_model"] is None  # No Hunter running
        assert result["redeployed"] is False
        assert "note" in result

        # Verify file was written
        path = _get_model_override_path()
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "qwen/qwen3.5-7b"

    def test_set_model_missing(self, mock_controller):
        """Missing model parameter returns error."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        result = json.loads(_handle_hunter_model_set({}))
        assert "error" in result

    def test_set_model_empty(self, mock_controller):
        """Empty model parameter returns error."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        result = json.loads(_handle_hunter_model_set({"model": ""}))
        assert "error" in result

    def test_set_model_captures_old_model(self, mock_controller, mock_process):
        """Old model is captured from current Hunter process."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        mock_process.model = "qwen/qwen3.5-32b"
        mock_controller.current = mock_process

        result = json.loads(_handle_hunter_model_set({"model": "qwen/qwen3.5-72b"}))

        assert result["old_model"] == "qwen/qwen3.5-32b"
        assert result["new_model"] == "qwen/qwen3.5-72b"

    def test_set_model_apply_immediately_running(self, mock_controller, mock_process):
        """apply_immediately triggers redeploy when Hunter is running."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        mock_controller.is_running = True
        mock_controller.redeploy.return_value = mock_process

        result = json.loads(_handle_hunter_model_set({
            "model": "qwen/qwen3.5-7b",
            "apply_immediately": True,
        }))

        assert result["redeployed"] is True
        assert result["session_id"] == "hunter-model-change-001"
        assert result["pid"] == 8888
        mock_controller.redeploy.assert_called_once_with(resume_session=True, model="qwen/qwen3.5-7b")

    def test_set_model_apply_immediately_not_running(self, mock_controller):
        """apply_immediately with no Hunter running just persists."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        mock_controller.is_running = False

        result = json.loads(_handle_hunter_model_set({
            "model": "qwen/qwen3.5-7b",
            "apply_immediately": True,
        }))

        assert result["redeployed"] is False
        assert "next spawn" in result["note"]
        mock_controller.redeploy.assert_not_called()

    def test_set_model_redeploy_budget_error(self, mock_controller):
        """Budget exhaustion on immediate redeploy reported in response."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        mock_controller.is_running = True
        mock_controller.redeploy.side_effect = RuntimeError("Budget exhausted")

        result = json.loads(_handle_hunter_model_set({
            "model": "qwen/qwen3.5-72b",
            "apply_immediately": True,
        }))

        assert result["redeployed"] is False
        assert "redeployment_error" in result
        assert "budget" in result["redeployment_error"].lower()

    def test_set_model_note_running_no_immediate(self, mock_controller):
        """Running Hunter without apply_immediately shows appropriate note."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        mock_controller.is_running = True

        result = json.loads(_handle_hunter_model_set({"model": "qwen/qwen3.5-7b"}))

        assert result["redeployed"] is False
        assert "next redeploy" in result["note"]

    @patch("hunter.tools.budget_tools._extract_overseer_event")
    def test_set_model_elephantasm_logging(self, mock_extract, mock_controller):
        """Model change logs to Elephantasm."""
        from hunter.tools.budget_tools import _handle_hunter_model_set

        _handle_hunter_model_set({"model": "qwen/qwen3.5-72b"})

        mock_extract.assert_called_once()
        meta = mock_extract.call_args[1]["meta"]
        assert meta["type"] == "model_change"
        assert meta["new_model"] == "qwen/qwen3.5-72b"


# ---------------------------------------------------------------------------
# _get_model_override_path tests
# ---------------------------------------------------------------------------

class TestModelOverridePath:
    """Model override file path helper."""

    def test_returns_path_under_hunter_home(self):
        """Path is under ~/.hermes/hunter/."""
        from hunter.tools.budget_tools import _get_model_override_path

        path = _get_model_override_path()
        assert path.name == "model_override.txt"
        assert "hunter" in str(path)

    def test_path_is_consistent(self):
        """Multiple calls return the same path."""
        from hunter.tools.budget_tools import _get_model_override_path

        assert _get_model_override_path() == _get_model_override_path()


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """Verify tools are properly registered with the Hermes registry."""

    def test_all_tools_registered(self):
        """Both tools should be in the registry after import."""
        from tools.registry import registry

        import hunter.tools.budget_tools  # noqa: F401

        names = registry.get_all_tool_names()
        assert "budget_status" in names
        assert "hunter_model_set" in names

    def test_tools_in_correct_toolset(self):
        """Both tools belong to the hunter-overseer toolset."""
        from tools.registry import registry

        import hunter.tools.budget_tools  # noqa: F401

        assert registry.get_toolset_for_tool("budget_status") == "hunter-overseer"
        assert registry.get_toolset_for_tool("hunter_model_set") == "hunter-overseer"

    def test_model_set_schema_requires_model(self):
        """hunter_model_set requires the 'model' parameter."""
        from tools.registry import registry

        import hunter.tools.budget_tools  # noqa: F401

        entry = registry._tools["hunter_model_set"]
        assert "model" in entry.schema["parameters"]["required"]

    def test_schemas_valid_openai_format(self):
        """Schemas have required top-level fields for OpenAI tool format."""
        from tools.registry import registry

        import hunter.tools.budget_tools  # noqa: F401

        for tool_name in ["budget_status", "hunter_model_set"]:
            entry = registry._tools[tool_name]
            assert "name" in entry.schema
            assert "description" in entry.schema
            assert "parameters" in entry.schema
            assert entry.schema["parameters"]["type"] == "object"


# ---------------------------------------------------------------------------
# Integration via registry.dispatch tests
# ---------------------------------------------------------------------------

class TestDispatchIntegration:
    """Verify tools work through the registry dispatch path."""

    def test_dispatch_budget_status(self, mock_controller, mock_budget):
        """registry.dispatch('budget_status', ...) works."""
        from tools.registry import registry

        import hunter.tools.budget_tools  # noqa: F401

        raw = registry.dispatch("budget_status", {})
        result = json.loads(raw)

        assert "allowed" in result
        assert "summary" in result

    def test_dispatch_model_set(self, mock_controller):
        """registry.dispatch('hunter_model_set', ...) works."""
        from tools.registry import registry

        import hunter.tools.budget_tools  # noqa: F401

        raw = registry.dispatch("hunter_model_set", {"model": "qwen/qwen3.5-7b"})
        result = json.loads(raw)

        assert result["status"] == "model_updated"

    def test_dispatch_catches_unexpected_exception(self, mock_controller, mock_budget):
        """Unexpected exceptions in handlers are caught by registry.dispatch."""
        from tools.registry import registry

        import hunter.tools.budget_tools  # noqa: F401

        mock_budget.reload.side_effect = ValueError("unexpected")

        raw = registry.dispatch("budget_status", {})
        result = json.loads(raw)

        assert "error" in result
