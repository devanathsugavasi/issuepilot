"""Versioned, validated configuration.

Precedence (highest first): CLI flags > config file (`--config`, else `<repo>/issuepilot.yaml`)
> built-in defaults. Environment variables are used only for provider credentials, which are
never read from config files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from issuepilot.errors import ConfigError

CONFIG_FILENAME = "issuepilot.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfig(_Strict):
    provider: Literal["anthropic", "fake"] = "anthropic"
    model: str | None = None
    fake_script: str | None = Field(
        default=None, description="Path to a scripted-response file for the deterministic fake provider."
    )
    max_repair_attempts: int = Field(default=2, ge=0, le=5)
    request_timeout_s: float = Field(default=300.0, gt=0, le=3600)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_tokens: int = Field(default=16000, ge=1024, le=64000)
    max_context_files: int = Field(default=12, ge=1, le=100)
    max_context_bytes: int = Field(default=150_000, ge=1_000, le=2_000_000)


class ExecutionConfig(_Strict):
    sandbox: Literal["docker", "host"] = "docker"
    docker_image: str = "python:3.12-slim"
    # Only "disabled" is supported; the Docker backend enforces it with --network none.
    network: Literal["disabled"] = "disabled"
    timeout_seconds: int = Field(default=600, ge=1, le=7200)
    max_memory_mb: int = Field(default=2048, ge=128, le=65536)
    max_cpus: float = Field(default=2.0, gt=0, le=64)
    max_pids: int = Field(default=256, ge=16, le=8192)


class CheckConfig(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,40}$")
    kind: Literal["test", "lint", "typecheck", "build"]
    command: str = Field(min_length=1)


class VerificationConfig(_Strict):
    checks: list[CheckConfig] = Field(default_factory=list)
    max_output_chars: int = Field(default=8000, ge=500, le=200_000)


class SecurityConfig(_Strict):
    builtin_secrets: bool = True
    gitleaks: bool = False
    semgrep: bool = False
    semgrep_config: str = "p/default"
    require_scanners: bool = False


class PatchPolicy(_Strict):
    max_files: int = Field(default=20, ge=1, le=200)
    max_file_bytes: int = Field(default=1_000_000, ge=1_000, le=20_000_000)
    protected_paths: list[str] = Field(
        default_factory=lambda: [
            ".git/**",
            ".issuepilot/**",
            ".github/workflows/**",
            CONFIG_FILENAME,
        ]
    )


class PermissionsConfig(_Strict):
    # Consequential actions are not implemented in v0.1; `true` is rejected rather than ignored.
    modify_current_branch: Literal[False] = False
    auto_commit: Literal[False] = False
    auto_push: Literal[False] = False
    auto_merge: Literal[False] = False


class Config(_Strict):
    version: Literal[1] = 1
    model: ModelConfig = Field(default_factory=ModelConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    patch: PatchPolicy = Field(default_factory=PatchPolicy)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    report_dir: str = ".issuepilot/runs"

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


def load_config(repo: Path, config_path: Path | None = None) -> tuple[Config, Path | None]:
    """Return the validated config and the file it came from (None = defaults)."""
    path = config_path or (repo / CONFIG_FILENAME)
    if not path.exists():
        if config_path is not None:
            raise ConfigError(f"config file not found: {config_path}")
        return Config(), None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    try:
        cfg = Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"{path}: invalid configuration\n{e}") from e
    if cfg.model.fake_script and not Path(cfg.model.fake_script).is_absolute():
        cfg.model.fake_script = str((path.parent / cfg.model.fake_script).resolve())
    return cfg, path


STARTER_CONFIG = """\
# IssuePilot configuration — see docs/CONFIGURATION.md
version: 1

model:
  provider: anthropic          # anthropic | fake
  model: claude-opus-5-5       # any model id your account can use
  max_repair_attempts: 2

execution:
  sandbox: docker              # docker (isolated) | host (requires --trust-repo; NOT isolated)
  docker_image: python:3.12-slim   # never pulled automatically: run `docker pull` yourself
  network: disabled
  timeout_seconds: 600
  max_memory_mb: 2048
  max_cpus: 2

verification:
  checks:
    - id: tests
      kind: test
      command: python3 -m unittest discover -s tests -q

security:
  builtin_secrets: true
  gitleaks: false
  semgrep: false

permissions:
  modify_current_branch: false
  auto_commit: false
  auto_push: false
  auto_merge: false
"""
