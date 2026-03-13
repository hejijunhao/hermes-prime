"""Protocol definitions for Hunter backend abstraction.

Defines ``WorktreeBackend`` and ``ControlBackend`` as ``typing.Protocol``
classes. These capture the interfaces that tool handlers and the Overseer
loop actually use, enabling Phase B to introduce remote backends (Fly.io)
without changing any consumer code.

Design rationale:
    - Protocols are **wide** (match real usage) not narrow (minimal ideal).
    - ``WorktreeManager`` and ``HunterController`` structurally satisfy these
      protocols without inheriting from them.
    - All type references are string-quoted or behind TYPE_CHECKING to avoid
      circular imports. These protocols are for type checking only.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hunter.budget import BudgetManager
    from hunter.control import HunterProcess, HunterStatus
    from hunter.worktree import CommitInfo


@runtime_checkable
class WorktreeBackend(Protocol):
    """Interface for managing the Hunter's source code.

    Local implementation: ``WorktreeManager`` (git worktree on disk).
    Future remote implementation: git operations over SSH / API to a Fly.io VM.
    """

    worktree_path: Path
    branch: str

    # -- Setup & teardown --
    def setup(self) -> None: ...
    def teardown(self) -> None: ...
    def is_setup(self) -> bool: ...
    def is_clean(self) -> bool: ...

    # -- File operations --
    def read_file(self, relative_path: str) -> str: ...
    def write_file(self, relative_path: str, content: str) -> None: ...
    def edit_file(self, relative_path: str, old_str: str, new_str: str) -> bool: ...
    def delete_file(self, relative_path: str) -> bool: ...
    def list_files(self, relative_dir: str = ".", pattern: str = "*") -> List[str]: ...

    # -- Git operations --
    def commit(self, message: str, files: List[str] = None) -> str: ...
    def rollback(self, commit_hash: str) -> None: ...
    def diff(self, staged: bool = False) -> str: ...
    def diff_since(self, commit_hash: str) -> str: ...
    def get_head_commit(self) -> str: ...
    def get_recent_commits(self, n: int = 10) -> List[CommitInfo]: ...
    def push(self) -> None: ...


@runtime_checkable
class ControlBackend(Protocol):
    """Interface for managing the Hunter agent process.

    Local implementation: ``HunterController`` (subprocess on this machine).
    Future remote implementation: Fly.io Machine API or similar.
    """

    worktree: WorktreeBackend
    budget: BudgetManager

    # -- Process lifecycle --
    def spawn(
        self,
        model: str = None,
        initial_instruction: str = None,
        resume_session: bool = False,
        session_id: str = None,
        detach: bool = False,
    ) -> HunterProcess: ...

    def kill(self) -> bool: ...

    def redeploy(
        self,
        resume_session: bool = True,
        model: str = None,
    ) -> HunterProcess: ...

    # -- Status & monitoring --
    def get_status(self) -> HunterStatus: ...
    def get_logs(self, tail: int = 100) -> str: ...

    # -- Injection & interrupt --
    def inject(self, instruction: str, priority: str = "normal") -> None: ...
    def interrupt(self) -> None: ...

    @property
    def is_running(self) -> bool: ...

    @property
    def current(self) -> Optional[HunterProcess]: ...

    @property
    def history(self) -> list: ...
