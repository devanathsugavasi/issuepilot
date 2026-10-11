# Evaluation cases

Each directory under `cases/` is one case:

```
cases/<name>/
├── case.yaml     # metadata, config overrides, expected status
├── issue.md      # issue text given to IssuePilot
├── fake.yaml     # scripted responses for the deterministic fake provider (optional)
└── fixture/      # repository contents (may be shared: `fixture: ../other/fixture`)
```

`case.yaml` (schema_version 1):

```yaml
schema_version: 1
name: idor-dashboard
description: What this case tests.
issue: issue.md            # default
fixture: fixture           # default; relative to the case directory
config:                    # merged into a full IssuePilot config
  model: {provider: fake, fake_script: fake.yaml}
  verification:
    checks:
      - {id: tests, kind: test, command: python3 -m unittest discover -s tests -q}
expected_status: VERIFIED  # VERIFIED | NEEDS_REVIEW | NO_FIX | FAILED
known_limitations: []
```

For every run the fixture is copied to a temp directory and committed as a fresh repository.
Run artifacts are kept under `$TMPDIR/issuepilot-eval-runs/<case>/<run-id>/`.

```bash
uv run issuepilot eval evals/cases                          # Docker sandbox
uv run issuepilot eval evals/cases --sandbox host --trust-repo   # trusted fixtures, no Docker
```

To evaluate a real model, copy a case and replace `model` with your provider settings. Real-model
results vary between runs: repeat trials and report sample sizes.
