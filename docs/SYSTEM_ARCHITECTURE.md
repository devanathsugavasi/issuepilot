# System architecture

A Python modular monolith. One process orchestrates separate modules; there is no server,
database or background worker.

```
cli.py ─► orchestrator.py (state machine, retry budget, status)
            ├─ issues/         Markdown parsing, acceptance criteria
            ├─ repository/     read-only Git inspection, HEAD blob reader
            ├─ agent/          bounded context selection (from HEAD, sensitive files excluded)
            ├─ llm/            ModelProvider protocol · anthropic_provider · fake
            ├─ patching/       edit validation · isolated workspace clone · diff/manifest
            ├─ sandbox/        DockerSandbox · HostSandbox (opt-in, unisolated)
            ├─ verification/   check execution · decide_status (pure function)
            ├─ security/       redaction · built-in secrets · gitleaks · semgrep · comparison
            ├─ reports/        JSON + Markdown writer/reader
            └─ evaluation/     case loader, fixture materialization, metrics
```

## State machine

`INITIALIZED → REPOSITORY_VALIDATED → ISSUE_ANALYZED → PLAN_READY → WORKSPACE_CREATED →
BASELINE_CAPTURED → PATCH_GENERATED → PATCH_VALIDATED → CHECKS_EXECUTED → REPORT_GENERATED`

Allowed loops: `PATCH_GENERATED → PATCH_GENERATED` (rejected patch → repair) and
`CHECKS_EXECUTED → PATCH_GENERATED` (failed checks → repair). `REPORT_GENERATED` is reachable from
any state so every run ends in a report. Any other transition raises `InvalidTransition`.

The repair budget (`model.max_repair_attempts`, default 2, max 5) is read once from configuration.

## Data flow and trust

1. Issue text and HEAD file contents are redacted and wrapped in `<untrusted_…>` tags.
2. The provider returns `IssueAnalysis`, `FixPlan` and `PatchProposal` objects validated by
   Pydantic (Anthropic: structured outputs via `messages.parse`).
3. `plan_edits` validates every edit against the workspace without writing; any violation rejects
   the whole proposal.
4. Only validated content is written to the workspace; only those paths are staged for the diff.
5. Checks run through a `Sandbox`; scanners read files on the host (they do not execute repo code).
6. `decide_status(Evidence)` derives the status from executed results only.

## Workspace

`git clone --no-hardlinks` of the user's repository into `$TMPDIR/issuepilot-ws-*/repo`, checked
out at the recorded HEAD, with the `origin` remote removed. Reset/cleanup refuse to operate on
any directory IssuePilot did not create. See ADR 0002.

## Reports

`<repo>/.issuepilot/runs/<run-id>/{report.json,report.md,changes.patch}`. `report.json` follows
`schemas.Report` with `schema_version: "1"`; breaking changes will bump the version.
