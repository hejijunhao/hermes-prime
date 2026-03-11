"""Tests for Overseer code modification tools (hunter/tools/code_tools.py).

Tests the five tools registered in the hunter-overseer toolset:
    - hunter_code_read:   read a file from the Hunter's worktree
    - hunter_code_edit:   find-and-replace + auto-commit
    - hunter_diff:        view uncommitted or historical changes
    - hunter_rollback:    reset worktree to a previous commit
    - hunter_redeploy:    kill + restart Hunter with new code

All tests use a mock HunterController — no real subprocesses or git repos.
"""

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the controller singleton before each test."""
    import hunter.tools.code_tools as mod
    original = mod._controller
    mod._controller = None
    yield
    mod._controller = original


@pytest.fixture
def mock_worktree():
    """A mock WorktreeManager."""
    wt = MagicMock()
    wt.read_file.return_value = "file content here"
    wt.edit_file.return_value = True
    wt.commit.return_value = "abc123def456"
    wt.diff.return_value = ""
    wt.diff_since.return_value = ""
    wt.get_head_commit.return_value = "abc123def456"
    return wt


@pytest.fixture
def mock_controller(mock_worktree):
    """Provide a mock HunterController and inject it as the singleton."""
    import hunter.tools.code_tools as mod

    controller = MagicMock()
    controller.worktree = mock_worktree
    controller.is_running = False
    controller.current = None
    controller.budget = MagicMock()
    mod._controller = controller
    return controller


@pytest.fixture
def mock_process():
    """A mock HunterProcess returned by controller.redeploy()."""
    proc = MagicMock()
    proc.session_id = "hunter-redeploy-001"
    proc.model = "qwen/qwen3.5-32b"
    proc._pid = 9999
    return proc


# ---------------------------------------------------------------------------
# _get_controller tests
# ---------------------------------------------------------------------------

class TestGetController:
    """Lazy singleton initialisation."""

    def test_creates_controller_on_first_call(self):
        """_get_controller lazily creates a HunterController with default managers."""
        import hunter.tools.code_tools as mod

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
        import hunter.tools.code_tools as mod

        result1 = mod._get_controller()
        result2 = mod._get_controller()
        assert result1 is result2
        assert result1 is mock_controller

    def test_set_controller_overrides_singleton(self):
        """_set_controller allows tests to inject a mock."""
        import hunter.tools.code_tools as mod

        fake = MagicMock()
        mod._set_controller(fake)
        assert mod._get_controller() is fake


# ---------------------------------------------------------------------------
# hunter_code_read tests
# ---------------------------------------------------------------------------

class TestHunterCodeRead:
    """hunter_code_read tool handler."""

    def test_read_normal_file(self, mock_controller, mock_worktree):
        """Reading an existing file returns content and size."""
        from hunter.tools.code_tools import _handle_hunter_code_read

        mock_worktree.read_file.return_value = "hello world"

        result = json.loads(_handle_hunter_code_read({"path": "tools/web_tools.py"}))

        assert result["path"] == "tools/web_tools.py"
        assert result["content"] == "hello world"
        assert result["size_bytes"] == len("hello world".encode("utf-8"))
        mock_worktree.read_file.assert_called_once_with("tools/web_tools.py")

    def test_read_missing_path(self, mock_controller):
        """Missing path parameter returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_read

        result = json.loads(_handle_hunter_code_read({}))
        assert "error" in result
        assert "path" in result["error"].lower()

    def test_read_empty_path(self, mock_controller):
        """Empty path parameter returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_read

        result = json.loads(_handle_hunter_code_read({"path": ""}))
        assert "error" in result

    def test_read_file_not_found(self, mock_controller, mock_worktree):
        """File that doesn't exist in worktree returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_read

        mock_worktree.read_file.side_effect = FileNotFoundError("Not found in worktree: nope.py")

        result = json.loads(_handle_hunter_code_read({"path": "nope.py"}))
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_read_worktree_error(self, mock_controller, mock_worktree):
        """WorktreeError (not set up) returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_read
        from hunter.worktree import WorktreeError

        mock_worktree.read_file.side_effect = WorktreeError("Worktree not set up")

        result = json.loads(_handle_hunter_code_read({"path": "test.py"}))
        assert "error" in result
        assert "not set up" in result["error"].lower()

    def test_read_utf8_size(self, mock_controller, mock_worktree):
        """Size reflects UTF-8 byte length, not character count."""
        from hunter.tools.code_tools import _handle_hunter_code_read

        # Multi-byte UTF-8 characters
        content = "Hello 🌍"
        mock_worktree.read_file.return_value = content

        result = json.loads(_handle_hunter_code_read({"path": "greet.py"}))
        assert result["size_bytes"] == len(content.encode("utf-8"))
        assert result["size_bytes"] > len(content)  # 🌍 is 4 bytes


# ---------------------------------------------------------------------------
# hunter_code_edit tests
# ---------------------------------------------------------------------------

class TestHunterCodeEdit:
    """hunter_code_edit tool handler."""

    def test_edit_normal(self, mock_controller, mock_worktree):
        """Normal find-and-replace edit with auto-commit."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        result = json.loads(_handle_hunter_code_edit({
            "path": "skills/recon.md",
            "old_string": "old text",
            "new_string": "new text",
        }))

        assert result["status"] == "edited_and_committed"
        assert result["path"] == "skills/recon.md"
        assert result["commit"] == "abc123def456"
        mock_worktree.edit_file.assert_called_once_with("skills/recon.md", "old text", "new text")
        mock_worktree.commit.assert_called_once_with("overseer: edit skills/recon.md", files=["skills/recon.md"])

    def test_edit_create_file(self, mock_controller, mock_worktree):
        """Empty old_string creates a new file via write_file."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        result = json.loads(_handle_hunter_code_edit({
            "path": "skills/new_skill.md",
            "old_string": "",
            "new_string": "# New Skill\nContent here.",
        }))

        assert result["status"] == "edited_and_committed"
        mock_worktree.write_file.assert_called_once_with("skills/new_skill.md", "# New Skill\nContent here.")
        mock_worktree.edit_file.assert_not_called()

    def test_edit_missing_path(self, mock_controller):
        """Missing path returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        result = json.loads(_handle_hunter_code_edit({
            "old_string": "x",
            "new_string": "y",
        }))
        assert "error" in result

    def test_edit_missing_old_string(self, mock_controller):
        """Missing old_string returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        result = json.loads(_handle_hunter_code_edit({
            "path": "test.py",
            "new_string": "y",
        }))
        assert "error" in result
        assert "old_string" in result["error"]

    def test_edit_missing_new_string(self, mock_controller):
        """Missing new_string returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        result = json.loads(_handle_hunter_code_edit({
            "path": "test.py",
            "old_string": "x",
        }))
        assert "error" in result
        assert "new_string" in result["error"]

    def test_edit_identical_strings(self, mock_controller):
        """old_string == new_string returns no-op error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        result = json.loads(_handle_hunter_code_edit({
            "path": "test.py",
            "old_string": "same",
            "new_string": "same",
        }))
        assert "error" in result
        assert "identical" in result["error"]

    def test_edit_old_string_not_found(self, mock_controller, mock_worktree):
        """old_string not in file returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        mock_worktree.edit_file.return_value = False  # Not found

        result = json.loads(_handle_hunter_code_edit({
            "path": "test.py",
            "old_string": "nonexistent",
            "new_string": "replacement",
        }))
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_edit_ambiguous(self, mock_controller, mock_worktree):
        """old_string appearing multiple times raises error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit
        from hunter.worktree import WorktreeError

        mock_worktree.edit_file.side_effect = WorktreeError(
            "Ambiguous edit: old_str appears 3 times"
        )

        result = json.loads(_handle_hunter_code_edit({
            "path": "test.py",
            "old_string": "common text",
            "new_string": "replacement",
        }))
        assert "error" in result
        assert "ambiguous" in result["error"].lower()

    def test_edit_file_not_found(self, mock_controller, mock_worktree):
        """File not in worktree returns error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        mock_worktree.edit_file.side_effect = FileNotFoundError("Not found")

        result = json.loads(_handle_hunter_code_edit({
            "path": "ghost.py",
            "old_string": "x",
            "new_string": "y",
        }))
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_edit_custom_commit_message(self, mock_controller, mock_worktree):
        """Custom commit message is passed through."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        _handle_hunter_code_edit({
            "path": "test.py",
            "old_string": "old",
            "new_string": "new",
            "commit_message": "feat(hunter): improve IDOR detection",
        })

        mock_worktree.commit.assert_called_once_with(
            "feat(hunter): improve IDOR detection",
            files=["test.py"],
        )

    def test_edit_default_commit_message(self, mock_controller, mock_worktree):
        """Default commit message includes the file path."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        _handle_hunter_code_edit({
            "path": "agent/prompt_builder.py",
            "old_string": "old",
            "new_string": "new",
        })

        mock_worktree.commit.assert_called_once_with(
            "overseer: edit agent/prompt_builder.py",
            files=["agent/prompt_builder.py"],
        )

    @patch("hunter.tools.code_tools._extract_overseer_event")
    def test_edit_elephantasm_logging(self, mock_extract, mock_controller, mock_worktree):
        """Successful edit logs to Elephantasm."""
        from hunter.tools.code_tools import _handle_hunter_code_edit

        _handle_hunter_code_edit({
            "path": "test.py",
            "old_string": "old",
            "new_string": "new",
        })

        mock_extract.assert_called_once()
        call_args = mock_extract.call_args
        assert "test.py" in call_args[0][0]
        assert call_args[1]["meta"]["type"] == "code_edit"

    def test_edit_commit_failure(self, mock_controller, mock_worktree):
        """Edit succeeds but commit fails — reports the error."""
        from hunter.tools.code_tools import _handle_hunter_code_edit
        from hunter.worktree import WorktreeError

        mock_worktree.commit.side_effect = WorktreeError("Nothing to commit")

        result = json.loads(_handle_hunter_code_edit({
            "path": "test.py",
            "old_string": "old",
            "new_string": "new",
        }))
        assert "error" in result
        assert "commit failed" in result["error"].lower()


