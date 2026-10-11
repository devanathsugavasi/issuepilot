"""Shared typed data models. Report models are versioned via REPORT_SCHEMA_VERSION."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA_VERSION = "1"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunState(StrEnum):
    INITIALIZED = "INITIALIZED"
    REPOSITORY_VALIDATED = "REPOSITORY_VALIDATED"
    ISSUE_ANALYZED = "ISSUE_ANALYZED"
    PLAN_READY = "PLAN_READY"
    WORKSPACE_CREATED = "WORKSPACE_CREATED"
    BASELINE_CAPTURED = "BASELINE_CAPTURED"
    PATCH_GENERATED = "PATCH_GENERATED"
    PATCH_VALIDATED = "PATCH_VALIDATED"
    CHECKS_EXECUTED = "CHECKS_EXECUTED"
    REPORT_GENERATED = "REPORT_GENERATED"


class RunStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NO_FIX = "NO_FIX"
    FAILED = "FAILED"


# --- inputs -----------------------------------------------------------------


class Issue(_Model):
    title: str
    body: str
    source: str
    acceptance_criteria: list[str] = Field(default_factory=list)


class RepoSnapshot(_Model):
    root: str
    head: str
    branch: str | None
    dirty: bool
    status_digest: str
    """sha256 of `git status --porcelain` + `git diff HEAD`, excluding IssuePilot's own paths."""


class RepoInfo(_Model):
    snapshot: RepoSnapshot
    tracked_file_count: int
    languages: list[str]
    test_paths: list[str]
    instruction_files: list[str]
    manifests: list[str]


# --- model I/O (these are what the provider must return; all are validated) ---


class IssueAnalysis(_Model):
    summary: str
    expected_behavior: str | None = None
    actual_behavior: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    security_relevant: bool = False
    sufficient_information: bool
    missing_information: list[str] = Field(default_factory=list)


class FixPlan(_Model):
    proposed_change: str
    files_to_change: list[str] = Field(default_factory=list)
    test_plan: list[str] = Field(default_factory=list)
    security_considerations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class FileEdit(_Model):
    path: str = Field(description="Repository-relative POSIX path.")
    search: str = Field(
        description="Exact text that must occur exactly once in the file. Empty string = create a new file."
    )
    replace: str


class PatchProposal(_Model):
    summary: str
    edits: list[FileEdit]


class PlanResult(_Model):
    """Output of the read-only `plan` command."""

    issue: Issue
    repo: RepoInfo
    analysis: IssueAnalysis
    plan: FixPlan | None
    context_files: list[str]


# --- verification ------------------------------------------------------------


class CheckOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class CheckResult(_Model):
    check_id: str
    kind: str
    command: str
    phase: str  # baseline | reproduction | candidate
    environment: str
    ran: bool
    outcome: CheckOutcome
    exit_code: int | None = None
    started_at: str | None = None
    duration_s: float | None = None
    output: str = ""
    skip_reason: str | None = None


class FindingStatus(StrEnum):
    SCANNER_REPORTED = "scanner_reported"
    CANDIDATE_VULNERABILITY = "candidate_vulnerability"
    REPRODUCED = "reproduced"
    VERIFIED_REMEDIATION = "verified_remediation"


class Finding(_Model):
    id: str
    source: str
    rule_id: str
    severity: str  # info | low | medium | high | critical | unknown
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    evidence: str
    confidence: str  # low | medium | high
    status: FindingStatus
    remediation: str | None = None
    introduced_by_patch: bool | None = None
    resolved_in_candidate: bool | None = None
    related_checks: list[str] = Field(default_factory=list)


class ScannerRun(_Model):
    scanner: str
    phase: str
    ran: bool
    detail: str


class ChangedFile(_Model):
    path: str
    change: str  # added | modified | deleted
    is_test: bool


class Attempt(_Model):
    number: int
    kind: str  # initial | repair
    summary: str
    validation_errors: list[str] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)


class Usage(_Model):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderInfo(_Model):
    name: str
    model: str | None
    usage: Usage


class Report(_Model):
    schema_version: str = REPORT_SCHEMA_VERSION
    tool_version: str
    run_id: str
    created_at: str
    status: RunStatus
    status_reasons: list[str]
    state_history: list[RunState]
    issue: Issue
    repo_start: RepoSnapshot | None = None
    original_repo_intact: bool | None = None
    config_digest: str
    sandbox: str
    analysis: IssueAnalysis | None = None
    plan: FixPlan | None = None
    attempts: list[Attempt] = Field(default_factory=list)
    baseline_checks: list[CheckResult] = Field(default_factory=list)
    reproduction_checks: list[CheckResult] = Field(default_factory=list)
    final_checks: list[CheckResult] = Field(default_factory=list)
    scanner_runs: list[ScannerRun] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    patch_file: str | None = None
    test_changes: list[str] = Field(default_factory=list)
    provider: ProviderInfo
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    next_action: str
