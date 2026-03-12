"""Git worktree manager for the Hunter's codebase.

Manages the hunter/live branch and its associated git worktree. The Overseer
uses this to modify the Hunter's source code (skills, tools, prompts) and
redeploy without affecting its own codebase.

Key invariants:
    - The main repo is NEVER modified by worktree operations.
    - All git commands use -C <worktree_path> to target the worktree.
    - The Overseer is the only writer; the Hunter only reads at startup.
    - setup() is idempotent — safe to call on every Overseer start.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from hunter.config import get_hunter_worktree_path, HUNTER_BRANCH

logger = logging.getLogger(__name__)


@dataclass
class CommitInfo:
    """Summary of a git commit."""
    hash: str
    short_hash: str
    message: str


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""


class WorktreeManager:
    """Manages the Hunter's git worktree and branch lifecycle.

    Usage:
        wt = WorktreeManager()
        wt.setup()                          # One-time: create branch + worktree
        wt.write_file("skills/security/idor.md", content)
        wt.commit("feat(hunter): add IDOR skill")
        wt.rollback(previous_hash)          # If the change was bad
    """

    def __init__(
        self,
        repo_root: Path = None,
        worktree_path: Path = None,
        branch: str = HUNTER_BRANCH,
    ):
        self.repo_root = repo_root or self._find_repo_root()
        self.worktree_path = worktree_path or get_hunter_worktree_path()
        self.branch = branch

    # ── Setup & teardown ────────────────────────────────────────────────

    def setup(self) -> None:
        """One-time setup: create hunter/live branch + worktree if they don't exist.

        Idempotent — safe to call on every Overseer start.
        """
        self._ensure_branch()
        self._ensure_worktree()
        logger.info(
            "Worktree ready: branch=%s path=%s head=%s",
            self.branch, self.worktree_path, self.get_head_commit()[:8],
        )

    def teardown(self) -> None:
        """Remove the worktree (but keep the branch for history).

        Use this for cleanup. The branch can be re-attached later via setup().
        """
        if not self._worktree_exists():
            return

        self._run_git("worktree", "remove", str(self.worktree_path), "--force",
                       cwd=self.repo_root)
        logger.info("Worktree removed: %s", self.worktree_path)

    # ── Status queries ──────────────────────────────────────────────────

    def is_setup(self) -> bool:
        """Check if both the branch and worktree exist and are valid."""
        return self._branch_exists() and self._worktree_exists()

    def is_clean(self) -> bool:
        """Check if the worktree has no uncommitted changes."""
        self._require_setup()
        result = self._run_git("status", "--porcelain")
        return result.stdout.strip() == ""

    def get_head_commit(self) -> str:
        """Get current HEAD commit hash (full 40-char) of the worktree."""
        self._require_setup()
        result = self._run_git("rev-parse", "HEAD")
        return result.stdout.strip()

    def get_recent_commits(self, n: int = 10) -> List[CommitInfo]:
        """Get last N commits on the hunter branch."""
        self._require_setup()
        result = self._run_git(
            "log", f"-{n}", "--format=%H%n%h%n%s",
        )
        lines = result.stdout.strip().split("\n")
        commits = []
        # Each commit is 3 lines: full hash, short hash, subject
        for i in range(0, len(lines) - 2, 3):
            commits.append(CommitInfo(
                hash=lines[i],
                short_hash=lines[i + 1],
                message=lines[i + 2],
            ))
        return commits

    # ── File operations ─────────────────────────────────────────────────

    def read_file(self, relative_path: str) -> str:
        """Read a file from the worktree.

        Args:
            relative_path: Path relative to worktree root (e.g., "skills/security/idor.md").

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        self._require_setup()
        full_path = self.worktree_path / relative_path
        if not full_path.exists():
            raise FileNotFoundError(f"Not found in worktree: {relative_path}")
        return full_path.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str) -> None:
        """Write a file to the worktree (does NOT auto-commit).

        Creates parent directories if needed.

        Args:
            relative_path: Path relative to worktree root.
            content: File content.
        """
        self._require_setup()
        full_path = self.worktree_path / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def edit_file(self, relative_path: str, old_str: str, new_str: str) -> bool:
        """Find-and-replace in a worktree file.

        Args:
            relative_path: Path relative to worktree root.
            old_str: Text to find (must appear exactly once).
            new_str: Replacement text.

        Returns:
            True if the replacement was made, False if old_str was not found.

        Raises:
            WorktreeError: If old_str appears more than once (ambiguous edit).
            FileNotFoundError: If the file doesn't exist.
        """
        self._require_setup()
        full_path = self.worktree_path / relative_path
        if not full_path.exists():
            raise FileNotFoundError(f"Not found in worktree: {relative_path}")

        content = full_path.read_text(encoding="utf-8")
        count = content.count(old_str)

        if count == 0:
            return False
        if count > 1:
            raise WorktreeError(
                f"Ambiguous edit: old_str appears {count} times in {relative_path}. "
                "Provide more context to make it unique."
            )

        content = content.replace(old_str, new_str, 1)
        full_path.write_text(content, encoding="utf-8")
        return True

    def delete_file(self, relative_path: str) -> bool:
        """Delete a file from the worktree (does NOT auto-commit).

        Returns True if the file existed and was deleted.
        """
        self._require_setup()
        full_path = self.worktree_path / relative_path
        if not full_path.exists():
            return False
        full_path.unlink()
        return True

    def list_files(self, relative_dir: str = ".", pattern: str = "*") -> List[str]:
        """List files in a worktree directory matching a glob pattern.

        Returns paths relative to the worktree root.
        """
        self._require_setup()
        search_dir = self.worktree_path / relative_dir
        if not search_dir.is_dir():
            return []
        return [
            str(p.relative_to(self.worktree_path))
            for p in search_dir.rglob(pattern)
            if p.is_file()
        ]

    # ── Git operations ──────────────────────────────────────────────────

    def commit(self, message: str, files: List[str] = None) -> str:
        """Stage files (or all changes) and commit.

        Args:
            message: Commit message.
            files: Specific files to stage (relative paths). If None, stages all changes.

        Returns:
            The new commit hash.

        Raises:
            WorktreeError: If there's nothing to commit.
        """
        self._require_setup()

        if files:
            for f in files:
                self._run_git("add", f)
        else:
            self._run_git("add", "-A")

        # Check if there's anything staged
        result = self._run_git("diff", "--cached", "--quiet", check=False)
        if result.returncode == 0:
            raise WorktreeError("Nothing to commit — no staged changes.")

        self._run_git("commit", "-m", message)
        return self.get_head_commit()

    def rollback(self, commit_hash: str) -> None:
        """Reset worktree HEAD to a specific commit (hard reset).

        WARNING: This discards all uncommitted changes and moves HEAD.

        Args:
            commit_hash: Full or short commit hash to reset to.
        """
        self._require_setup()
        self._run_git("reset", "--hard", commit_hash)
        logger.info("Worktree rolled back to %s", commit_hash[:8])

    def diff(self, staged: bool = False) -> str:
        """Show current uncommitted changes in the worktree.

        Args:
            staged: If True, show only staged changes. If False, show all.
        """
        self._require_setup()
        args = ["diff"]
        if staged:
            args.append("--staged")
        result = self._run_git(*args)
        return result.stdout

    def diff_since(self, commit_hash: str) -> str:
        """Show all changes between a commit and current HEAD."""
        self._require_setup()
        result = self._run_git("diff", f"{commit_hash}..HEAD")
        return result.stdout

    def push(self) -> None:
        """Push commits to remote. No-op for local worktrees.

        Remote backends (Phase B) will implement actual git push here.
        """
        logger.debug("Local worktree: push() is a no-op")

    # ── Internal helpers ────────────────────────────────────────────────

    def _ensure_branch(self) -> None:
        """Create the hunter branch from current HEAD if it doesn't exist."""
        if self._branch_exists():
            return

        # Create branch pointing at current HEAD of the main repo
        self._run_git("branch", self.branch, "HEAD", cwd=self.repo_root)
        logger.info("Created branch: %s", self.branch)

    def _ensure_worktree(self) -> None:
        """Create the worktree if it doesn't exist."""
        if self._worktree_exists():
            return

        self.worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_git(
            "worktree", "add", str(self.worktree_path), self.branch,
            cwd=self.repo_root,
        )
        logger.info("Created worktree: %s -> %s", self.worktree_path, self.branch)

    def _branch_exists(self) -> bool:
        """Check if the hunter branch exists in the repo."""
        result = self._run_git(
            "branch", "--list", self.branch,
            cwd=self.repo_root, check=False,
        )
        return self.branch in result.stdout

    def _worktree_exists(self) -> bool:
        """Check if the worktree directory exists and is a valid git worktree."""
        if not self.worktree_path.exists():
            return False
        # Verify it's actually a worktree (has .git file pointing to main repo)
        git_file = self.worktree_path / ".git"
        if not git_file.exists():
            return False
        # Quick sanity: can we run git status in it?
        result = self._run_git("status", "--porcelain", check=False)
        return result.returncode == 0

    def _require_setup(self) -> None:
        """Raise if the worktree isn't set up."""
        if not self._worktree_exists():
            raise WorktreeError(
                f"Worktree not set up at {self.worktree_path}. "
                "Call setup() first or run 'hermes hunter setup'."
            )

    def _run_git(
        self,
        *args: str,
        cwd: Path = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a git command targeting the worktree (or specified cwd).

        Args:
            *args: Git subcommand and arguments.
            cwd: Working directory. Defaults to self.worktree_path.
            check: If True, raise WorktreeError on non-zero exit.

        Returns:
            CompletedProcess with stdout/stderr.
        """
        cmd = ["git"] + list(args)
        target_cwd = cwd or self.worktree_path

        logger.debug("git %s (cwd=%s)", " ".join(args), target_cwd)

        result = subprocess.run(
            cmd,
            cwd=target_cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if check and result.returncode != 0:
            raise WorktreeError(
                f"git {' '.join(args)} failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )

        return result

    @staticmethod
    def _find_repo_root() -> Path:
        """Find the Hermes repo root from the current file's location.

        Falls back to git rev-parse if the file-based approach fails.
        """
        # First try: walk up from this file
        candidate = Path(__file__).resolve().parent.parent
        if (candidate / ".git").exists():
            return candidate

        # Fallback: ask git
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True, timeout=5,
            )
            return Path(result.stdout.strip())
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            raise WorktreeError(
                "Cannot find the Hermes repo root. "
                "Ensure you're running from within the repo."
            )

    def __repr__(self) -> str:
        setup = self.is_setup()
        head = self.get_head_commit()[:8] if setup else "N/A"
        return f"WorktreeManager(branch={self.branch}, path={self.worktree_path}, head={head}, setup={setup})"