# ---------------------------------------------------------------------------
# hunter_diff tests
# ---------------------------------------------------------------------------

class TestHunterDiff:
    """hunter_diff tool handler."""

    def test_diff_default_unstaged(self, mock_controller, mock_worktree):
        """No args returns unstaged diff."""
        from hunter.tools.code_tools import _handle_hunter_diff

        mock_worktree.diff.return_value = "diff --git a/test.py\n+new line"

        result = json.loads(_handle_hunter_diff({}))

        assert result["empty"] is False
        assert "+new line" in result["diff"]
        mock_worktree.diff.assert_called_once_with(staged=False)

    def test_diff_staged(self, mock_controller, mock_worktree):
        """staged=true shows only staged changes."""
        from hunter.tools.code_tools import _handle_hunter_diff

        mock_worktree.diff.return_value = "staged change"

        result = json.loads(_handle_hunter_diff({"staged": True}))

        assert result["empty"] is False
        mock_worktree.diff.assert_called_once_with(staged=True)

    def test_diff_since_commit(self, mock_controller, mock_worktree):
        """since_commit uses diff_since and takes priority over staged."""
        from hunter.tools.code_tools import _handle_hunter_diff

        mock_worktree.diff_since.return_value = "changes since abc"

        result = json.loads(_handle_hunter_diff({
            "since_commit": "abc123",
            "staged": True,  # Ignored when since_commit is set
        }))

        assert result["diff"] == "changes since abc"
        mock_worktree.diff_since.assert_called_once_with("abc123")
        mock_worktree.diff.assert_not_called()

    def test_diff_empty(self, mock_controller, mock_worktree):
        """Empty diff sets empty=true."""
        from hunter.tools.code_tools import _handle_hunter_diff

        mock_worktree.diff.return_value = ""

        result = json.loads(_handle_hunter_diff({}))

        assert result["empty"] is True
        assert result["diff"] == ""

    def test_diff_worktree_error(self, mock_controller, mock_worktree):
        """Worktree error returns JSON error."""
        from hunter.tools.code_tools import _handle_hunter_diff
        from hunter.worktree import WorktreeError

        mock_worktree.diff.side_effect = WorktreeError("Worktree not set up")

        result = json.loads(_handle_hunter_diff({}))
        assert "error" in result

    def test_diff_since_invalid_commit(self, mock_controller, mock_worktree):
        """Invalid commit hash returns JSON error."""
        from hunter.tools.code_tools import _handle_hunter_diff
        from hunter.worktree import WorktreeError

        mock_worktree.diff_since.side_effect = WorktreeError("git diff failed")

        result = json.loads(_handle_hunter_diff({"since_commit": "invalid"}))
        assert "error" in result


