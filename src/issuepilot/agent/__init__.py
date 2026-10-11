"""Bounded context assembly. Decides which repository content a model may see."""

from __future__ import annotations

import re
from pathlib import Path

from issuepilot.config import ModelConfig
from issuepilot.llm import ModelContext
from issuepilot.patching.validate import is_sensitive
from issuepilot.repository.git import read_head_files
from issuepilot.schemas import Issue, RepoInfo
from issuepilot.security.redact import redact

TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".swift",
    ".md",
    ".toml",
    ".cfg",
    ".ini",
    ".yaml",
    ".yml",
    ".json",
    ".sql",
    ".html",
    ".css",
    ".sh",
    ".txt",
}
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_STOP = {
    "this",
    "that",
    "with",
    "from",
    "when",
    "should",
    "would",
    "could",
    "have",
    "user",
    "users",
    "issue",
    "expected",
    "actual",
    "behavior",
    "behaviour",
    "steps",
    "the",
    "and",
}
MAX_FILE_BYTES = 40_000


def _score(path: str, text: str, words: set[str], mentioned: set[str]) -> float:
    score = 0.0
    if path in mentioned or Path(path).name in mentioned:
        score += 100
    lower_path = path.lower()
    score += sum(5 for w in words if w in lower_path)
    tokens = set(_WORD.findall(text.lower()))
    score += len(words & tokens)
    return score


def build_context(issue: Issue, repo: RepoInfo, cfg: ModelConfig) -> ModelContext:
    root = Path(repo.snapshot.root)
    head = repo.snapshot.head
    words = {w.lower() for w in _WORD.findall(issue.body)} - _STOP
    mentioned = {tok.strip("`'\"()[],:") for tok in issue.body.split()}
    texts = read_head_files(
        root,
        head,
        lambda rel: Path(rel).suffix.lower() in TEXT_SUFFIXES and not is_sensitive(rel),
        MAX_FILE_BYTES,
    )
    files = sorted(texts)
    candidates = sorted(
        ((_score(rel, text, words, mentioned), rel, text) for rel, text in texts.items()),
        key=lambda c: (-c[0], c[1]),
    )

    selected: dict[str, str] = {}
    budget = cfg.max_context_bytes
    for score, rel, text in candidates:
        if score <= 0 or len(selected) >= cfg.max_context_files:
            break
        if len(text) > budget:
            continue
        selected[rel] = redact(text)
        budget -= len(text)

    instructions = {name: redact(texts[name][:8000]) for name in repo.instruction_files if name in texts}

    summary = (
        f"HEAD {repo.snapshot.head[:12]}; {repo.tracked_file_count} tracked files; "
        f"languages: {', '.join(repo.languages) or 'unknown'}; "
        f"test paths: {', '.join(repo.test_paths) or 'none detected'}; "
        f"manifests: {', '.join(repo.manifests) or 'none'}.\n"
        "Files shown below were selected by relevance and may be incomplete.\n"
        "Tracked files:\n" + "\n".join(f for f in files[:400] if not is_sensitive(f))
    )
    return ModelContext(issue_text=redact(issue.body), repo_summary=summary, files=selected, instructions=instructions)
