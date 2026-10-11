from pathlib import Path

import pytest

from issuepilot.errors import IssuePilotError
from issuepilot.reports import load_report, render_markdown, run_dir, write_report
from issuepilot.schemas import Issue, ProviderInfo, Report, RunStatus, Usage


def _report(**kw) -> Report:
    base = dict(
        tool_version="0",
        run_id="20260101T000000Z-abcdef",
        created_at="t",
        status=RunStatus.NO_FIX,
        status_reasons=["r"],
        state_history=[],
        issue=Issue(title="t", body="b", source="s"),
        config_digest="d",
        sandbox="docker",
        provider=ProviderInfo(name="fake", model=None, usage=Usage()),
        next_action="n",
    )
    base.update(kw)
    return Report(**base)


def test_roundtrip_and_redaction(tmp_path: Path):
    r = _report(warnings=["leaked ghp_" + "a" * 36])
    write_report(r, tmp_path, "")
    loaded = load_report(tmp_path)
    assert loaded.status == RunStatus.NO_FIX and loaded.schema_version == "1"
    assert "ghp_" not in (tmp_path / "report.json").read_text()
    assert "ghp_" not in (tmp_path / "report.md").read_text()
    assert not (tmp_path / "changes.patch").exists()
    assert "NO_FIX" in render_markdown(loaded)


@pytest.mark.parametrize("rid", ["../etc", "x", "20260101T000000Z-abcdef/../../x"])
def test_run_id_validated(tmp_path: Path, rid: str):
    with pytest.raises(IssuePilotError):
        run_dir(tmp_path, ".issuepilot/runs", rid)
