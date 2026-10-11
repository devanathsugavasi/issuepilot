from pathlib import Path

import pytest

from issuepilot.config import STARTER_CONFIG, Config, load_config
from issuepilot.errors import ConfigError


def test_defaults_are_safe():
    c = Config()
    assert c.execution.sandbox == "docker"
    assert c.execution.network == "disabled"
    assert c.permissions.auto_push is False
    assert c.model.max_repair_attempts == 2


def test_starter_config_is_valid(tmp_path: Path):
    (tmp_path / "issuepilot.yaml").write_text(STARTER_CONFIG)
    cfg, src = load_config(tmp_path)
    assert src == tmp_path / "issuepilot.yaml"
    assert cfg.verification.checks[0].id == "tests"


@pytest.mark.parametrize(
    "body",
    [
        "unknown_key: 1\n",
        "permissions: {auto_merge: true}\n",
        "execution: {network: enabled}\n",
        "model: {max_repair_attempts: 99}\n",
        "version: 2\n",
        "- not a mapping\n",
        "verification: {checks: [{id: 'Bad Id!', kind: test, command: x}]}\n",
    ],
)
def test_invalid_configs_are_rejected(tmp_path: Path, body: str):
    (tmp_path / "issuepilot.yaml").write_text(body)
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_missing_explicit_config_is_error(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_config(tmp_path, tmp_path / "nope.yaml")


def test_fake_script_resolved_relative_to_config(tmp_path: Path):
    (tmp_path / "issuepilot.yaml").write_text("model: {provider: fake, fake_script: s.yaml}\n")
    cfg, _ = load_config(tmp_path)
    assert cfg.model.fake_script == str((tmp_path / "s.yaml").resolve())
