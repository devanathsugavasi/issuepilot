"""Validation of model-proposed edits. Model output is untrusted: every rule here is enforced
before any byte is written, and a single violation rejects the whole proposal."""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

from issuepilot.config import PatchPolicy
from issuepilot.errors import PatchRejected
from issuepilot.schemas import FileEdit, PatchProposal

SENSITIVE_GLOBS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "*credentials*",
    "*.kdbx",
)


def is_sensitive(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return any(fnmatch.fnmatch(name, g) for g in SENSITIVE_GLOBS)


def check_path(path: str, root: Path, policy: PatchPolicy) -> list[str]:
    errors: list[str] = []
    if not path or "\0" in path or "\\" in path:
        return [f"{path!r}: invalid path"]
    pure = PurePosixPath(path)
    if pure.is_absolute():
        return [f"{path}: absolute paths are not allowed"]
    if any(part in ("..", "") for part in path.split("/")) or path.startswith("./"):
        return [f"{path}: path traversal or non-normalized path"]
    for pattern in policy.protected_paths:
        if fnmatch.fnmatch(path, pattern) or path == pattern.rstrip("/*"):
            errors.append(f"{path}: protected by policy ({pattern})")
    if is_sensitive(path):
        errors.append(f"{path}: credential-like files may not be edited")
    # Resolve through symlinks: the final location must stay inside the workspace.
    target = (root / pure).resolve()
    if not target.is_relative_to(root.resolve()):
        errors.append(f"{path}: resolves outside the workspace")
    return errors


def plan_edits(proposal: PatchProposal, root: Path, policy: PatchPolicy) -> dict[str, str]:
    """Validate all edits against the workspace and return {path: new_content}.

    Nothing is written. Raises PatchRejected listing every violation found.
    """
    errors: list[str] = []
    if not proposal.edits:
        raise PatchRejected(["proposal contains no edits"])
    files = {e.path for e in proposal.edits}
    if len(files) > policy.max_files:
        errors.append(f"proposal touches {len(files)} files (limit {policy.max_files})")
    contents: dict[str, str | None] = {}
    for edit in proposal.edits:
        path_errors = check_path(edit.path, root, policy)
        if path_errors:
            errors.extend(path_errors)
            continue
        errors.extend(_apply_one(edit, root, contents, policy))
    if errors:
        raise PatchRejected(errors)
    return {p: c for p, c in contents.items() if c is not None}


def _apply_one(edit: FileEdit, root: Path, contents: dict[str, str | None], policy: PatchPolicy) -> list[str]:
    target = root / edit.path
    if edit.path not in contents:
        if target.is_symlink():
            return [f"{edit.path}: editing symlinks is not allowed"]
        if target.exists():
            if not target.is_file():
                return [f"{edit.path}: not a regular file"]
            raw = target.read_bytes()
            if b"\0" in raw:
                return [f"{edit.path}: binary files cannot be edited"]
            contents[edit.path] = raw.decode("utf-8", errors="strict") if _utf8(raw) else None
            if contents[edit.path] is None:
                return [f"{edit.path}: file is not valid UTF-8"]
        else:
            contents[edit.path] = None
    current = contents[edit.path]
    if edit.search == "":
        if current is not None:
            return [f"{edit.path}: create requested but file already exists"]
        new = edit.replace
    else:
        if current is None:
            return [f"{edit.path}: file does not exist"]
        count = current.count(edit.search)
        if count != 1:
            return [f"{edit.path}: search text found {count} times (must be exactly 1)"]
        new = current.replace(edit.search, edit.replace, 1)
    if "\0" in new:
        return [f"{edit.path}: result would contain NUL bytes"]
    if len(new.encode()) > policy.max_file_bytes:
        return [f"{edit.path}: result exceeds {policy.max_file_bytes} bytes"]
    contents[edit.path] = new
    return []


def _utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


_ASSERTION = ("assert", "expect(", "should", "self.fail", "pytest.raises", "assertraises")
_SKIP = ("@pytest.mark.skip", "@unittest.skip", "pytest.skip(", ".skip(", "xit(", "xdescribe(", "@skip")


def flag_test_changes(patch: str, manifest: list) -> tuple[list[str], list[str]]:  # noqa: ANN001
    """Return (blocking, informational) notes about test changes in a unified diff.

    Blocking = changes that can manufacture a passing result: deleted test files, removed
    assertions, added skips. Informational = any other modification of an existing test file.
    """
    blocking: list[str] = []
    info: list[str] = []
    for c in manifest:
        if c.is_test and c.change == "deleted":
            blocking.append(f"{c.path}: test file deleted")
        elif c.is_test and c.change == "modified":
            info.append(f"{c.path}: existing test file modified")
    removed: dict[str, int] = {}
    skips: dict[str, int] = {}
    current = None
    test_files = {c.path for c in manifest if c.is_test}
    for line in patch.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            if line.startswith("+++ b/") or line.startswith("--- a/"):
                current = line[6:]
            continue
        if current is None or current not in test_files:
            continue
        body = line[1:].strip().lower()
        if line.startswith("-") and any(a in body for a in _ASSERTION):
            removed[current] = removed.get(current, 0) + 1
        elif line.startswith("+") and any(s in body for s in _SKIP):
            skips[current] = skips.get(current, 0) + 1
    blocking += [f"{p}: removes {n} assertion line(s)" for p, n in removed.items()]
    blocking += [f"{p}: adds {n} skip marker(s)" for p, n in skips.items()]
    return blocking, info
