import pytest

from issuepilot.errors import InvalidTransition
from issuepilot.orchestrator import StateMachine
from issuepilot.schemas import RunState as S


def test_happy_path_and_repair_loop():
    sm = StateMachine()
    for s in [
        S.REPOSITORY_VALIDATED,
        S.ISSUE_ANALYZED,
        S.PLAN_READY,
        S.WORKSPACE_CREATED,
        S.BASELINE_CAPTURED,
        S.PATCH_GENERATED,
        S.PATCH_VALIDATED,
        S.CHECKS_EXECUTED,
        S.PATCH_GENERATED,
        S.PATCH_GENERATED,
        S.PATCH_VALIDATED,
        S.CHECKS_EXECUTED,
        S.REPORT_GENERATED,
    ]:
        sm.to(s)
    assert sm.history[-1] == S.REPORT_GENERATED


@pytest.mark.parametrize(
    "path",
    [
        [S.PLAN_READY],
        [S.REPOSITORY_VALIDATED, S.ISSUE_ANALYZED, S.PLAN_READY, S.PATCH_GENERATED],
        [S.REPOSITORY_VALIDATED, S.CHECKS_EXECUTED],
    ],
)
def test_skipping_states_is_rejected(path):
    sm = StateMachine()
    with pytest.raises(InvalidTransition):
        for s in path:
            sm.to(s)


def test_report_reachable_from_anywhere_but_terminal():
    sm = StateMachine()
    sm.to(S.REPORT_GENERATED)
    with pytest.raises(InvalidTransition):
        sm.to(S.REPORT_GENERATED)
    with pytest.raises(InvalidTransition):
        sm.to(S.REPOSITORY_VALIDATED)
