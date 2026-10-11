"""End-to-end runs with the deterministic fake provider. Host execution (trusted fixtures) is
used so these run without Docker; the Docker backend has its own tests in tests/security."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from issuepilot.cli import app
from issuepilot.config import Config
from issuepilot.evaluation import discover, run_case
from issuepilot.issues import parse_issue_text
from issuepilot.orchestrator import Orchestrator
from issuepilot.patching.workspace import WORKSPACE_PREFIX
from issuepilot.sandbox import DockerSandbox
from issuepilot.schemas import CheckOutcome, RunState, RunStatus
from tests.conftest import CASES, config, fake, git, host

ISSUE = parse_issue_text((CASES / "idor-dashboard" / "issue.md").read_text())


@pytest.mark.parametrize("case", discover(CASES), ids=lambda p: p.name)
def test_eval_cases_reach_expected_status(case: Path):
    res = run_case(case, trust_repo=True, overrides={"execution": {"sandbox": "host"}})
    assert res.matched, f"{res.name}: expected {res.expected}, got {res.actual} ({res.run_dir})"


def test_verified_run_artifacts_and_state_history(idor_repo, idor_script):
    cfg = config()
    orch = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg))
    r = orch.run()
    assert r.status == RunStatus.VERIFIED
    assert r.state_history[0] == RunState.INITIALIZED and r.state_history[-1] == RunState.REPORT_GENERATED
    assert r.original_repo_intact is True
    assert [c.outcome for c in r.reproduction_checks] == [CheckOutcome.FAILED]
    assert {f.status for f in r.findings} == {"verified_remediation"}
    for name in ("report.json", "report.md", "changes.patch"):
        assert (orch.dir / name).exists()
    assert json.loads((orch.dir / "report.json").read_text())["schema_version"] == "1"
    # The patch applies cleanly to the user's repository.
    git(idor_repo, "apply", "--check", str(orch.dir / "changes.patch"))


def test_dirty_worktree_is_preserved(idor_repo, idor_script):
    (idor_repo / "app" / "dashboard.py").write_text("# user's uncommitted edit\n")
    (idor_repo / "notes.txt").write_text("untracked user file\n")
    before = git(idor_repo, "status", "--porcelain")
    cfg = config()
    r = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg)).run()
    assert r.status == RunStatus.VERIFIED  # works from HEAD, not the dirty tree
    assert (idor_repo / "app" / "dashboard.py").read_text() == "# user's uncommitted edit\n"
    assert (idor_repo / "notes.txt").read_text() == "untracked user file\n"
    after = "\n".join(
        line for line in git(idor_repo, "status", "--porcelain").splitlines() if ".issuepilot" not in line
    )
    assert after.strip() == before.strip()
    assert r.original_repo_intact is True
    assert any("uncommitted" in w for w in r.warnings)


def test_sandbox_unavailable_fails_closed(idor_repo, idor_script, monkeypatch):
    marker = idor_repo.parent / "executed"
    cfg = config(
        execution={"sandbox": "docker"},
        verification={"checks": [{"id": "tests", "kind": "test", "command": f"touch {marker}"}]},
    )
    sb = DockerSandbox(cfg.execution)
    monkeypatch.setattr(sb, "availability", lambda: (False, "docker CLI not found on PATH"))
    r = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), sb).run()
    assert not marker.exists()
    assert r.status == RunStatus.NEEDS_REVIEW
    assert all(c.outcome == CheckOutcome.SKIPPED and not c.ran for c in r.baseline_checks + r.final_checks)
    assert r.patch_file is not None  # patch is still produced for review


def test_host_without_trust_fails_closed(idor_repo, idor_script):
    from issuepilot.sandbox import HostSandbox

    marker = idor_repo.parent / "executed"
    cfg = config(verification={"checks": [{"id": "t", "kind": "test", "command": f"touch {marker}"}]})
    r = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), HostSandbox(cfg.execution, trusted=False)).run()
    assert not marker.exists() and r.status == RunStatus.NEEDS_REVIEW


def test_timeout_reported(idor_repo, idor_script):
    cfg = config(
        execution={"sandbox": "host", "timeout_seconds": 1},
        verification={"checks": [{"id": "slow", "kind": "test", "command": "sleep 30"}]},
    )
    r = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg)).run()
    assert r.baseline_checks[0].outcome == CheckOutcome.TIMEOUT
    assert r.status == RunStatus.NEEDS_REVIEW


def test_candidate_regression_after_budget(idor_repo, idor_script):
    broken = {
        "summary": "breaks owners",
        "edits": [
            {"path": "app/dashboard.py", "search": "    return {", "replace": "    raise RuntimeError()\n    return {"}
        ],
    }
    idor_script["patches"] = [broken, broken]
    cfg = config(model={"provider": "fake", "fake_script": "x", "max_repair_attempts": 1})
    r = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg)).run()
    assert r.status == RunStatus.NEEDS_REVIEW
    assert len(r.attempts) == 2
    assert any("regression" in s for s in r.status_reasons)


def test_retry_budget_is_enforced(idor_repo, idor_script):
    bad = {"summary": "bad", "edits": [{"path": "../x", "search": "", "replace": "x"}]}
    idor_script["patches"] = [bad] * 10
    cfg = config(model={"provider": "fake", "fake_script": "x", "max_repair_attempts": 2})
    r = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg)).run()
    assert len(r.attempts) == 3 and r.status == RunStatus.NO_FIX


@pytest.mark.parametrize(
    "script_update,needle",
    [
        ({"fail_on": "analyze"}, "simulated provider failure"),
        ({"analysis": {"summary": "x"}}, "invalid structured output"),
        ({"patches": []}, "no further patch"),
    ],
)
def test_provider_failures_produce_failed_report(idor_repo, idor_script, script_update, needle):
    idor_script.update(script_update)
    cfg = config()
    orch = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg))
    r = orch.run()
    assert r.status == RunStatus.FAILED
    assert needle in (r.failure_reason or "")
    assert (orch.dir / "report.json").exists()


def test_workspace_cleaned_up(idor_repo, idor_script, tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    cfg = config()
    Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg)).run()
    assert not list(tmp_path.glob(f"{WORKSPACE_PREFIX}*"))


def test_missing_required_scanner(idor_repo, idor_script, monkeypatch):
    from issuepilot.security import scanners

    real_which = scanners.shutil.which
    monkeypatch.setattr(scanners.shutil, "which", lambda n: None if n in ("gitleaks", "semgrep") else real_which(n))
    cfg = config(security={"gitleaks": True, "require_scanners": True})
    r = Orchestrator(idor_repo, ISSUE, cfg, fake(idor_script), host(cfg)).run()
    assert r.status == RunStatus.NEEDS_REVIEW
    assert any("gitleaks" in s for s in r.status_reasons)
    assert any(s.scanner == "gitleaks" and not s.ran for s in r.scanner_runs)


def test_cli_end_to_end(idor_repo):
    runner = CliRunner()
    script = CASES / "idor-dashboard" / "fake.yaml"
    assert runner.invoke(app, ["init", "--repo", str(idor_repo)]).exit_code == 0
    assert "already exists" in runner.invoke(app, ["init", "--repo", str(idor_repo)]).output
    cfg_file = idor_repo.parent / "ip.yaml"
    cfg_file.write_text(
        f"model: {{provider: fake, fake_script: {script}}}\n"
        "execution: {sandbox: host}\n"
        "verification: {checks: [{id: tests, kind: test, command: python3 -m unittest discover -s tests -q}]}\n"
    )
    issue = CASES / "idor-dashboard" / "issue.md"
    common = ["--repo", str(idor_repo), "--config", str(cfg_file)]

    doc = runner.invoke(app, ["doctor", *common])
    assert "host execution requires --trust-repo" in doc.output and doc.exit_code == 1

    plan = runner.invoke(app, ["plan", "--issue", str(issue), *common])
    assert plan.exit_code == 0 and "Proposed change" in plan.output
    assert git(idor_repo, "status", "--porcelain").strip() == "?? issuepilot.yaml"

    res = runner.invoke(app, ["run", "--issue", str(issue), "--trust-repo", *common])
    assert res.exit_code == 0, res.output
    assert "Result: VERIFIED" in res.output
    run_id = next((idor_repo / ".issuepilot" / "runs").iterdir()).name
    rep = runner.invoke(app, ["report", "--run", run_id, *common])
    assert "IssuePilot report — VERIFIED" in rep.output
    d = runner.invoke(app, ["diff", "--run", run_id, *common])
    assert '+    if account["owner"] != current_user:' in d.output
    assert runner.invoke(app, ["report", "--run", "../../etc", *common]).exit_code == 1

    no_trust = runner.invoke(app, ["run", "--issue", str(issue), *common])
    assert no_trust.exit_code == 2 and "NEEDS_REVIEW" in no_trust.output


def test_cli_security_command(idor_repo):
    runner = CliRunner()
    clean = runner.invoke(app, ["security", "--repo", str(idor_repo)])
    assert clean.exit_code == 0 and "builtin-secrets: ran" in clean.output
    (idor_repo / "k.py").write_text('API_KEY = "abcdefghijkl1234"\n')
    git(idor_repo, "add", "k.py")
    hit = runner.invoke(app, ["security", "--repo", str(idor_repo)])
    assert hit.exit_code == 1 and "abcdefghijkl1234" not in hit.output


def test_config_defaults_without_file(idor_repo):
    assert Config().execution.sandbox == "docker"
