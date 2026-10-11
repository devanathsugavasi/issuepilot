import pytest

from issuepilot.errors import IssueParseError
from issuepilot.issues import parse_issue_text


def test_title_and_acceptance_criteria():
    issue = parse_issue_text(
        "# Login fails\n\nBody\n\n## Acceptance Criteria\n- [ ] works\n* also this\n1. third\n\n## Notes\n- nope\n"
    )
    assert issue.title == "Login fails"
    assert issue.acceptance_criteria == ["works", "also this", "third"]


def test_title_falls_back_to_first_line():
    assert parse_issue_text("crash on save\nmore").title == "crash on save"


def test_empty_issue_rejected():
    with pytest.raises(IssueParseError):
        parse_issue_text("   \n")
