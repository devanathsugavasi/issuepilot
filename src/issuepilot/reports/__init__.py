"""Versioned JSON report + human-readable Markdown summary. Everything is redacted on write."""

from __future__ import annotations

import re
from pathlib import Path

from issuepilot.errors import IssuePilotError
from issuepilot.schemas import CheckResult, Report
from issuepilot.security.redact import redact

_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")


def run_dir(repo_root: Path, report_dir: str, run_id: str) -> Path:
    if not _RUN_ID.match(run_id):
        raise IssuePilotError(f"invalid run id: {run_id!r}")
    base = (repo_root / report_dir).resolve()
    return base / run_id


def write_report(report: Report, directory: Path, patch: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if patch:
        (directory / "changes.patch").write_text(redact(patch, generic=False), encoding="utf-8")
    (directory / "report.json").write_text(redact(report.model_dump_json(indent=2)), encoding="utf-8")
    (directory / "report.md").write_text(redact(render_markdown(report)), encoding="utf-8")


def load_report(directory: Path) -> Report:
    path = directory / "report.json"
    if not path.exists():
        raise IssuePilotError(f"no report at {path}")
    return Report.model_validate_json(path.read_text(encoding="utf-8"))


def _checks_table(rows: list[CheckResult]) -> list[str]:
    if not rows:
        return ["_none_", ""]
    out = ["| Check | Kind | Ran | Outcome | Exit | Duration | Environment |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        dur = f"{r.duration_s:.2f}s" if r.duration_s is not None else "-"
        note = f" ({r.skip_reason})" if r.skip_reason else ""
        out.append(
            f"| `{r.check_id}` | {r.kind} | {'yes' if r.ran else 'no'} | {r.outcome}{note} | "
            f"{r.exit_code if r.exit_code is not None else '-'} | {dur} | {r.environment} |"
        )
    return [*out, ""]


def render_markdown(r: Report) -> str:
    md = [
        f"# IssuePilot report — {r.status}",
        "",
        f"- **Run:** `{r.run_id}` ({r.created_at})",
        f"- **Issue:** {r.issue.title} (`{r.issue.source}`)",
    ]
    if r.repo_start:
        md.append(f"- **Starting commit:** `{r.repo_start.head}` on `{r.repo_start.branch or 'detached'}`")
    md += [
        f"- **Original repository intact:** {r.original_repo_intact}",
        f"- **Sandbox:** {r.sandbox}",
        f"- **Provider:** {r.provider.name} / {r.provider.model or 'n/a'} "
        f"({r.provider.usage.calls} calls, {r.provider.usage.input_tokens} in / "
        f"{r.provider.usage.output_tokens} out tokens)",
        f"- **Tool version:** {r.tool_version} · report schema {r.schema_version} · config {r.config_digest}",
        "",
        "## Why this status",
        *[f"- {x}" for x in r.status_reasons],
        "",
    ]
    if r.failure_reason:
        md += ["## Failure", "", f"```\n{r.failure_reason}\n```", ""]
    if r.analysis:
        a = r.analysis
        md += ["## Analysis", "", a.summary, ""]
        if a.expected_behavior:
            md.append(f"- **Expected:** {a.expected_behavior}")
        if a.actual_behavior:
            md.append(f"- **Actual:** {a.actual_behavior}")
        md.append(f"- **Security relevant:** {a.security_relevant}")
        if a.acceptance_criteria:
            md += ["", "**Acceptance criteria**", *[f"- {c}" for c in a.acceptance_criteria]]
        if a.missing_information:
            md += ["", "**Missing information**", *[f"- {c}" for c in a.missing_information]]
        md.append("")
    if r.plan:
        md += ["## Plan", "", r.plan.proposed_change, ""]
        if r.plan.test_plan:
            md += ["**Test plan**", *[f"- {t}" for t in r.plan.test_plan], ""]
    md += ["## Changed files", ""]
    md += [f"- `{c.path}` ({c.change}{', test' if c.is_test else ''})" for c in r.changed_files] or ["_none_"]
    if r.patch_file:
        md += ["", f"Patch: `{r.patch_file}`"]
    md += ["", "## Baseline checks (before patch)", "", *_checks_table(r.baseline_checks)]
    if r.reproduction_checks:
        md += ["## Reproduction (new tests against unpatched code)", "", *_checks_table(r.reproduction_checks)]
    md += ["## Final checks (with patch)", "", *_checks_table(r.final_checks)]
    md += ["## Attempts", ""]
    for at in r.attempts:
        md.append(f"- **#{at.number} ({at.kind})** {at.summary}")
        md += [f"  - rejected: {e}" for e in at.validation_errors]
        md += [f"  - `{c.check_id}`: {c.outcome}" for c in at.checks]
    md += ["", "## Security", ""]
    md += [f"- {s.scanner} [{s.phase}]: {'ran' if s.ran else 'did not run'} — {s.detail}" for s in r.scanner_runs]
    if r.findings:
        md += [
            "",
            "| Status | Source | Rule | Severity | Location | New in patch | Resolved |",
            "|---|---|---|---|---|---|---|",
        ]
        for f in r.findings:
            loc = f"{f.file}:{f.line_start}" if f.file else "-"
            md.append(
                f"| {f.status} | {f.source} | {f.rule_id} | {f.severity} | {loc} | "
                f"{f.introduced_by_patch} | {f.resolved_in_candidate} |"
            )
    else:
        md.append("\nNo findings reported by the scanners that ran. This is not proof of absence.")
    if r.test_changes:
        md += ["", "## Test changes requiring review", *[f"- {t}" for t in r.test_changes]]
    if r.warnings:
        md += ["", "## Warnings", *[f"- {w}" for w in r.warnings]]
    md += ["", "## Limitations", *[f"- {x}" for x in r.limitations], "", "## Next action", "", r.next_action, ""]
    return "\n".join(md)
