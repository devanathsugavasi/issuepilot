"""Command-line interface.

Exit codes: 0 VERIFIED / success, 1 FAILED or error, 2 NEEDS_REVIEW, 3 NO_FIX.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer

from issuepilot import __version__
from issuepilot.agent import build_context
from issuepilot.config import CONFIG_FILENAME, STARTER_CONFIG, Config, load_config
from issuepilot.errors import IssuePilotError
from issuepilot.issues import parse_issue
from issuepilot.llm import get_provider, provider_status
from issuepilot.reports import load_report, render_markdown, run_dir
from issuepilot.repository.git import inspect_repo, repo_root, tracked_files
from issuepilot.sandbox import get_sandbox
from issuepilot.schemas import PlanResult, RunStatus
from issuepilot.security.redact import redact
from issuepilot.security.scanners import scan_tree

app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="IssuePilot — security-aware, evidence-first AI issue solving."
)

EXIT = {RunStatus.VERIFIED: 0, RunStatus.FAILED: 1, RunStatus.NEEDS_REVIEW: 2, RunStatus.NO_FIX: 3}
RepoOpt = Annotated[Path, typer.Option("--repo", help="Path inside the target Git repository.")]
ConfigOpt = Annotated[Path | None, typer.Option("--config", help=f"Config file (default: <repo>/{CONFIG_FILENAME}).")]
IssueOpt = Annotated[Path, typer.Option("--issue", help="Markdown issue file.", exists=True, dir_okay=False)]
TrustOpt = Annotated[
    bool, typer.Option("--trust-repo", help="Allow `sandbox: host` to run repository code WITHOUT isolation.")
]


def _fail(msg: str) -> typer.Exit:
    typer.secho(f"error: {redact(msg)}", fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _load(repo: Path, config: Path | None) -> tuple[Path, Config, Path | None]:
    root = repo_root(repo)
    cfg, src = load_config(root, config)
    return root, cfg, src


@app.callback(invoke_without_command=True)
def _main(version: Annotated[bool, typer.Option("--version", help="Show version.")] = False) -> None:
    if version:
        typer.echo(f"issuepilot {__version__}")
        raise typer.Exit()


@app.command()
def init(repo: RepoOpt = Path(".")) -> None:
    """Create a starter issuepilot.yaml (never overwrites)."""
    try:
        root = repo_root(repo)
    except IssuePilotError as e:
        raise _fail(str(e)) from e
    target = root / CONFIG_FILENAME
    if target.exists():
        typer.echo(f"{target} already exists; not modified.")
        return
    target.write_text(STARTER_CONFIG, encoding="utf-8")
    typer.echo(f"Created {target}")
    typer.echo("Tip: add `.issuepilot/` to your .gitignore (run reports are written there).")


@app.command()
def doctor(repo: RepoOpt = Path("."), config: ConfigOpt = None, trust_repo: TrustOpt = False) -> None:
    """Check repository, configuration, provider, sandbox and scanners. Makes no changes."""
    ok = True

    def line(good: bool | None, label: str, detail: str) -> None:
        mark = {True: "ok  ", False: "FAIL", None: "warn"}[good]
        color = {True: typer.colors.GREEN, False: typer.colors.RED, None: typer.colors.YELLOW}[good]
        typer.secho(f"[{mark}] {label}: {redact(detail)}", fg=color)

    line(shutil.which("git") is not None, "git", shutil.which("git") or "not found")
    try:
        root, cfg, src = _load(repo, config)
        info = inspect_repo(root)
        line(True, "repository", f"{root} @ {info.snapshot.head[:12]} ({info.snapshot.branch or 'detached'})")
        if info.snapshot.dirty:
            line(None, "working tree", "uncommitted changes present (runs use HEAD only)")
        line(True, "config", str(src) if src else "defaults (no issuepilot.yaml)")
    except IssuePilotError as e:
        line(False, "repository/config", str(e))
        raise typer.Exit(1) from e
    good, detail = provider_status(cfg.model)
    line(good or None, "model provider", detail)
    sb = get_sandbox(cfg.execution, trust_repo)
    sb_ok, sb_detail = sb.availability()
    line(sb_ok if sb.isolated else (None if sb_ok else False), f"sandbox ({sb.name})", sb_detail)
    ok &= sb_ok
    if not cfg.verification.checks:
        line(None, "checks", "no verification checks configured; runs cannot be VERIFIED")
    for name, enabled in (("gitleaks", cfg.security.gitleaks), ("semgrep", cfg.security.semgrep)):
        if enabled:
            found = shutil.which(name) is not None
            line(
                found if cfg.security.require_scanners else (True if found else None),
                name,
                "installed" if found else "not installed",
            )
            ok &= found or not cfg.security.require_scanners
    line(True, "permissions", "commit/push/merge/branch modification are disabled (not implemented)")
    raise typer.Exit(0 if ok else 1)


@app.command()
def plan(
    issue: IssueOpt,
    repo: RepoOpt = Path("."),
    config: ConfigOpt = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Read-only analysis and fix plan. Edits nothing and executes no repository code."""
    try:
        root, cfg, _ = _load(repo, config)
        parsed = parse_issue(issue)
        info = inspect_repo(root)
        provider = get_provider(cfg.model)
        ctx = build_context(parsed, info, cfg.model)
        analysis = provider.analyze_issue(ctx)
        fix = provider.plan_fix(ctx, analysis) if analysis.sufficient_information else None
    except IssuePilotError as e:
        raise _fail(str(e)) from e
    result = PlanResult(issue=parsed, repo=info, analysis=analysis, plan=fix, context_files=sorted(ctx.files))
    if as_json:
        typer.echo(redact(result.model_dump_json(indent=2)))
        return
    out = [f"# Plan: {parsed.title}", "", analysis.summary, ""]
    if analysis.expected_behavior:
        out.append(f"- Expected: {analysis.expected_behavior}")
    if analysis.actual_behavior:
        out.append(f"- Actual: {analysis.actual_behavior}")
    out.append(f"- Security relevant: {analysis.security_relevant}")
    out += ["", "## Acceptance criteria", *[f"- {c}" for c in analysis.acceptance_criteria or ["(none stated)"]]]
    out += ["", "## Relevant files", *[f"- {f}" for f in analysis.relevant_files or sorted(ctx.files)]]
    if fix is None:
        out += ["", "## Not enough information", *[f"- {m}" for m in analysis.missing_information]]
    else:
        out += ["", "## Proposed change", fix.proposed_change, "", "## Test plan", *[f"- {t}" for t in fix.test_plan]]
        if fix.security_considerations:
            out += ["", "## Security considerations", *[f"- {s}" for s in fix.security_considerations]]
        if fix.uncertainties:
            out += ["", "## Uncertainties", *[f"- {u}" for u in fix.uncertainties]]
    typer.echo(redact("\n".join(out)))


