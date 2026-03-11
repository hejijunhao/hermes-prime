"""Tests for the Hunter process controller (hunter/control.py).

Tests HunterProcess (single process lifecycle), HunterController (singleton),
and the runner entry point utilities (hunter/runner.py).

These tests use mock subprocesses — they don't require a real AIAgent or LLM.
"""

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo that WorktreeManager and HunterProcess can use."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


@pytest.fixture
def worktree(git_repo, tmp_path):
    """Set up a WorktreeManager with a temp worktree."""
    from hunter.worktree import WorktreeManager
    wt_path = tmp_path / "hunter-worktree"
    mgr = WorktreeManager(repo_root=git_repo, worktree_path=wt_path)
    mgr.setup()
    return mgr


@pytest.fixture
def budget(tmp_path):
    """BudgetManager with temp paths — generous budget by default."""
    from hunter.budget import BudgetManager
    config_path = tmp_path / "budget.yaml"
    ledger_path = tmp_path / "spend.jsonl"
    mgr = BudgetManager(config_path=config_path, ledger_path=ledger_path)
    mgr.create_default_config()
    return mgr


@pytest.fixture
def hunter_home(tmp_path, monkeypatch):
    """Redirect hunter home paths to tmp_path for IPC file tests."""
    home = tmp_path / "hunter_home"
    home.mkdir()
    (home / "injections").mkdir()
    (home / "logs").mkdir()
    monkeypatch.setattr("hunter.config.get_hunter_home", lambda: home)
    monkeypatch.setattr("hunter.config.get_injection_dir", lambda: home / "injections")
    monkeypatch.setattr("hunter.config.get_injection_path", lambda: home / "injections" / "current.md")
    monkeypatch.setattr("hunter.config.get_interrupt_flag_path", lambda: home / "interrupt.flag")
    monkeypatch.setattr("hunter.config.get_hunter_log_dir", lambda: home / "logs")
    monkeypatch.setattr("hunter.config.ensure_hunter_home", lambda: None)
    return home


# ---------------------------------------------------------------------------
# HunterStatus tests
# ---------------------------------------------------------------------------

class TestHunterStatus:
    """Test the HunterStatus dataclass."""

    def test_running_summary(self):
        from hunter.control import HunterStatus
        s = HunterStatus(
            running=True, pid=12345, session_id="hunter-abc",
            model="qwen/qwen3.5-32b", uptime_seconds=120.0,
            exit_code=None, last_output_line="Analysing target...", error=None,
        )
        assert "running" in s.summary()
        assert "12345" in s.summary()
        assert "hunter-abc" in s.summary()

    def test_stopped_summary(self):
        from hunter.control import HunterStatus
        s = HunterStatus(
            running=False, pid=12345, session_id="hunter-abc",
            model="qwen/qwen3.5-32b", uptime_seconds=0.0,
            exit_code=0, last_output_line="", error=None,
        )
        assert "stopped" in s.summary()

    def test_to_dict(self):
        from hunter.control import HunterStatus
        s = HunterStatus(
            running=True, pid=1, session_id="s", model="m",
            uptime_seconds=1.0, exit_code=None, last_output_line="", error=None,
        )
        d = s.to_dict()
        assert d["running"] is True
        assert d["session_id"] == "s"


# ---------------------------------------------------------------------------
# HunterProcess tests (using a real subprocess, but not AIAgent)
# ---------------------------------------------------------------------------

