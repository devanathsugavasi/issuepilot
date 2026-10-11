"""Deterministic scripted provider for tests, demos and evaluations. No network access."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from issuepilot.errors import ProviderError, ProviderUnavailable
from issuepilot.llm import ModelContext
from issuepilot.schemas import FixPlan, IssueAnalysis, PatchProposal, Usage


class FakeProvider:
    """Script keys: `analysis`, `plan`, `patches` (list; first = initial, rest = repairs),
    and optional `fail_on` (one of analyze|plan|patch) to simulate a provider failure.
    Malformed script entries raise ProviderError exactly like invalid real model output."""

    name: str = "fake"
    model: str | None = None

    def __init__(self, script: dict[str, Any]):
        self.script = script
        self.usage = Usage()
        self._patch_index = 0
        self.seen_contexts: list[ModelContext] = []

    @classmethod
    def from_file(cls, path: str | Path) -> FakeProvider:
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            raise ProviderUnavailable(f"cannot load fake script {path}: {e}") from e
        return cls(data)

    def _maybe_fail(self, step: str) -> None:
        self.usage.calls += 1
        if self.script.get("fail_on") == step:
            raise ProviderError(f"simulated provider failure during {step}")

    def _parse(self, model: type, key: str, raw: Any):  # noqa: ANN205
        if raw is None:
            raise ProviderError(f"fake script has no '{key}' response")
        try:
            return model.model_validate(raw)
        except ValidationError as e:
            raise ProviderError(f"invalid structured output for {key}: {e.error_count()} error(s)") from e

    def analyze_issue(self, ctx: ModelContext) -> IssueAnalysis:
        self.seen_contexts.append(ctx)
        self._maybe_fail("analyze")
        return self._parse(IssueAnalysis, "analysis", self.script.get("analysis"))

    def plan_fix(self, ctx: ModelContext, analysis: IssueAnalysis) -> FixPlan:
        self._maybe_fail("plan")
        return self._parse(FixPlan, "plan", self.script.get("plan"))

    def _next_patch(self) -> PatchProposal:
        self._maybe_fail("patch")
        patches = self.script.get("patches") or []
        if self._patch_index >= len(patches):
            raise ProviderError("fake script has no further patch responses")
        raw = patches[self._patch_index]
        self._patch_index += 1
        return self._parse(PatchProposal, f"patches[{self._patch_index - 1}]", raw)

    def propose_patch(self, ctx: ModelContext, analysis: IssueAnalysis, plan: FixPlan) -> PatchProposal:
        return self._next_patch()

    def repair_patch(
        self, ctx: ModelContext, analysis: IssueAnalysis, plan: FixPlan, previous: PatchProposal, failures: str
    ) -> PatchProposal:
        return self._next_patch()
