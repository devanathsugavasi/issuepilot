# ADR 0002: Isolated workspace and fail-closed execution

**Status:** accepted · 2026-10-11

## Context
Candidate patches must never touch the user's branch or uncommitted work, and repository code
(tests, build scripts) is untrusted.

## Decision
- Work in a `git clone --no-hardlinks` of HEAD in a private temp dir, not a `git worktree`. A
  worktree writes metadata into the user's `.git` and its `.git` file points back at host paths,
  which would be exposed inside the sandbox mount.
- Execute repository commands only through a `Sandbox`. Docker is the default isolated backend.
  If it is unavailable, checks are `SKIPPED` and the run cannot be `VERIFIED`.
- Host execution exists only behind both `execution.sandbox: host` and the `--trust-repo` flag,
  and every report produced that way states it was unisolated.
- Images are never pulled implicitly (`--pull never`).

## Consequences
Uncommitted changes are not visible to runs (documented warning). Cloning costs time on very
large repositories. Users without Docker must opt in to host mode explicitly.
