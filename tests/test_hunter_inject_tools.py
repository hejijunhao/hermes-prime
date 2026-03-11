"""Tests for Overseer runtime injection tools (hunter/tools/inject_tools.py).

Tests the three tools registered in the hunter-overseer toolset:
    - hunter_inject: push a runtime instruction into the Hunter
    - hunter_interrupt: signal the Hunter to stop gracefully
    - hunter_logs: retrieve recent Hunter output

All tests use a mock HunterController — no real subprocesses or git repos.
File I/O tests use the _isolate_hermes_home autouse fixture for safe paths.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the controller singleton before each test."""
    import hunter.tools.inject_tools as mod
    original = mod._controller
    mod._controller = None
    yield
    mod._controller = original


@pytest.fixture
def mock_controller():
    """Provide a mock HunterController and inject it as the singleton."""
    import hunter.tools.inject_tools as mod

    controller = MagicMock()
    controller.is_running = False
    controller.current = None
    mod._controller = controller
    return controller


@pytest.fixture
def mock_process():
    """A mock HunterProcess with controllable wait()."""
    proc = MagicMock()
    proc.session_id = "hunter-test1234"
    proc.model = "qwen/qwen3.5-32b"
    proc._pid = 42
    return proc


# ---------------------------------------------------------------------------
# _get_controller tests
# ---------------------------------------------------------------------------

class TestGetController:
    """Lazy singleton initialisation."""

    def test_creates_controller_on_first_call(self):
        """_get_controller lazily creates a HunterController with default managers."""
        import hunter.tools.inject_tools as mod

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
        import hunter.tools.inject_tools as mod

        result1 = mod._get_controller()
        result2 = mod._get_controller()
        assert result1 is result2
        assert result1 is mock_controller

    def test_set_controller_overrides_singleton(self):
        """_set_controller allows tests to inject a mock."""
        import hunter.tools.inject_tools as mod

        fake = MagicMock()
        mod._set_controller(fake)
        assert mod._get_controller() is fake


# ---------------------------------------------------------------------------
# hunter_inject tests
# ---------------------------------------------------------------------------

class TestHunterInject:
    """hunter_inject tool handler."""

    def test_inject_normal_priority(self):
        """Inject with default (normal) priority writes instruction as-is."""
        from hunter.tools.inject_tools import _handle_hunter_inject
        from hunter.config import get_injection_path

        result = json.loads(_handle_hunter_inject({
            "instruction": "Focus on SQL injection in /api/users"
        }))

        assert result["status"] == "injected"
        assert result["priority"] == "normal"
        assert result["instruction_length"] == len("Focus on SQL injection in /api/users")

        # Verify file content
        content = get_injection_path().read_text(encoding="utf-8")
        assert content == "Focus on SQL injection in /api/users"

    def test_inject_high_priority(self):
        """Inject with high priority adds prefix."""
        from hunter.tools.inject_tools import _handle_hunter_inject
        from hunter.config import get_injection_path

        result = json.loads(_handle_hunter_inject({
            "instruction": "Check IDOR on invoice API",
            "priority": "high",
        }))

        assert result["status"] == "injected"
        assert result["priority"] == "high"

        content = get_injection_path().read_text(encoding="utf-8")
        assert content == "HIGH PRIORITY: Check IDOR on invoice API"

    def test_inject_critical_priority(self):
        """Inject with critical priority adds drop-task prefix."""
        from hunter.tools.inject_tools import _handle_hunter_inject
        from hunter.config import get_injection_path

        result = json.loads(_handle_hunter_inject({
            "instruction": "Stop analysis, target is out of scope",
            "priority": "critical",
        }))

        assert result["status"] == "injected"
        assert result["priority"] == "critical"

        content = get_injection_path().read_text(encoding="utf-8")
        assert content.startswith("CRITICAL")
        assert "Stop analysis, target is out of scope" in content

    def test_inject_missing_instruction(self):
        """Inject without instruction returns error."""
        from hunter.tools.inject_tools import _handle_hunter_inject

        result = json.loads(_handle_hunter_inject({}))
        assert "error" in result
        assert "instruction" in result["error"].lower()

    def test_inject_empty_instruction(self):
        """Inject with empty instruction returns error."""
        from hunter.tools.inject_tools import _handle_hunter_inject

        result = json.loads(_handle_hunter_inject({"instruction": ""}))
        assert "error" in result

    def test_inject_invalid_priority(self):
        """Inject with invalid priority returns error."""
        from hunter.tools.inject_tools import _handle_hunter_inject

        result = json.loads(_handle_hunter_inject({
            "instruction": "test",
            "priority": "urgent",
        }))

        assert "error" in result
        assert "urgent" in result["error"]

    def test_inject_creates_parent_dirs(self):
        """Inject creates the injections directory if it doesn't exist."""
        from hunter.tools.inject_tools import _handle_hunter_inject
        from hunter.config import get_injection_path

        # The _isolate_hermes_home fixture gives us a clean dir
        injection_path = get_injection_path()
        assert not injection_path.parent.exists()

        result = json.loads(_handle_hunter_inject({
            "instruction": "test directive"
        }))

        assert result["status"] == "injected"
        assert injection_path.exists()

    def test_inject_overwrites_previous_injection(self):
        """A new injection replaces any unconsumed previous injection."""
        from hunter.tools.inject_tools import _handle_hunter_inject
        from hunter.config import get_injection_path

        _handle_hunter_inject({"instruction": "first instruction"})
        _handle_hunter_inject({"instruction": "second instruction"})

        content = get_injection_path().read_text(encoding="utf-8")
        assert content == "second instruction"

    @patch("hunter.tools.inject_tools._extract_overseer_event")
    def test_inject_calls_elephantasm(self, mock_extract):
        """Inject calls _extract_overseer_event for memory logging."""
        from hunter.tools.inject_tools import _handle_hunter_inject

        _handle_hunter_inject({
            "instruction": "test logging",
            "priority": "high",
        })

        mock_extract.assert_called_once()
        call_args = mock_extract.call_args
        assert "test logging" in call_args[0][0]
        assert call_args[1]["meta"]["priority"] == "high"

    def test_extract_overseer_event_catches_errors(self):
        """_extract_overseer_event never raises, even if Elephantasm is unavailable."""
        from hunter.tools.inject_tools import _extract_overseer_event

        # Should not raise — all exceptions are caught internally
        _extract_overseer_event("test event that won't reach Elephantasm")