@app.command()
def run(issue: IssueOpt, repo: RepoOpt = Path("."), config: ConfigOpt = None, trust_repo: TrustOpt = False) -> None:
    """Solve an issue in an isolated workspace and write an evidence report."""
    from issuepilot.orchestrator import Orchestrator

    try:
        root, cfg, _ = _load(repo, config)
        parsed = parse_issue(issue)
        provider = get_provider(cfg.model)
        orch = Orchestrator(root, parsed, cfg, provider, get_sandbox(cfg.execution, trust_repo))
    except IssuePilotError as e:
        raise _fail(str(e)) from e
    typer.echo(f"Run {orch.run_id}: working in an isolated clone of HEAD …")
    report = orch.run()
    color = {RunStatus.VERIFIED: typer.colors.GREEN, RunStatus.NEEDS_REVIEW: typer.colors.YELLOW}.get(
        report.status, typer.colors.RED
    )
    typer.secho(f"\nResult: {report.status}", fg=color, bold=True)
    for reason in report.status_reasons:
        typer.echo(f"  - {reason}")
    passed = sum(1 for c in report.final_checks if c.outcome == "PASSED")
    typer.echo(f"Changed files: {len(report.changed_files)}")
    typer.echo(f"Checks: {passed}/{len(report.final_checks)} passed (sandbox: {report.sandbox})")
    typer.echo(
        f"Security: {sum(1 for f in report.findings if f.introduced_by_patch)} new finding(s), "
        f"{len(report.findings)} total"
    )
    typer.echo(f"Report: {orch.dir / 'report.md'}")
    if report.patch_file:
        typer.echo(f"Patch:  {report.patch_file}")
    raise typer.Exit(EXIT[report.status])