class TestHunterProcess:
    """Test HunterProcess with real subprocesses (simple scripts, not AIAgent)."""

    def _make_process(self, worktree, hunter_home, **kwargs):
        """Create a HunterProcess with patched command builder."""
        from hunter.control import HunterProcess
        return HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-session",
            **kwargs,
        )

    def test_spawn_and_poll(self, worktree, hunter_home):
        """Spawn a simple subprocess and verify it's running."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-spawn",
        )

        # Patch _build_command to run a simple script instead of hunter.runner
        script = textwrap.dedent("""\
            import time, sys
            print("Hunter starting...")
            sys.stdout.flush()
            time.sleep(30)
        """)
        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", script,
        ]):
            proc.spawn()

        assert proc.is_alive()
        status = proc.poll()
        assert status.running is True
        assert status.pid is not None
        assert status.session_id == "test-spawn"

        # Clean up
        proc.kill()
        assert not proc.is_alive()

    def test_kill_graceful(self, worktree, hunter_home):
        """Kill should terminate the process."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-kill",
        )

        # A process that sleeps
        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            proc.spawn()

        assert proc.is_alive()
        result = proc.kill(timeout=5.0)
        assert result is True
        assert not proc.is_alive()

    def test_kill_when_not_running(self, worktree, hunter_home):
        """Kill returns False if process isn't running."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-not-running",
        )
        assert proc.kill() is False

    def test_process_exit_detected(self, worktree, hunter_home):
        """Poll detects when the process has exited on its own."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-exit",
        )

        # A process that exits immediately
        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", "print('done')",
        ]):
            proc.spawn()

        # Wait for it to exit
        proc.wait(timeout=5.0)
        status = proc.poll()
        assert status.running is False
        assert status.exit_code == 0

    def test_nonzero_exit_code(self, worktree, hunter_home):
        """Non-zero exit code is captured as an error."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-error",
        )

        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", "import sys; sys.exit(42)",
        ]):
            proc.spawn()

        proc.wait(timeout=5.0)
        status = proc.poll()
        assert status.running is False
        assert status.exit_code == 42
        assert status.error is not None

    def test_output_capture(self, worktree, hunter_home):
        """Stdout is captured in the rolling buffer and log file."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-output",
        )

        script = textwrap.dedent("""\
            import sys
            for i in range(5):
                print(f"line {i}")
                sys.stdout.flush()
        """)
        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", script,
        ]):
            proc.spawn()

        proc.wait(timeout=5.0)
        # Give capture thread a moment to finish
        time.sleep(0.2)

        logs = proc.get_logs(tail=10)
        assert "line 0" in logs
        assert "line 4" in logs

        # Check log file exists
        log_path = proc.get_full_log_path()
        assert log_path is not None
        assert log_path.exists()
        assert "line 0" in log_path.read_text()

    def test_wait_timeout(self, worktree, hunter_home):
        """wait() raises TimeoutError if process doesn't exit in time."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-timeout",
        )

        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            proc.spawn()

        with pytest.raises(TimeoutError):
            proc.wait(timeout=0.5)

        # Clean up
        proc.kill()

    def test_spawn_twice_raises(self, worktree, hunter_home):
        """Spawning while already running raises RuntimeError."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-double-spawn",
        )

        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            proc.spawn()
            with pytest.raises(RuntimeError, match="already running"):
                proc.spawn()

        proc.kill()

    def test_uptime_increases(self, worktree, hunter_home):
        """uptime_seconds increases while the process is running."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-uptime",
        )

        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            proc.spawn()

        t1 = proc.uptime_seconds
        time.sleep(0.2)
        t2 = proc.uptime_seconds
        assert t2 > t1

        proc.kill()

    def test_build_command(self, worktree, hunter_home):
        """_build_command produces the correct argument list."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            model="qwen/qwen3.5-7b",
            session_id="cmd-test",
            max_iterations=50,
            resume_session=True,
        )
        cmd = proc._build_command("Find IDOR vulnerabilities.")
        assert "-m" in cmd
        assert "hunter.runner" in cmd
        assert "--session-id" in cmd
        assert "cmd-test" in cmd
        assert "--model" in cmd
        assert "qwen/qwen3.5-7b" in cmd
        assert "--max-iterations" in cmd
        assert "50" in cmd
        assert "--resume" in cmd
        assert "--instruction" in cmd
        assert "Find IDOR vulnerabilities." in cmd

    def test_build_env_adds_pythonpath(self, worktree, hunter_home):
        """_build_env puts the worktree on PYTHONPATH."""
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="env-test",
        )
        env = proc._build_env()
        assert str(worktree.worktree_path) in env.get("PYTHONPATH", "")


# ---------------------------------------------------------------------------
# HunterController tests
# ---------------------------------------------------------------------------

