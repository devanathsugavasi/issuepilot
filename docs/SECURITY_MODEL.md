# Security model

## Assumptions
The repository under analysis, the issue text, project instruction files, tool output and model
output may all be adversarial. The user, their IssuePilot installation and their explicit CLI
flags are trusted. A repository-provided `issuepilot.yaml` is treated as user configuration —
review it before running IssuePilot on an untrusted repository, or pass `--config`.

## Threats and controls

| Threat | Control (v0.1) | Verified by |
|---|---|---|
| Prompt injection in issue/repo files | Content wrapped as untrusted data; system prompt forbids following it; model has no tools; all output validated | `tests/security/test_injection_and_context.py`, `malicious-patch` eval |
| Malicious tests/build scripts | Run only via sandbox; fail closed when unavailable | `test_sandbox_unavailable_fails_closed`, Docker tests |
| Secret leakage to model | Sensitive files never selected; content redacted; only committed HEAD content is read | context security tests |
| Secret leakage to sandbox | Docker gets no host env; host mode passes only PATH/HOME/TMPDIR/LANG | `test_host_scrubs_environment`, Docker test |
| Secret leakage to reports | Redaction on every write; scanner secrets discarded | report/scanner unit tests |
| Destructive commands | No shell for the model; checks are user-configured commands | design |
| Corruption of user's work | Private clone; owned-path guard; integrity digest before/after | `test_dirty_worktree_is_preserved` |
| Network exfiltration | Docker `--network none` (only supported value) | Docker test |
| Malicious patch | Traversal, absolute, symlink-escape, `.git`, CI, config, credential, binary, size checks | `tests/unit/test_validate.py` |
| Runaway loops/cost | Config-owned repair budget; per-request timeout and retries; command timeouts with process-group kill | unit + integration tests |
| Tests weakened to pass | Removed assertions, added skips and deleted test files block `VERIFIED` | `weakened-test` eval |
| False security claims | Status derived from evidence; four-level finding status; "not proof of absence" in every report | `test_status.py` |

## Docker backend
Enforced flags: `--network none --user <non-root uid> --cap-drop ALL --security-opt
no-new-privileges --read-only --tmpfs /tmp --pids-limit --memory --memory-swap --cpus --pull never`,
a single bind mount of the workspace clone, no Docker socket, no home directory, no host
environment. Containers are killed on timeout.

**Docker is not a complete security boundary.** Containers share the host kernel; a kernel or
runtime vulnerability can allow escape. For highly adversarial repositories run IssuePilot inside
a disposable VM, or use a stronger runtime (gVisor/`runsc`, Kata) configured as Docker's runtime.

## Host backend (`--trust-repo`)
Not isolated. Repository code runs as your user with network access and can read anything you
can. Mitigations are limited to a scrubbed environment, a private temporary HOME, and process-group
termination. Every report produced this way lists these limitations.

## Finding levels
1. `scanner_reported` — a tool reported a pattern.
2. `candidate_vulnerability` — the issue reports a security problem not yet reproduced.
3. `reproduced` — a test failed on the unpatched code.
4. `verified_remediation` — reproduced, and the run is `VERIFIED`. This describes the tested
   scope only, not the security of the whole application.