@app.command()
def report(
    run_id: Annotated[str, typer.Option("--run")],
    repo: RepoOpt = Path("."),
    config: ConfigOpt = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show a completed run's report."""
    try:
        root, cfg, _ = _load(repo, config)
        r = load_report(run_dir(root, cfg.report_dir, run_id))
    except IssuePilotError as e:
        raise _fail(str(e)) from e
    typer.echo(r.model_dump_json(indent=2) if as_json else render_markdown(r))


@app.command()
def diff(
    run_id: Annotated[str, typer.Option("--run")],
    repo: RepoOpt = Path("."),
    config: ConfigOpt = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write patch to file.")] = None,
) -> None:
    """Print or export a run's candidate patch."""
    try:
        root, cfg, _ = _load(repo, config)
        p = run_dir(root, cfg.report_dir, run_id) / "changes.patch"
        if not p.exists():
            raise IssuePilotError(f"run {run_id} produced no patch")
    except IssuePilotError as e:
        raise _fail(str(e)) from e
    if output:
        if output.exists():
            raise _fail(f"{output} exists; refusing to overwrite")
        output.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        typer.echo(f"Wrote {output}")
    else:
        typer.echo(p.read_text(encoding="utf-8"), nl=False)


@app.command()
def security(
    repo: RepoOpt = Path("."), config: ConfigOpt = None, as_json: Annotated[bool, typer.Option("--json")] = False
) -> None:
    """Run configured scanners on tracked files. Read-only; applies no fixes."""
    try:
        root, cfg, _ = _load(repo, config)
        runs, findings = scan_tree(root, cfg.security, tracked_files(root))
    except IssuePilotError as e:
        raise _fail(str(e)) from e
    if as_json:
        typer.echo(
            json.dumps(
                {"scanners": [r.model_dump() for r in runs], "findings": [f.model_dump(mode="json") for f in findings]},
                indent=2,
            )
        )
    else:
        for r in runs:
            typer.echo(f"{r.scanner}: {'ran' if r.ran else 'DID NOT RUN'} — {r.detail}")
        for f in findings:
            typer.echo(f"[{f.severity}] {f.source}:{f.rule_id} {f.file}:{f.line_start} — {f.evidence}")
        typer.echo(
            f"{len(findings)} finding(s) (scanner-reported, unverified). No findings does not mean no vulnerabilities."
        )
    missing = [r.scanner for r in runs if not r.ran]
    raise typer.Exit(1 if (missing and cfg.security.require_scanners) or findings else 0)


@app.command("eval")
def eval_cmd(
    path: Annotated[Path, typer.Argument(help="Case directory or directory of cases.")] = Path("evals/cases"),
    trust_repo: TrustOpt = False,
    sandbox: Annotated[str | None, typer.Option(help="Override execution.sandbox (docker|host).")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Run benchmark cases and report measured metrics."""
    from issuepilot.evaluation import discover, run_case, summarize

    cases = discover(path)
    if not cases:
        raise _fail(f"no cases found under {path}")
    overrides = {"execution": {"sandbox": sandbox}} if sandbox else None
    results = []
    for case in cases:
        try:
            res = run_case(case, trust_repo=trust_repo, overrides=overrides)
        except IssuePilotError as e:
            raise _fail(f"{case.name}: {e}") from e
        mark = "match" if res.matched else "MISMATCH"
        typer.echo(
            f"{res.name}: expected {res.expected}, got {res.actual} [{mark}] "
            f"attempts={res.attempts} blocked_unsafe={res.unsafe_actions_blocked}"
        )
        results.append(res)
    summary = summarize(results)
    typer.echo(json.dumps(summary, indent=2))
    if output:
        output.write_text(
            json.dumps({"summary": summary, "results": [r.model_dump(mode="json") for r in results]}, indent=2),
            encoding="utf-8",
        )
    raise typer.Exit(0 if all(r.matched for r in results) else 1)