class TestHunterController:
    """Test the HunterController singleton."""

    def _make_controller(self, worktree, budget, hunter_home):
        from hunter.control import HunterController
        return HunterController(worktree=worktree, budget=budget)

    def test_spawn_creates_process(self, worktree, budget, hunter_home):
        """spawn() creates a running HunterProcess."""
        ctrl = self._make_controller(worktree, budget, hunter_home)

        # Patch the subprocess to run a simple script
        with patch("hunter.control.HunterProcess._build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            proc = ctrl.spawn(initial_instruction="Test")

        assert ctrl.is_running
        assert proc.session_id
        assert ctrl.current is proc

        ctrl.kill()

    def test_spawn_kills_existing(self, worktree, budget, hunter_home):
        """Spawning a new Hunter kills the existing one first."""
        ctrl = self._make_controller(worktree, budget, hunter_home)

        with patch("hunter.control.HunterProcess._build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            proc1 = ctrl.spawn()
            pid1 = proc1._pid
            proc2 = ctrl.spawn()

        assert ctrl.current is proc2
        assert not proc1.is_alive()
        assert ctrl.is_running

        # History should record the first process
        assert len(ctrl.history) >= 1

        ctrl.kill()

    def test_budget_hard_stop_prevents_spawn(self, worktree, budget, hunter_home):
        """Cannot spawn when budget is exhausted."""
        ctrl = self._make_controller(worktree, budget, hunter_home)

        # Exhaust the budget
        budget.record_spend(100.0, "test-model", 0, 0, "test")

        with pytest.raises(RuntimeError, match="Budget exhausted"):
            ctrl.spawn()

    def test_kill_returns_false_when_none(self, worktree, budget, hunter_home):
        """kill() returns False when no Hunter has been spawned."""
        ctrl = self._make_controller(worktree, budget, hunter_home)
        assert ctrl.kill() is False

    def test_get_status_no_hunter(self, worktree, budget, hunter_home):
        """get_status() returns sensible defaults when no Hunter exists."""
        ctrl = self._make_controller(worktree, budget, hunter_home)
        status = ctrl.get_status()
        assert status.running is False
        assert status.error is not None

    def test_get_logs_no_hunter(self, worktree, budget, hunter_home):
        """get_logs() returns empty string when no Hunter exists."""
        ctrl = self._make_controller(worktree, budget, hunter_home)
        assert ctrl.get_logs() == ""

    def test_redeploy(self, worktree, budget, hunter_home):
        """redeploy() kills the old Hunter and spawns a new one."""
        ctrl = self._make_controller(worktree, budget, hunter_home)

        with patch("hunter.control.HunterProcess._build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            proc1 = ctrl.spawn()
            session_id = proc1.session_id

            proc2 = ctrl.redeploy(resume_session=True)

        # New process should have the same session_id (for resume)
        assert proc2.session_id == session_id
        assert proc2.resume_session is True
        assert not proc1.is_alive()
        assert ctrl.is_running

        ctrl.kill()

    def test_redeploy_with_model_change(self, worktree, budget, hunter_home):
        """redeploy() can change the model."""
        ctrl = self._make_controller(worktree, budget, hunter_home)

        with patch("hunter.control.HunterProcess._build_command", return_value=[
            sys.executable, "-c", "import time; time.sleep(60)",
        ]):
            ctrl.spawn(model="qwen/qwen3.5-32b")
            proc2 = ctrl.redeploy(model="qwen/qwen3.5-7b")

        assert proc2.model == "qwen/qwen3.5-7b"
        ctrl.kill()

    def test_repr(self, worktree, budget, hunter_home):
        """__repr__ works for both running and stopped states."""
        ctrl = self._make_controller(worktree, budget, hunter_home)
        r = repr(ctrl)
        assert "stopped" in r
        assert "none" in r


# ---------------------------------------------------------------------------
# Interrupt flag file tests
# ---------------------------------------------------------------------------

class TestInterruptFlag:
    """Test the interrupt flag file mechanism."""

    def test_write_and_read_flag(self, hunter_home):
        """Interrupt flag can be written and read."""
        from hunter.config import get_interrupt_flag_path

        flag_path = get_interrupt_flag_path()
        assert not flag_path.exists()

        # Write flag
        flag_path.write_text("Shutting down for upgrade.", encoding="utf-8")
        assert flag_path.exists()

        # Read flag (as runner.py would)
        from hunter.runner import _check_interrupt_flag
        msg = _check_interrupt_flag()
        assert msg == "Shutting down for upgrade."

    def test_no_flag_returns_none(self, hunter_home):
        """No flag file returns None."""
        from hunter.runner import _check_interrupt_flag
        assert _check_interrupt_flag() is None


# ---------------------------------------------------------------------------
# Injection file tests
# ---------------------------------------------------------------------------

class TestInjectionFile:
    """Test the injection file mechanism."""

    def test_read_and_consume_injection(self, hunter_home):
        """Injection file is read and renamed to .consumed."""
        from hunter.config import get_injection_path
        from hunter.runner import _read_injection_file

        injection_path = get_injection_path()
        injection_path.write_text("Focus on the /api/users endpoint.", encoding="utf-8")

        content = _read_injection_file()
        assert content == "Focus on the /api/users endpoint."

        # File should be consumed (renamed)
        assert not injection_path.exists()
        consumed = injection_path.with_suffix(".md.consumed")
        assert consumed.exists()

    def test_no_injection_returns_none(self, hunter_home):
        """No injection file returns None."""
        from hunter.runner import _read_injection_file
        assert _read_injection_file() is None

    def test_empty_injection_returns_none(self, hunter_home):
        """Empty injection file is cleaned up and returns None."""
        from hunter.config import get_injection_path
        from hunter.runner import _read_injection_file

        injection_path = get_injection_path()
        injection_path.write_text("", encoding="utf-8")

        assert _read_injection_file() is None
        assert not injection_path.exists()


# ---------------------------------------------------------------------------
# Ephemeral prompt builder tests
# ---------------------------------------------------------------------------

class TestEphemeralPromptBuilder:
    """Test the ephemeral system prompt assembly."""

    def test_with_memory_and_injection(self):
        from hunter.runner import _build_hunter_ephemeral_prompt
        prompt = _build_hunter_ephemeral_prompt(
            memory_context="IDOR patterns: check /users/{id}",
            injection="Focus on auth bypass.",
        )
        assert "Elephantasm Memory Context" in prompt
        assert "IDOR patterns" in prompt
        assert "Overseer Instruction" in prompt
        assert "auth bypass" in prompt

    def test_with_only_injection(self):
        from hunter.runner import _build_hunter_ephemeral_prompt
        prompt = _build_hunter_ephemeral_prompt(injection="Check dependencies.")
        assert "Overseer Instruction" in prompt
        assert "Check dependencies." in prompt
        assert "Memory" not in prompt

    def test_with_nothing(self):
        from hunter.runner import _build_hunter_ephemeral_prompt
        assert _build_hunter_ephemeral_prompt() is None

    def test_with_only_memory(self):
        from hunter.runner import _build_hunter_ephemeral_prompt
        prompt = _build_hunter_ephemeral_prompt(memory_context="Previously found XSS.")
        assert "Memory" in prompt
        assert prompt is not None


# ---------------------------------------------------------------------------
# Step callback tests
# ---------------------------------------------------------------------------

class TestStepCallback:
    """Test the step callback that wires interrupt/injection checking."""

    def test_interrupt_calls_agent_interrupt(self, hunter_home):
        """Step callback calls agent.interrupt() when flag file exists."""
        from hunter.config import get_interrupt_flag_path
        from hunter.runner import _make_step_callback

        mock_agent = MagicMock()
        mock_agent.ephemeral_system_prompt = None
        callback = _make_step_callback(mock_agent)

        # No flag — should not interrupt
        callback(1, [])
        mock_agent.interrupt.assert_not_called()

        # Write flag
        flag = get_interrupt_flag_path()
        flag.write_text("Stop now.", encoding="utf-8")

        callback(2, ["terminal"])
        mock_agent.interrupt.assert_called_once_with("Stop now.")

    def test_injection_updates_ephemeral_prompt(self, hunter_home):
        """Step callback updates agent's ephemeral prompt when injection exists."""
        from hunter.config import get_injection_path
        from hunter.runner import _make_step_callback

        mock_agent = MagicMock()
        mock_agent.ephemeral_system_prompt = "existing prompt"
        callback = _make_step_callback(mock_agent)

        # Write injection
        injection_path = get_injection_path()
        injection_path.write_text("Check SSRF on /api/proxy.", encoding="utf-8")

        callback(1, [])

        # Ephemeral prompt should be updated
        assert "SSRF" in mock_agent.ephemeral_system_prompt
        assert "existing prompt" in mock_agent.ephemeral_system_prompt


# ---------------------------------------------------------------------------
# Integration: HunterProcess with interrupt flag
# ---------------------------------------------------------------------------

class TestInterruptIntegration:
    """End-to-end test: spawn a real subprocess, interrupt it via flag file."""

    def test_interrupt_via_flag_file(self, worktree, hunter_home):
        """A subprocess that polls for the interrupt flag exits when it's set."""
        from hunter.config import get_interrupt_flag_path
        from hunter.control import HunterProcess

        proc = HunterProcess(
            worktree_path=worktree.worktree_path,
            session_id="test-interrupt-e2e",
        )

        # Script that polls for the interrupt flag, simulating runner.py behaviour
        flag_path = get_interrupt_flag_path()
        script = textwrap.dedent(f"""\
            import time, sys
            from pathlib import Path
            flag = Path("{flag_path}")
            print("Waiting for interrupt...", flush=True)
            for i in range(100):
                if flag.exists():
                    print("Interrupt detected! Exiting.", flush=True)
                    sys.exit(0)
                time.sleep(0.1)
            print("Timed out waiting for interrupt.", flush=True)
            sys.exit(1)
        """)

        with patch.object(proc, "_build_command", return_value=[
            sys.executable, "-c", script,
        ]):
            proc.spawn()

        # Give it a moment to start
        time.sleep(0.3)
        assert proc.is_alive()

        # Write the interrupt flag
        flag_path.write_text("Test interrupt.", encoding="utf-8")

        # Wait for graceful exit
        exit_code = proc.wait(timeout=5.0)
        assert exit_code == 0

        logs = proc.get_logs()
        assert "Interrupt detected" in logs
