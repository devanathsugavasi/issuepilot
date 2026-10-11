"""Run configured checks through a sandbox and derive an evidence-based status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from issuepilot.config import CheckConfig, Config
from issuepilot.sandbox import Sandbox
from issuepilot.schemas import CheckOutcome, CheckResult, Finding, RunStatus
from issuepilot.security.redact import redact, truncate


def run_checks(
    checks: list[CheckConfig],
    sandbox: Sandbox,
    sandbox_ok: bool,
    sandbox_reason: str,
    workspace: Path,
    phase: str,
    cfg: Config,
    kinds: set[str] | None = None,
) -> list[CheckResult]:
    results = []
    for check in checks:
        if kinds is not None and check.kind not in kinds:
            continue
        base: dict[str, Any] = {
            "check_id": check.id,
            "kind": check.kind,
            "command": check.command,
            "phase": phase,
            "environment": sandbox.name,
        }
        if not sandbox_ok:
            # Fail closed: never execute repository code without an available sandbox.
            results.append(
                CheckResult(
                    **base,
                    ran=False,
                    outcome=CheckOutcome.SKIPPED,
                    skip_reason=f"sandbox unavailable: {sandbox_reason}",
                )
            )
            continue
        started = datetime.now(UTC).isoformat(timespec="seconds")
        res = sandbox.run(workspace, check.command, cfg.execution.timeout_seconds)
        if res.error:
            outcome = CheckOutcome.ERROR
        elif res.timed_out:
            outcome = CheckOutcome.TIMEOUT
        else:
            outcome = CheckOutcome.PASSED if res.exit_code == 0 else CheckOutcome.FAILED
        output = res.error or res.output
        results.append(
            CheckResult(
                **base,
                ran=res.error is None,
                outcome=outcome,
                exit_code=res.exit_code,
                started_at=started,
                duration_s=round(res.duration_s, 3),
                output=truncate(redact(output), cfg.verification.max_output_chars),
            )
        )
    return results


def failure_summary(results: list[CheckResult], limit: int = 12000) -> str:
    parts = [
        f"## {r.check_id} ({r.kind}) -> {r.outcome} exit={r.exit_code}\n{r.output}"
        for r in results
        if r.outcome != CheckOutcome.PASSED
    ]
    return truncate("\n\n".join(parts), limit)


def all_passed(results: list[CheckResult]) -> bool:
    return bool(results) and all(r.outcome == CheckOutcome.PASSED for r in results)


@dataclass
class Evidence:
    patch_valid: bool
    sandbox_ok: bool
    baseline: list[CheckResult]
    reproduction: list[CheckResult]
    candidate: list[CheckResult]
    new_findings: list[Finding] = field(default_factory=list)
    weakened_tests: list[str] = field(default_factory=list)
    scanners_missing: list[str] = field(default_factory=list)


BLOCKING_SEVERITIES = {"medium", "high", "critical", "unknown"}


def decide_status(ev: Evidence) -> tuple[RunStatus, list[str]]:
    """Pure function: the only place a final status is derived. The model has no input here."""
    if not ev.patch_valid:
        return RunStatus.NO_FIX, ["no proposed patch passed validation within the attempt budget"]
    reasons: list[str] = []
    if not ev.sandbox_ok:
        reasons.append("checks were not executed because no sandbox was available (fail-closed)")
    if not ev.candidate:
        reasons.append("no verification checks are configured")
    for r in ev.candidate:
        if r.outcome != CheckOutcome.PASSED:
            reasons.append(f"check '{r.check_id}' did not pass on the candidate ({r.outcome})")
    base = {r.check_id: r.outcome for r in ev.baseline}
    for r in ev.candidate:
        if base.get(r.check_id) == CheckOutcome.PASSED and r.outcome == CheckOutcome.FAILED:
            reasons.append(f"regression: '{r.check_id}' passed at baseline but fails with the patch")
    demonstrated = any(r.outcome == CheckOutcome.FAILED for r in ev.baseline if r.kind == "test") or any(
        r.outcome == CheckOutcome.FAILED for r in ev.reproduction
    )
    if ev.sandbox_ok and ev.candidate and not demonstrated:
        reasons.append("the defect was never demonstrated: no test failed before the patch")
    for f in ev.new_findings:
        if f.severity in BLOCKING_SEVERITIES:
            reasons.append(f"patch introduced a {f.severity} security finding: {f.rule_id} in {f.file}")
    for w in ev.weakened_tests:
        reasons.append(f"test changes need review: {w}")
    for s in ev.scanners_missing:
        reasons.append(f"required scanner unavailable: {s}")
    if reasons:
        return RunStatus.NEEDS_REVIEW, list(dict.fromkeys(reasons))
    return RunStatus.VERIFIED, [
        "a test failed before the patch and all configured checks pass after it, "
        "with no regressions or new blocking findings"
    ]