# ---------------------------------------------------------------------------
# hunter_rollback tests
# ---------------------------------------------------------------------------

class TestHunterRollback:
    """hunter_rollback tool handler."""

    def test_rollback_valid(self, mock_controller, mock_worktree):
        """Valid rollback resets worktree and returns new HEAD."""
        from hunter.tools.code_tools import _handle_hunter_rollback

        mock_worktree.get_head_commit.return_value = "abc123000"

        result = json.loads(_handle_hunter_rollback({"commit": "abc123"}))

        assert result["status"] == "rolled_back"
        assert result["to_commit"] == "abc123000"
        mock_worktree.rollback.assert_called_once_with("abc123")

    def test_rollback_missing_commit(self, mock_controller):
        """Missing commit hash returns error."""
        from hunter.tools.code_tools import _handle_hunter_rollback

        result = json.loads(_handle_hunter_rollback({}))
        assert "error" in result
        assert "commit" in result["error"].lower()

    def test_rollback_empty_commit(self, mock_controller):
        """Empty commit hash returns error."""
        from hunter.tools.code_tools import _handle_hunter_rollback

        result = json.loads(_handle_hunter_rollback({"commit": ""}))
        assert "error" in result

    def test_rollback_invalid_hash(self, mock_controller, mock_worktree):
        """Invalid hash causes WorktreeError."""
        from hunter.tools.code_tools import _handle_hunter_rollback
        from hunter.worktree import WorktreeError

        mock_worktree.rollback.side_effect = WorktreeError("git reset failed")

        result = json.loads(_handle_hunter_rollback({"commit": "deadbeef"}))
        assert "error" in result

    @patch("hunter.tools.code_tools._extract_overseer_event")
    def test_rollback_elephantasm_logging(self, mock_extract, mock_controller, mock_worktree):
        """Successful rollback logs to Elephantasm."""
        from hunter.tools.code_tools import _handle_hunter_rollback

        _handle_hunter_rollback({"commit": "abc123"})

        mock_extract.assert_called_once()
        call_args = mock_extract.call_args
        assert "abc123" in call_args[0][0]
        assert call_args[1]["meta"]["type"] == "rollback"

    def test_rollback_head_query_failure(self, mock_controller, mock_worktree):
        """If get_head_commit fails after rollback, falls back to input hash."""
        from hunter.tools.code_tools import _handle_hunter_rollback
        from hunter.worktree import WorktreeError

        mock_worktree.get_head_commit.side_effect = WorktreeError("failed")

        result = json.loads(_handle_hunter_rollback({"commit": "abc123"}))

        assert result["status"] == "rolled_back"
        assert result["to_commit"] == "abc123"


