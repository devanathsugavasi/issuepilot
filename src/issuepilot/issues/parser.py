"""Markdown issue parsing. Issue text is untrusted data: it is parsed, never executed."""

from __future__ import annotations

import re
from pathlib import Path

from issuepilot.errors import IssueParseError
from issuepilot.schemas import Issue

MAX_ISSUE_BYTES = 200_000
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.+?)\s*$")
_CRITERIA_HEADINGS = ("acceptance criteria", "acceptance", "definition of done", "expected")


def parse_issue(path: Path) -> Issue:
    try:
        data = path.read_bytes()
    except OSError as e:
        raise IssueParseError(f"cannot read issue file {path}: {e}") from e
    if len(data) > MAX_ISSUE_BYTES:
        raise IssueParseError(f"issue file exceeds {MAX_ISSUE_BYTES} bytes")
    return parse_issue_text(data.decode("utf-8", errors="replace"), source=str(path))


def parse_issue_text(text: str, source: str = "<inline>") -> Issue:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise IssueParseError("issue is empty")
    lines = text.split("\n")
    title = ""
    criteria: list[str] = []
    section: str | None = None
    for line in lines:
        m = _HEADING.match(line)
        if m:
            heading = m.group(1).strip()
            if not title:
                title = heading
            section = heading.lower()
            continue
        if section and section.startswith(_CRITERIA_HEADINGS):
            item = _ITEM.match(line)
            if item:
                criteria.append(item.group(1))
    if not title:
        title = lines[0].strip()[:120]
    return Issue(title=title, body=text, source=source, acceptance_criteria=criteria)
