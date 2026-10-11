from issuepilot.schemas import CheckOutcome as O
from issuepilot.schemas import CheckResult, Finding, FindingStatus, RunStatus
from issuepilot.verification import Evidence, decide_status


def chk(outcome, phase="candidate", kind="test", cid="tests"):
    return CheckResult(
        check_id=cid, kind=kind, command="c", phase=phase, environment="host", ran=outcome != O.SKIPPED, outcome=outcome
    )


def ev(**kw):
    base = dict(
        patch_valid=True,
        sandbox_ok=True,
        baseline=[chk(O.FAILED, "baseline")],
        reproduction=[],
        candidate=[chk(O.PASSED)],
    )
    base.update(kw)
    return Evidence(**base)


def test_verified_requires_demonstrated_failure():
    assert decide_status(ev())[0] == RunStatus.VERIFIED
    assert (
        decide_status(ev(baseline=[chk(O.PASSED, "baseline")], reproduction=[chk(O.FAILED, "reproduction")]))[0]
        == RunStatus.VERIFIED
    )
    status, reasons = decide_status(ev(baseline=[chk(O.PASSED, "baseline")]))
    assert status == RunStatus.NEEDS_REVIEW and any("never demonstrated" in r for r in reasons)


def test_no_valid_patch_is_no_fix():
    assert decide_status(ev(patch_valid=False))[0] == RunStatus.NO_FIX


def test_skipped_checks_are_never_passed():
    status, reasons = decide_status(ev(sandbox_ok=False, candidate=[chk(O.SKIPPED)]))
    assert status == RunStatus.NEEDS_REVIEW
    assert any("sandbox" in r for r in reasons)


def test_no_checks_configured():
    assert decide_status(ev(candidate=[]))[0] == RunStatus.NEEDS_REVIEW


def test_failures_regressions_findings_weakening():
    assert decide_status(ev(candidate=[chk(O.FAILED)]))[0] == RunStatus.NEEDS_REVIEW
    assert decide_status(ev(candidate=[chk(O.TIMEOUT)]))[0] == RunStatus.NEEDS_REVIEW
    reg = ev(
        baseline=[chk(O.FAILED, "baseline"), chk(O.PASSED, "baseline", "lint", "lint")],
        candidate=[chk(O.PASSED), chk(O.FAILED, kind="lint", cid="lint")],
    )
    assert any("regression" in r for r in decide_status(reg)[1])
    f = Finding(
        id="1",
        source="s",
        rule_id="r",
        severity="high",
        evidence="e",
        confidence="high",
        status=FindingStatus.SCANNER_REPORTED,
        introduced_by_patch=True,
    )
    assert decide_status(ev(new_findings=[f]))[0] == RunStatus.NEEDS_REVIEW
    low = f.model_copy(update={"severity": "low"})
    assert decide_status(ev(new_findings=[low]))[0] == RunStatus.VERIFIED
    assert decide_status(ev(weakened_tests=["x: removes 1 assertion line(s)"]))[0] == RunStatus.NEEDS_REVIEW
    assert decide_status(ev(scanners_missing=["semgrep"]))[0] == RunStatus.NEEDS_REVIEW