# ---------------------------------------------------------------------------
# hunter_redeploy tests
# ---------------------------------------------------------------------------

class TestHunterRedeploy:
    """hunter_redeploy tool handler."""

    def test_redeploy_defaults(self, mock_controller, mock_process):
        """Default redeploy resumes session."""
        from hunter.tools.code_tools import _handle_hunter_redeploy

        mock_controller.redeploy.return_value = mock_process

        result = json.loads(_handle_hunter_redeploy({}))

        assert result["status"] == "redeployed"
        assert result["resumed"] is True
        assert result["session_id"] == "hunter-redeploy-001"
        assert result["pid"] == 9999
        mock_controller.redeploy.assert_called_once_with(resume_session=True, model=None)

    def test_redeploy_no_resume(self, mock_controller, mock_process):
        """resume_session=false starts a fresh session."""
        from hunter.tools.code_tools import _handle_hunter_redeploy

        mock_controller.redeploy.return_value = mock_process

        result = json.loads(_handle_hunter_redeploy({"resume_session": False}))

        assert result["resumed"] is False
        mock_controller.redeploy.assert_called_once_with(resume_session=False, model=None)

    def test_redeploy_with_model(self, mock_controller, mock_process):
        """Model override is passed to controller."""
        from hunter.tools.code_tools import _handle_hunter_redeploy

        mock_controller.redeploy.return_value = mock_process

        result = json.loads(_handle_hunter_redeploy({"model": "qwen/qwen3.5-72b"}))

        mock_controller.redeploy.assert_called_once_with(resume_session=True, model="qwen/qwen3.5-72b")

    def test_redeploy_budget_error(self, mock_controller):
        """Budget exhaustion returns error."""
        from hunter.tools.code_tools import _handle_hunter_redeploy

        mock_controller.redeploy.side_effect = RuntimeError("Budget exhausted")

        result = json.loads(_handle_hunter_redeploy({}))
        assert "error" in result
        assert "budget" in result["error"].lower()

    @patch("hunter.tools.code_tools._extract_overseer_event")
    def test_redeploy_elephantasm_logging(self, mock_extract, mock_controller, mock_process):
        """Successful redeploy logs to Elephantasm."""
        from hunter.tools.code_tools import _handle_hunter_redeploy

        mock_controller.redeploy.return_value = mock_process

        _handle_hunter_redeploy({"model": "qwen/qwen3.5-7b"})

        mock_extract.assert_called_once()
        meta = mock_extract.call_args[1]["meta"]
        assert meta["type"] == "redeploy"


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """Verify tools are properly registered with the Hermes registry."""

    def test_all_tools_registered(self):
        """All five tools should be in the registry after import."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        names = registry.get_all_tool_names()
        for tool in ["hunter_code_read", "hunter_code_edit", "hunter_diff",
                      "hunter_rollback", "hunter_redeploy"]:
            assert tool in names

    def test_tools_in_correct_toolset(self):
        """All tools belong to the hunter-overseer toolset."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        for tool in ["hunter_code_read", "hunter_code_edit", "hunter_diff",
                      "hunter_rollback", "hunter_redeploy"]:
            assert registry.get_toolset_for_tool(tool) == "hunter-overseer"

    def test_code_edit_schema_requires_path_old_new(self):
        """hunter_code_edit requires path, old_string, and new_string."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        entry = registry._tools["hunter_code_edit"]
        required = entry.schema["parameters"]["required"]
        assert "path" in required
        assert "old_string" in required
        assert "new_string" in required

    def test_rollback_schema_requires_commit(self):
        """hunter_rollback requires commit."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        entry = registry._tools["hunter_rollback"]
        assert "commit" in entry.schema["parameters"]["required"]

    def test_schemas_valid_openai_format(self):
        """All schemas have required top-level fields for OpenAI tool format."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        for tool_name in ["hunter_code_read", "hunter_code_edit", "hunter_diff",
                          "hunter_rollback", "hunter_redeploy"]:
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

    def test_dispatch_code_read(self, mock_controller, mock_worktree):
        """registry.dispatch('hunter_code_read', ...) works."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        mock_worktree.read_file.return_value = "dispatched content"

        raw = registry.dispatch("hunter_code_read", {"path": "test.py"})
        result = json.loads(raw)

        assert result["content"] == "dispatched content"

    def test_dispatch_code_edit(self, mock_controller, mock_worktree):
        """registry.dispatch('hunter_code_edit', ...) works."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        raw = registry.dispatch("hunter_code_edit", {
            "path": "test.py",
            "old_string": "old",
            "new_string": "new",
        })
        result = json.loads(raw)

        assert result["status"] == "edited_and_committed"

    def test_dispatch_diff(self, mock_controller, mock_worktree):
        """registry.dispatch('hunter_diff', ...) works."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        raw = registry.dispatch("hunter_diff", {})
        result = json.loads(raw)

        assert "diff" in result

    def test_dispatch_rollback(self, mock_controller, mock_worktree):
        """registry.dispatch('hunter_rollback', ...) works."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        raw = registry.dispatch("hunter_rollback", {"commit": "abc123"})
        result = json.loads(raw)

        assert result["status"] == "rolled_back"

    def test_dispatch_catches_unexpected_exception(self, mock_controller, mock_worktree):
        """Unexpected exceptions in handlers are caught by registry.dispatch."""
        from tools.registry import registry

        import hunter.tools.code_tools  # noqa: F401

        mock_worktree.read_file.side_effect = ValueError("unexpected")

        raw = registry.dispatch("hunter_code_read", {"path": "test.py"})
        result = json.loads(raw)

        assert "error" in result
