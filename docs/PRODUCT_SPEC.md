# Product specification

## Mission
Help developers turn bug reports and security issues into minimal, tested, reviewable code
changes, with security checks and honest verification reports.

## Users
Open-source maintainers, individual developers, small teams, and security-conscious contributors.

## Primary workflow
Local repository + issue description → analysis → plan → isolated patch → tests and security
checks → evidence report → human review.

## Requirements and v0.1 status

| Requirement | Status |
|---|---|
| Markdown issue input with acceptance-criteria extraction | Implemented |
| Read-only repository inspection (Git state, languages, tests, instruction files) | Implemented |
| Structured analysis and fix plan (`plan`), no edits or execution | Implemented |
| Minimal patch in an isolated clone of HEAD | Implemented |
| Patch policy validation (paths, symlinks, protected files, size, binary) | Implemented |
| Baseline, reproduction (fail-before) and candidate checks | Implemented |
| Bounded repair loop, budget owned by config | Implemented |
| Docker sandbox (no network, non-root, caps dropped, limits) | Implemented; tested in CI |
| Host execution (`--trust-repo`), explicitly unisolated | Implemented |
| Built-in secret scan; Gitleaks and Semgrep adapters | Implemented (scanners optional) |
| Test-weakening detection | Implemented (heuristic) |
| Versioned JSON + Markdown reports, redacted | Implemented |
| Provider abstraction; Anthropic adapter; deterministic fake provider | Implemented |
| Evaluation harness with fixture cases | Implemented (7 cases) |
| Dependency vulnerability scanning | Planned |
| Additional providers | Planned |
| GitHub issue → draft PR automation | Planned (v0.3) |

## Statuses
`VERIFIED`, `NEEDS_REVIEW`, `NO_FIX`, `FAILED` — see README for definitions. A test failure is
never hidden because a model believes its change is correct.

## Non-goals (v0.1)
Hosted dashboard, multi-agent swarm, automatic merge or deployment, support for every language,
penetration testing, or claims that an application is secure.
