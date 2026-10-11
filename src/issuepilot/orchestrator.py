"""Issue-solving workflow. The orchestrator — not the model — owns control flow, the retry
budget, sandbox use and the final status."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from issuepilot import __version__
from issuepilot.agent import build_context
from issuepilot.config import Config
from issuepilot.errors import InvalidTransition, IssuePilotError, PatchRejected, ProviderError
from issuepilot.llm import ModelProvider
from issuepilot.patching.validate import flag_test_changes, plan_edits
from issuepilot.patching.workspace import Workspace
from issuepilot.reports import run_dir, write_report
from issuepilot.repository.git import git, inspect_repo, is_test_path, repo_root, snapshot
from issuepilot.sandbox import Sandbox
from issuepilot.schemas import (
    Attempt,
    ChangedFile,
    CheckOutcome,
    CheckResult,
    Finding,
    FindingStatus,
    FixPlan,
    Issue,
    IssueAnalysis,
    PatchProposal,
    ProviderInfo,
    Report,
    RepoSnapshot,
    RunState,
    RunStatus,
    ScannerRun,
)
from issuepilot.security.redact import redact, truncate
from issuepilot.security.scanners import compare, missing_required, scan_tree
from issuepilot.verification import Evidence, all_passed, decide_status, failure_summary, run_checks

S = RunState
TRANSITIONS: dict[RunState, set[RunState]] = {
    S.INITIALIZED: {S.REPOSITORY_VALIDATED},
    S.REPOSITORY_VALIDATED: {S.ISSUE_ANALYZED},
    S.ISSUE_ANALYZED: {S.PLAN_READY},
    S.PLAN_READY: {S.WORKSPACE_CREATED},
    S.WORKSPACE_CREATED: {S.BASELINE_CAPTURED},
    S.BASELINE_CAPTURED: {S.PATCH_GENERATED},
    S.PATCH_GENERATED: {S.PATCH_VALIDATED, S.PATCH_GENERATED},  # invalid patch -> repair
    S.PATCH_VALIDATED: {S.CHECKS_EXECUTED},
    S.CHECKS_EXECUTED: {S.PATCH_GENERATED},  # failed checks -> repair
    S.REPORT_GENERATED: set(),
}

NEXT_ACTION = {
    RunStatus.VERIFIED: "Review the patch and apply it yourself if acceptable (`git apply <run>/changes.patch`). "
    "IssuePilot never commits, pushes or merges.",
    RunStatus.NEEDS_REVIEW: "The fix is NOT verified. Read the reasons above and inspect the patch before deciding.",
    RunStatus.NO_FIX: "Clarify the issue (see missing information) or narrow its scope, then re-run.",
    RunStatus.FAILED: "Resolve the failure reason above and re-run.",
}


class StateMachine:
    def __init__(self) -> None:
        self.state = S.INITIALIZED
        self.history = [S.INITIALIZED]

    def to(self, new: RunState) -> None:
        # REPORT_GENERATED is reachable from any state so that every run ends in a report.
        allowed = TRANSITIONS[self.state] | ({S.REPORT_GENERATED} if self.state != S.REPORT_GENERATED else set())
        if new not in allowed:
            raise InvalidTransition(f"{self.state} -> {new} is not allowed")
        self.state = new
        self.history.append(new)


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


@dataclass
class _Candidate:
    attempt: Attempt
    files: dict[str, str]
    patch: str
    manifest: list[ChangedFile]
    reproduction: list[CheckResult]
    checks: list[CheckResult]


class Orchestrator:
    def __init__(self, repo: Path, issue: Issue, cfg: Config, provider: ModelProvider, sandbox: Sandbox):
        self.root = repo_root(repo)
        self.issue = issue
        self.cfg = cfg
        self.provider = provider
        self.sandbox = sandbox
        self.sm = StateMachine()
        self.run_id = new_run_id()
        self.dir = run_dir(self.root, cfg.report_dir, self.run_id)
        self.warnings: list[str] = []
        self.limitations = [
            "Model output is untrusted; a human must review the patch before applying it.",
            "Scanners and tests are finite: passing them does not prove the code is free of vulnerabilities.",
        ]

    # -- public -------------------------------------------------------------------

    def run(self) -> Report:
        start: RepoSnapshot | None = None
        ws: Workspace | None = None
        fields: dict = {}
        status, reasons, failure = RunStatus.FAILED, ["run did not complete"], None
        patch = ""
        try:
            info = inspect_repo(self.root)
            start = info.snapshot
            self.sm.to(S.REPOSITORY_VALIDATED)
            if start.dirty:
                self.warnings.append(
                    "The working tree has uncommitted changes; they were NOT included. "
                    f"IssuePilot works from HEAD {start.head[:12]}."
                )
            ctx = build_context(self.issue, info, self.cfg.model)
            analysis = self.provider.analyze_issue(ctx)
            fields["analysis"] = analysis
            self.sm.to(S.ISSUE_ANALYZED)
            if not analysis.sufficient_information:
                status = RunStatus.NO_FIX
                reasons = [
                    "the issue does not contain enough information to define correct behavior",
                    *[f"missing: {m}" for m in analysis.missing_information],
                ]
                return self._finish(start, status, reasons, None, fields, patch)
            plan = self.provider.plan_fix(ctx, analysis)
            fields["plan"] = plan
            self.sm.to(S.PLAN_READY)

            ws = Workspace(self.root, start.head)
            self.sm.to(S.WORKSPACE_CREATED)
            sb_ok, sb_reason = self.sandbox.availability()
            if not sb_ok:
                self.warnings.append(f"Sandbox unavailable ({sb_reason}); repository code was not executed.")
            else:
                self.limitations.extend(self.sandbox.limitations())
            baseline = run_checks(
                self.cfg.verification.checks, self.sandbox, sb_ok, sb_reason, ws.path, "baseline", self.cfg
            )
            base_runs, base_findings = self._scan(ws, "baseline")
            fields["baseline_checks"] = baseline
            self.sm.to(S.BASELINE_CAPTURED)

            attempts, best = self._patch_loop(ws, ctx, analysis, plan, baseline, sb_ok, sb_reason)
            fields["attempts"] = attempts
            if best is None:
                status, reasons = decide_status(Evidence(False, sb_ok, baseline, [], []))
                return self._finish(start, status, reasons, None, fields, patch)

            ws.reset()
            ws.write(best.files)
            patch, manifest = ws.diff(list(best.files))
            cand_runs, cand_findings = self._scan(ws, "candidate")
            findings = compare(base_findings, cand_findings)
            weakened, test_notes = flag_test_changes(patch, manifest)
            ev = Evidence(
                patch_valid=True,
                sandbox_ok=sb_ok,
                baseline=baseline,
                reproduction=best.reproduction,
                candidate=best.checks,
                new_findings=[f for f in findings if f.introduced_by_patch],
                weakened_tests=weakened,
                scanners_missing=missing_required(base_runs + cand_runs, self.cfg.security),
            )
            status, reasons = decide_status(ev)
            issue_finding = self._issue_finding(analysis, ev, status)
            fields.update(
                reproduction_checks=best.reproduction,
                final_checks=best.checks,
                scanner_runs=base_runs + cand_runs,
                findings=([issue_finding] if issue_finding else []) + findings,
                changed_files=manifest,
                patch_file=str(self.dir / "changes.patch"),
                test_changes=weakened + test_notes,
            )
        except (IssuePilotError, InvalidTransition) as e:
            failure = redact(str(e))
            status, reasons = RunStatus.FAILED, [f"{type(e).__name__}: {truncate(failure, 300)}"]
        except Exception as e:  # noqa: BLE001 - every run must end in a report
            failure = f"unexpected {type(e).__name__}: {redact(str(e))}"
            status, reasons = RunStatus.FAILED, [failure[:300]]
        finally:
            if ws is not None:
                ws.cleanup()
        return self._finish(start, status, reasons, failure, fields, patch)

    # -- internals ----------------------------------------------------------------

    def _scan(self, ws: Workspace, phase: str) -> tuple[list[ScannerRun], list[Finding]]:
        files = [f for f in git(ws.path, "ls-files", "-z").split("\0") if f]
        runs, found = scan_tree(ws.path, self.cfg.security, files)
        return [r.model_copy(update={"phase": phase}) for r in runs], found

    def _patch_loop(
        self,
        ws: Workspace,
        ctx,
        analysis: IssueAnalysis,
        plan: FixPlan,  # noqa: ANN001
        baseline: list[CheckResult],
        sb_ok: bool,
        sb_reason: str,
    ) -> tuple[list[Attempt], _Candidate | None]:
        budget = 1 + self.cfg.model.max_repair_attempts  # fixed by config; the model cannot change it
        attempts: list[Attempt] = []
        best: _Candidate | None = None
        proposal: PatchProposal = self.provider.propose_patch(ctx, analysis, plan)
        baseline_test_failed = any(r.kind == "test" and r.outcome == CheckOutcome.FAILED for r in baseline)
        for n in range(1, budget + 1):
            self.sm.to(S.PATCH_GENERATED)
            ws.reset()
            attempt = Attempt(number=n, kind="initial" if n == 1 else "repair", summary=truncate(proposal.summary, 500))
            attempts.append(attempt)
            try:
                files = plan_edits(proposal, ws.path, self.cfg.patch)
            except PatchRejected as e:
                attempt.validation_errors = e.errors
                feedback = "Patch rejected by validation:\n" + "\n".join(e.errors)
            else:
                ws.write(files)
                patch, manifest = ws.diff(list(files))
                attempt.changed_files = manifest
                self.sm.to(S.PATCH_VALIDATED)
                reproduction: list[CheckResult] = []
                tests_only = {p: c for p, c in files.items() if is_test_path(p)}
                if sb_ok and tests_only and len(tests_only) < len(files) and not baseline_test_failed:
                    # Fail-before evidence: run the new/changed tests against the unpatched code.
                    ws.reset()
                    ws.write(tests_only)
                    reproduction = run_checks(
                        self.cfg.verification.checks,
                        self.sandbox,
                        sb_ok,
                        sb_reason,
                        ws.path,
                        "reproduction",
                        self.cfg,
                        kinds={"test"},
                    )
                    ws.reset()
                    ws.write(files)
                checks = run_checks(
                    self.cfg.verification.checks, self.sandbox, sb_ok, sb_reason, ws.path, "candidate", self.cfg
                )
                attempt.checks = checks
                self.sm.to(S.CHECKS_EXECUTED)
                best = _Candidate(attempt, files, patch, manifest, reproduction, checks)
                if not sb_ok or not checks or all_passed(checks):
                    break
                feedback = failure_summary(checks)
            if n == budget:
                break
            try:
                proposal = self.provider.repair_patch(ctx, analysis, plan, proposal, feedback)
            except ProviderError as e:
                self.warnings.append(f"repair attempt {n + 1} could not be generated: {e}")
                break
        return attempts, best

    def _issue_finding(self, analysis: IssueAnalysis, ev: Evidence, status: RunStatus) -> Finding | None:
        if not analysis.security_relevant:
            return None
        failed_before = any(r.outcome == CheckOutcome.FAILED for r in ev.reproduction) or any(
            r.kind == "test" and r.outcome == CheckOutcome.FAILED for r in ev.baseline
        )
        if status == RunStatus.VERIFIED:
            st, note = FindingStatus.VERIFIED_REMEDIATION, "reproduced by a failing test, which passes with the patch"
        elif failed_before:
            st, note = FindingStatus.REPRODUCED, "reproduced by a failing test; remediation not verified"
        else:
            st, note = FindingStatus.CANDIDATE_VULNERABILITY, "reported in the issue; not reproduced"
        return Finding(
            id="issue",
            source="issue",
            rule_id="reported-issue",
            severity="unknown",
            evidence=note,
            confidence="medium" if failed_before else "low",
            status=st,
            related_checks=[r.check_id for r in ev.reproduction + ev.candidate],
        )

    def _finish(
        self,
        start: RepoSnapshot | None,
        status: RunStatus,
        reasons: list[str],
        failure: str | None,
        fields: dict,
        patch: str,
    ) -> Report:
        intact = None
        if start is not None:
            try:
                end = snapshot(self.root)
                intact = (end.head, end.branch, end.status_digest) == (start.head, start.branch, start.status_digest)
            except IssuePilotError:
                intact = False
            if not intact:
                self.warnings.append(
                    "The original repository changed during the run (HEAD, branch or working "
                    "tree). IssuePilot does not write there; check for concurrent edits."
                )
                if status == RunStatus.VERIFIED:
                    status = RunStatus.NEEDS_REVIEW
                    reasons = [*reasons, "original repository state changed during the run"]
        if self.sm.state != S.REPORT_GENERATED:
            self.sm.to(S.REPORT_GENERATED)
        report = Report(
            tool_version=__version__,
            run_id=self.run_id,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            status=status,
            status_reasons=reasons,
            state_history=self.sm.history,
            issue=self.issue,
            repo_start=start,
            original_repo_intact=intact,
            config_digest=self.cfg.digest(),
            sandbox=f"{self.sandbox.name} ({'isolated' if self.sandbox.isolated else 'NOT isolated'})",
            provider=ProviderInfo(name=self.provider.name, model=self.provider.model, usage=self.provider.usage),
            warnings=self.warnings,
            limitations=self.limitations,
            failure_reason=failure,
            next_action=NEXT_ACTION[status],
            **fields,
        )
        if not patch:
            report.patch_file = None
        write_report(report, self.dir, patch)
        return report
