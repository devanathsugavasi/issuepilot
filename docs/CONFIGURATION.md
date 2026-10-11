# Configuration

Precedence: CLI flags > config file (`--config PATH`, else `<repo>/issuepilot.yaml`) > defaults.
Unknown keys and unsupported values are **rejected** at startup. Credentials come only from the
environment (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile).

```yaml
version: 1                    # required to be 1

model:
  provider: anthropic         # anthropic | fake
  model: claude-opus-5-5      # required for anthropic; any model id your account can use
  fake_script: null           # fake provider only; path relative to the config file
  max_repair_attempts: 2      # 0–5, repairs after the initial patch
  request_timeout_s: 300
  max_retries: 2              # SDK retries for 408/409/429/5xx
  max_tokens: 16000
  max_context_files: 12
  max_context_bytes: 150000

execution:
  sandbox: docker             # docker | host (host also needs --trust-repo)
  docker_image: python:3.12-slim   # must exist locally; never pulled automatically
  network: disabled           # only supported value; enforced by Docker backend
  timeout_seconds: 600        # per check
  max_memory_mb: 2048
  max_cpus: 2
  max_pids: 256

verification:
  checks:                     # run at baseline, reproduction (tests only) and candidate
    - {id: tests, kind: test, command: "python3 -m pytest -q"}   # kind: test|lint|typecheck|build
  max_output_chars: 8000

security:
  builtin_secrets: true
  gitleaks: false             # requires gitleaks on PATH
  semgrep: false              # requires semgrep on PATH
  semgrep_config: p/default   # note: registry configs are downloaded by semgrep
  require_scanners: false     # true: a missing enabled scanner blocks VERIFIED

patch:
  max_files: 20
  max_file_bytes: 1000000
  protected_paths: [".git/**", ".issuepilot/**", ".github/workflows/**", "issuepilot.yaml"]

permissions:                  # all must be false; true is rejected (not implemented)
  modify_current_branch: false
  auto_commit: false
  auto_push: false
  auto_merge: false

report_dir: .issuepilot/runs
```

Credential-like files (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `.netrc`, `.npmrc`, `.pypirc`,
`*credentials*`, …) can never be edited and are never sent to the model, regardless of config.
