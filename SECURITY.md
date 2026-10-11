# Security Policy

IssuePilot executes untrusted repository code (in a sandbox) and handles untrusted model output,
so security reports are a priority.

## Reporting a vulnerability

Please **do not open a public issue.** Use GitHub's private reporting:
<https://github.com/devanathsugavasi/issuepilot/security/advisories/new>

Include affected version/commit, configuration (redact secrets), reproduction steps and impact.
We aim to acknowledge within 7 days. This is a volunteer project; there is no bug bounty.

## Especially in scope

- Escaping the workspace or sandbox (path traversal, symlinks, mounts, Docker flags)
- Repository code executing outside the sandbox, or when the sandbox is reported unavailable
- Credentials reaching the model, the sandbox, logs or reports
- Model output influencing the final status, the retry budget or policy
- Reports claiming checks ran or passed when they did not

## Out of scope

- Risks of `--trust-repo` host mode, which is documented as unisolated
- Kernel-level container escapes (Docker is documented as not a complete boundary)
- Findings that require a malicious IssuePilot configuration you wrote yourself

## Supported versions

Only the latest commit on `main` is supported during pre-alpha.
