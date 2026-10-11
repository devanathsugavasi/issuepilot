"""Reproducible benchmark runner.

A case directory contains `case.yaml`, an issue file, and a `fixture/` tree that is turned into
a fresh single-commit Git repository for every run. See evals/README.md for the format.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from issuepilot.config import Config
from issuepilot.errors import ConfigError
from issuepilot.issues import parse_issue
from issuepilot.llm import ModelProvider, get_provider
from issuepilot.orchestrator import Orchestrator
from issuepilot.repository.git import git
from issuepilot.sandbox import Sandbox, get_sandbox
from issuepilot.schemas import CheckOutcome, RunStatus

EVAL_SCHEMA_VERSION = 1
_UNSAFE_MARKERS = (
    "protected by policy",
    "traversal",
    "outside the workspace",
    "absolute path",
    "credential-like",
    "symlink",
)


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str
    description: str = ""
    issue: str = "issue.md"
    fixture: str = "fixture"
    config: dict[str, Any] = Field(default_factory=dict)
    expected_status: RunStatus
    known_limitations: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    name: str
    expected: RunStatus
    actual: RunStatus
    matched: bool
    attempts: int
    regression: bool
    reproduced: bool
    unsafe_actions_blocked: int
    new_findings: int
    duration_s: float
    run_dir: str
    input_tokens: int
    output_tokens: int


def load_case(case_dir: Path) -> EvalCase:
    path = case_dir / "case.yaml"
    try:
        return EvalCase.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"invalid eval case {path}: {e}") from e


def materialize_fixture(case_dir: Path, case: EvalCase, dest: Path) -> Path:
    repo = dest / "repo"
    shutil.copytree(case_dir / case.fixture, repo, symlinks=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "-c", "user.email=eval@localhost", "-c", "user.name=eval", "add", "-A")
    git(repo, "-c", "user.email=eval@localhost", "-c", "user.name=eval", "commit", "-q", "-m", "fixture")
    return repo


def run_case(
    case_dir: Path,
    *,
    trust_repo: bool,
    overrides: dict[str, Any] | None = None,
    provider: ModelProvider | None = None,
    sandbox: Sandbox | None = None,
) -> CaseResult:
    case = load_case(case_dir)
    raw = _deep_merge(case.config, overrides or {})
    if fs := raw.get("model", {}).get("fake_script"):
        raw["model"]["fake_script"] = str((case_dir / fs).resolve())
    cfg = Config.model_validate(raw)
    with tempfile.TemporaryDirectory(prefix="issuepilot-eval-") as tmp:
        repo = materialize_fixture(case_dir, case, Path(tmp))
        issue = parse_issue(case_dir / case.issue)
        orch = Orchestrator(
            repo, issue, cfg, provider or get_provider(cfg.model), sandbox or get_sandbox(cfg.execution, trust_repo)
        )
        t0 = time.monotonic()
        report = orch.run()
        elapsed = time.monotonic() - t0
        # Keep the run artifacts: move them out of the temp fixture.
        keep = Path(tempfile.gettempdir()) / "issuepilot-eval-runs" / case.name / report.run_id
        shutil.copytree(orch.dir, keep, dirs_exist_ok=True)
    base = {r.check_id: r.outcome for r in report.baseline_checks}
    return CaseResult(
        name=case.name,
        expected=case.expected_status,
        actual=report.status,
        matched=report.status == case.expected_status,
        attempts=len(report.attempts),
        regression=any(
            base.get(r.check_id) == CheckOutcome.PASSED and r.outcome == CheckOutcome.FAILED
            for r in report.final_checks
        ),
        reproduced=any(r.outcome == CheckOutcome.FAILED for r in report.reproduction_checks)
        or any(r.kind == "test" and r.outcome == CheckOutcome.FAILED for r in report.baseline_checks),
        unsafe_actions_blocked=sum(
            1 for a in report.attempts for e in a.validation_errors if any(m in e for m in _UNSAFE_MARKERS)
        ),
        new_findings=sum(1 for f in report.findings if f.introduced_by_patch),
        duration_s=round(elapsed, 2),
        run_dir=str(keep),
        input_tokens=report.provider.usage.input_tokens,
        output_tokens=report.provider.usage.output_tokens,
    )


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    n = len(results)
    if n == 0:
        return {"cases": 0}
    with_patch = [r for r in results if r.actual in (RunStatus.VERIFIED, RunStatus.NEEDS_REVIEW)]
    return {
        "eval_schema_version": EVAL_SCHEMA_VERSION,
        "cases": n,
        "status_match_rate": round(sum(r.matched for r in results) / n, 3),
        "verified_rate": round(sum(r.actual == RunStatus.VERIFIED for r in results) / n, 3),
        "regression_rate": round(sum(r.regression for r in with_patch) / len(with_patch), 3) if with_patch else None,
        "reproduction_rate": round(sum(r.reproduced for r in with_patch) / len(with_patch), 3) if with_patch else None,
        "unsafe_actions_blocked": sum(r.unsafe_actions_blocked for r in results),
        "new_findings_introduced": sum(r.new_findings for r in results),
        "median_duration_s": sorted(r.duration_s for r in results)[n // 2],
        "total_input_tokens": sum(r.input_tokens for r in results),
        "total_output_tokens": sum(r.output_tokens for r in results),
        "note": "Human acceptance and cost per fix require reviewer data and real-model runs; not measured here.",
    }


def discover(path: Path) -> list[Path]:
    if (path / "case.yaml").exists():
        return [path]
    return sorted(p.parent for p in path.glob("*/case.yaml"))


def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in a.items()}
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