# ---------------------------------------------------------------------------
# hunter_interrupt tests
# ---------------------------------------------------------------------------

class TestHunterInterrupt:
    """hunter_interrupt tool handler."""

    def test_interrupt_no_hunter_running(self, mock_controller):
        """Interrupt returns no_hunter_running when nothing is running."""
        from hunter.tools.inject_tools import _handle_hunter_interrupt

        mock_controller.is_running = False

        result = json.loads(_handle_hunter_interrupt({}))
        assert result["status"] == "no_hunter_running"

    def test_interrupt_graceful(self, mock_controller, mock_process):
        """Interrupt with successful graceful shutdown."""
        from hunter.tools.inject_tools import _handle_hunter_interrupt

        mock_controller.is_running = True
        mock_controller.current = mock_process
        mock_process.wait.return_value = 0  # Exits cleanly within timeout

        result = json.loads(_handle_hunter_interrupt({
            "message": "Upgrading Hunter skills."
        }))

        assert result["status"] == "interrupted_gracefully"
        assert result["message"] == "Upgrading Hunter skills."
        mock_process.wait.assert_called_once_with(timeout=30)

    def test_interrupt_force_kill(self, mock_controller, mock_process):
        """Interrupt falls back to force kill after timeout."""
        from hunter.tools.inject_tools import _handle_hunter_interrupt

        mock_controller.is_running = True
        mock_controller.current = mock_process
        mock_process.wait.side_effect = TimeoutError("timed out")

        result = json.loads(_handle_hunter_interrupt({}))

        assert result["status"] == "force_killed"
        mock_controller.kill.assert_called_once()

    def test_interrupt_default_message(self, mock_controller, mock_process):
        """Interrupt uses default message when none provided."""
        from hunter.tools.inject_tools import _handle_hunter_interrupt

        mock_controller.is_running = True
        mock_controller.current = mock_process
        mock_process.wait.return_value = 0

        result = json.loads(_handle_hunter_interrupt({}))

        assert result["message"] == "Overseer requested interrupt."

    def test_interrupt_writes_flag_file(self, mock_controller, mock_process):
        """Interrupt writes the interrupt flag file."""
        from hunter.tools.inject_tools import _handle_hunter_interrupt
        from hunter.config import get_interrupt_flag_path

        mock_controller.is_running = True
        mock_controller.current = mock_process
        mock_process.wait.return_value = 0

        _handle_hunter_interrupt({"message": "test interrupt"})

        flag_path = get_interrupt_flag_path()
        assert flag_path.exists()
        assert flag_path.read_text(encoding="utf-8") == "test interrupt"

    def test_interrupt_current_becomes_none(self, mock_controller):
        """Interrupt handles race where current becomes None after is_running check."""
        from hunter.tools.inject_tools import _handle_hunter_interrupt

        mock_controller.is_running = True
        mock_controller.current = None  # Race condition

        result = json.loads(_handle_hunter_interrupt({}))
        assert result["status"] == "no_hunter_running"


# ---------------------------------------------------------------------------
# hunter_logs tests
# ---------------------------------------------------------------------------

