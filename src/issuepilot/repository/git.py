"""Read-only Git inspection of the user's repository.

Nothing in this module writes to the user's repository or working tree.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from issuepilot.errors import RepositoryError
from issuepilot.schemas import RepoInfo, RepoSnapshot

OWN_PATH_PREFIX = ".issuepilot/"
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".github/copilot-instructions.md")
MANIFESTS = (
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    "composer.json",
)
_LANG_BY_EXT = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
}


def git(repo: Path, *args: str, check: bool = True, timeout: int = 60) -> str:
    if shutil.which("git") is None:
        raise RepositoryError("git executable not found on PATH")
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RepositoryError(f"git {' '.join(args)} timed out") from e
    if check and proc.returncode != 0:
        raise RepositoryError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def repo_root(path: Path) -> Path:
    if not path.exists():
        raise RepositoryError(f"path does not exist: {path}")
    out = git(path, "rev-parse", "--show-toplevel", check=False).strip()
    if not out:
        raise RepositoryError(f"not a Git repository: {path}")
    return Path(out).resolve()


def snapshot(root: Path) -> RepoSnapshot:
    head = git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
    if not head:
        raise RepositoryError("repository has no commits; IssuePilot works from a committed HEAD")
    branch = git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip() or None
    status = [
        line
        for line in git(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
        if OWN_PATH_PREFIX not in line
    ]
    diff = git(root, "diff", "HEAD", "--binary", "--", ".", f":(exclude){OWN_PATH_PREFIX}")
    digest = hashlib.sha256(("\n".join(status) + "\0" + diff).encode()).hexdigest()
    return RepoSnapshot(root=str(root), head=head, branch=branch, dirty=bool(status), status_digest=digest)


def tracked_files(root: Path) -> list[str]:
    return [p for p in git(root, "ls-files", "-z").split("\0") if p]


def inspect_repo(path: Path) -> RepoInfo:
    root = repo_root(path)
    snap = snapshot(root)
    files = tracked_files(root)
    langs: dict[str, int] = {}
    for f in files:
        lang = _LANG_BY_EXT.get(Path(f).suffix)
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
    test_paths = sorted({f.split("/")[0] + "/" for f in files if is_test_path(f) and "/" in f})
    return RepoInfo(
        snapshot=snap,
        tracked_file_count=len(files),
        languages=sorted(langs, key=lambda k: -langs[k]),
        test_paths=test_paths[:20],
        instruction_files=[f for f in INSTRUCTION_FILES if f in files],
        manifests=[f for f in files if f in MANIFESTS],
    )


def is_test_path(path: str) -> bool:
    p = path.lower()
    name = p.rsplit("/", 1)[-1]
    return (
        p.startswith(("test/", "tests/", "spec/", "__tests__/"))
        or any(seg in p for seg in ("/test/", "/tests/", "/spec/", "/__tests__/"))
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.go", ".test.ts", ".test.js", ".spec.ts", ".spec.js"))
    )


def read_head_files(root: Path, commit: str, accept, max_bytes: int) -> dict[str, str]:  # noqa: ANN001
    """Return {path: text} for regular files at `commit` where accept(path) is true and size <=
    max_bytes. Reads Git objects only (never the working tree), so uncommitted or ignored files
    are never exposed."""
    listing = git(root, "ls-tree", "-r", "-l", "-z", commit)
    wanted: list[tuple[str, str]] = []
    for entry in listing.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        mode, kind, sha, size = meta.split()
        if kind != "blob" or mode not in ("100644", "100755") or size == "-" or int(size) > max_bytes:
            continue
        if accept(path):
            wanted.append((path, sha))
    if not wanted:
        return {}
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(f"{sha}\n" for _, sha in wanted).encode(),
        capture_output=True,
        timeout=120,
        check=True,
    )
    out, pos, result = proc.stdout, 0, {}
    for path, _ in wanted:
        header_end = out.index(b"\n", pos)
        size = int(out[pos:header_end].split()[2])
        body = out[header_end + 1 : header_end + 1 + size]
        pos = header_end + 1 + size + 1
        if b"\0" not in body:
            result[path] = body.decode("utf-8", errors="replace")
    return result
