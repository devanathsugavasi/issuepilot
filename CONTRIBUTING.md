# Contributing to IssuePilot

Thanks for helping. IssuePilot's value is trustworthy evidence, so changes are judged first on
whether they keep reports honest and the execution boundary intact.

## Setup

```bash
git clone https://github.com/devanathsugavasi/issuepilot && cd issuepilot
uv sync
uv run pytest -q
```

Before opening a PR run `uv run ruff check src tests`, `uv run ruff format --check src tests`,
`uv run pyright`, `uv run pytest -q` and the eval suite (see AGENTS.md).

## Ground rules

- Every change to patch validation, sandboxing, redaction or status derivation needs tests,
  including a negative (attack) case where relevant.
- No test may require network access, paid model access or real secrets. Use harmless fixtures.
- Document limitations alongside features. Never describe planned work as available.

## Adding a model provider

1. Implement the `ModelProvider` protocol (`src/issuepilot/llm/__init__.py`) in a new module
   under `llm/`; return the Pydantic models from `schemas.py` and raise `ProviderError` /
   `ProviderUnavailable` (never provider-specific exceptions).
2. Wrap all repository and issue content as untrusted (see `render_context`) and give the model
   no tools that execute code.
3. Register it in `get_provider` and the `ModelConfig.provider` literal; add an optional
   dependency extra.
4. Add tests with a mocked client covering success, refusal/truncation, timeouts and errors.

## Adding a security scanner

Add an adapter in `security/scanners.py` that (a) reports `ran=False` with a reason when the tool
is missing, (b) normalizes output to `Finding` with `status=scanner_reported`, (c) never stores raw
secret values. Add normalization tests using recorded sample output.

## Adding an eval case

See [evals/README.md](evals/README.md). Cases must be deterministic and self-contained.