class TestHunterLogs:
    """hunter_logs tool handler."""

    def test_logs_default_tail(self, mock_controller):
        """Logs returns output with default tail of 100."""
        from hunter.tools.inject_tools import _handle_hunter_logs

        mock_controller.get_logs.return_value = "line1\nline2\nline3"
        mock_controller.is_running = True

        result = json.loads(_handle_hunter_logs({}))

        assert result["logs"] == "line1\nline2\nline3"
        assert result["lines"] == 100
        assert result["hunter_running"] is True
        mock_controller.get_logs.assert_called_once_with(tail=100)

    def test_logs_custom_tail(self, mock_controller):
        """Logs respects custom tail parameter."""
        from hunter.tools.inject_tools import _handle_hunter_logs

        mock_controller.get_logs.return_value = "recent line"

        result = json.loads(_handle_hunter_logs({"tail": 10}))

        assert result["lines"] == 10
        mock_controller.get_logs.assert_called_once_with(tail=10)

    def test_logs_empty(self, mock_controller):
        """Logs returns empty string when no output."""
        from hunter.tools.inject_tools import _handle_hunter_logs

        mock_controller.get_logs.return_value = ""
        mock_controller.is_running = False

        result = json.loads(_handle_hunter_logs({}))

        assert result["logs"] == ""
        assert result["hunter_running"] is False

    def test_logs_json_structure(self, mock_controller):
        """Logs response has all expected fields."""
        from hunter.tools.inject_tools import _handle_hunter_logs

        mock_controller.get_logs.return_value = "test output"
        mock_controller.is_running = True

        result = json.loads(_handle_hunter_logs({}))

        assert "logs" in result
        assert "lines" in result
        assert "hunter_running" in result


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """Verify tools are properly registered with the Hermes registry."""

    def test_tools_are_registered(self):
        """All three tools should be in the registry after import."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        names = registry.get_all_tool_names()
        assert "hunter_inject" in names
        assert "hunter_interrupt" in names
        assert "hunter_logs" in names

    def test_tools_in_correct_toolset(self):
        """All tools belong to the hunter-overseer toolset."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        assert registry.get_toolset_for_tool("hunter_inject") == "hunter-overseer"
        assert registry.get_toolset_for_tool("hunter_interrupt") == "hunter-overseer"
        assert registry.get_toolset_for_tool("hunter_logs") == "hunter-overseer"

    def test_inject_schema_has_required_instruction(self):
        """hunter_inject requires the 'instruction' parameter."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        entry = registry._tools["hunter_inject"]
        props = entry.schema["parameters"]["properties"]

        assert "instruction" in props
        assert "priority" in props
        assert "instruction" in entry.schema["parameters"]["required"]

    def test_interrupt_schema_has_optional_message(self):
        """hunter_interrupt has an optional 'message' parameter."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        entry = registry._tools["hunter_interrupt"]
        props = entry.schema["parameters"]["properties"]

        assert "message" in props
        assert entry.schema["parameters"]["required"] == []

    def test_logs_schema_has_optional_tail(self):
        """hunter_logs has an optional 'tail' parameter."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        entry = registry._tools["hunter_logs"]
        props = entry.schema["parameters"]["properties"]

        assert "tail" in props
        assert entry.schema["parameters"]["required"] == []

    def test_schemas_are_valid_openai_format(self):
        """Schemas have the required top-level fields for OpenAI tool format."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        for tool_name in ["hunter_inject", "hunter_interrupt", "hunter_logs"]:
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

    def test_dispatch_hunter_inject(self):
        """registry.dispatch('hunter_inject', ...) calls the handler."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        raw = registry.dispatch("hunter_inject", {
            "instruction": "Test via dispatch"
        })
        result = json.loads(raw)

        assert result["status"] == "injected"

    def test_dispatch_hunter_interrupt(self, mock_controller):
        """registry.dispatch('hunter_interrupt', ...) calls the handler."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        mock_controller.is_running = False

        raw = registry.dispatch("hunter_interrupt", {})
        result = json.loads(raw)

        assert result["status"] == "no_hunter_running"

    def test_dispatch_hunter_logs(self, mock_controller):
        """registry.dispatch('hunter_logs', ...) calls the handler."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        mock_controller.get_logs.return_value = "dispatch test"
        mock_controller.is_running = False

        raw = registry.dispatch("hunter_logs", {})
        result = json.loads(raw)

        assert result["logs"] == "dispatch test"

    def test_dispatch_catches_unexpected_exception(self, mock_controller):
        """Unexpected exceptions in handlers are caught by registry.dispatch."""
        from tools.registry import registry

        import hunter.tools.inject_tools  # noqa: F401

        mock_controller.get_logs.side_effect = ValueError("unexpected")

        raw = registry.dispatch("hunter_logs", {})
        result = json.loads(raw)

        assert "error" in result
        assert "ValueError" in result["error"]
