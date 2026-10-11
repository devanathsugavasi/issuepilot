"""Isolated workspace: a private `git clone` of the user's HEAD in a temp directory.

A clone (rather than `git worktree`) is used so that IssuePilot never writes into the
user's `.git` directory and the sandbox mount contains no pointers back to host paths.
Uncommitted changes in the user's tree are intentionally NOT copied.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from issuepilot.errors import RepositoryError
from issuepilot.repository.git import git, is_test_path
from issuepilot.schemas import ChangedFile

WORKSPACE_PREFIX = "issuepilot-ws-"


class Workspace:
    def __init__(self, source: Path, commit: str):
        self._tmp = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX)).resolve()
        self.path = self._tmp / "repo"
        git(self._tmp, "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(source), str(self.path), timeout=600)
        git(self.path, "checkout", "--quiet", "--detach", commit)
        git(self.path, "config", "user.email", "issuepilot@localhost")
        git(self.path, "config", "user.name", "IssuePilot")
        # Drop the remote so nothing inside the sandbox can point back at the host repo.
        git(self.path, "remote", "remove", "origin", check=False)
        self.commit = commit

    def _assert_owned(self) -> None:
        if not (self._tmp.name.startswith(WORKSPACE_PREFIX) and self.path.parent == self._tmp):
            raise RepositoryError("refusing to operate on a directory IssuePilot did not create")

    def reset(self) -> None:
        """Return the workspace to the starting commit (owned clone only)."""
        self._assert_owned()
        git(self.path, "reset", "--quiet", "--hard", self.commit)
        git(self.path, "clean", "-fdxq")

    def write(self, files: dict[str, str]) -> None:
        self._assert_owned()
        for rel, content in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def diff(self, paths: list[str]) -> tuple[str, list[ChangedFile]]:
        """Stage exactly `paths` (never anything else) and return (patch, manifest)."""
        self._assert_owned()
        if not paths:
            return "", []
        git(self.path, "add", "--", *paths)
        patch = git(self.path, "diff", "--cached", "--binary", self.commit, "--", *paths)
        status = git(self.path, "diff", "--cached", "--name-status", self.commit, "--", *paths)
        kinds = {"A": "added", "M": "modified", "D": "deleted"}
        manifest = []
        for line in status.splitlines():
            code, _, path = line.partition("\t")
            manifest.append(ChangedFile(path=path, change=kinds.get(code[:1], code), is_test=is_test_path(path)))
        return patch, manifest

    def cleanup(self) -> None:
        self._assert_owned()
        shutil.rmtree(self._tmp, ignore_errors=True)
