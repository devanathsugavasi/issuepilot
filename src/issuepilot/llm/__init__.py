"""Model-provider protocol and factory. Provider-specific code lives only in this package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from issuepilot.config import ModelConfig
from issuepilot.errors import ProviderUnavailable
from issuepilot.schemas import FixPlan, IssueAnalysis, PatchProposal, Usage


@dataclass
class ModelContext:
    """Bounded, already-redacted context handed to a provider. All fields are untrusted data."""

    issue_text: str
    repo_summary: str
    files: dict[str, str] = field(default_factory=dict)
    instructions: dict[str, str] = field(default_factory=dict)


class ModelProvider(Protocol):
    name: str
    model: str | None
    usage: Usage

    def analyze_issue(self, ctx: ModelContext) -> IssueAnalysis: ...

    def plan_fix(self, ctx: ModelContext, analysis: IssueAnalysis) -> FixPlan: ...

    def propose_patch(self, ctx: ModelContext, analysis: IssueAnalysis, plan: FixPlan) -> PatchProposal: ...

    def repair_patch(
        self,
        ctx: ModelContext,
        analysis: IssueAnalysis,
        plan: FixPlan,
        previous: PatchProposal,
        failures: str,
    ) -> PatchProposal: ...


def get_provider(cfg: ModelConfig) -> ModelProvider:
    if cfg.provider == "fake":
        from issuepilot.llm.fake import FakeProvider

        if not cfg.fake_script:
            raise ProviderUnavailable("model.provider=fake requires model.fake_script")
        return FakeProvider.from_file(cfg.fake_script)
    from issuepilot.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(cfg)


def provider_status(cfg: ModelConfig) -> tuple[bool, str]:
    """Check configuration without making a request or revealing credential values."""
    try:
        p = get_provider(cfg)
    except ProviderUnavailable as e:
        return False, str(e)
    return True, f"{p.name} ({p.model or 'scripted'}) configured"
