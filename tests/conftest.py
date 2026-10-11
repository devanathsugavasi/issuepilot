from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from issuepilot.config import Config
from issuepilot.llm.fake import FakeProvider
from issuepilot.sandbox import DockerSandbox, HostSandbox

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def make_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return path


@pytest.fixture
def idor_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(CASES / "idor-dashboard" / "fixture", repo)
    return make_repo(repo, {})


@pytest.fixture
def idor_script() -> dict:
    import yaml

    return yaml.safe_load((CASES / "idor-dashboard" / "fake.yaml").read_text())


def config(**overrides) -> Config:
    raw = {
        "model": {"provider": "fake", "fake_script": "unused"},
        "execution": {"sandbox": "host", "timeout_seconds": 60},
        "verification": {
            "checks": [{"id": "tests", "kind": "test", "command": "python3 -m unittest discover -s tests -q"}]
        },
    }
    for k, v in overrides.items():
        raw[k] = {**raw.get(k, {}), **v} if isinstance(v, dict) else v
    return Config.model_validate(raw)


def host(cfg: Config) -> HostSandbox:
    return HostSandbox(cfg.execution, trusted=True)


def fake(script: dict) -> FakeProvider:
    return FakeProvider(script)


def docker_ready() -> bool:
    return DockerSandbox(Config().execution).availability()[0]


requires_docker = pytest.mark.skipif(not docker_ready(), reason="Docker daemon or image unavailable")
