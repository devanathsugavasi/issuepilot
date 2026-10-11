## What and why

## Evidence
- [ ] `uv run pytest -q` passes (paste summary)
- [ ] `uv run ruff check src tests && uv run pyright` pass
- [ ] Eval suite still matches expected statuses

## Safety checklist
- [ ] No change weakens patch validation, sandbox selection, redaction or status derivation —
      or the change includes tests for the new behavior, including an attack case
- [ ] Docs distinguish implemented from planned behavior
