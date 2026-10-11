"""Execution boundary tests. Host tests run everywhere; Docker tests need a daemon + image."""

import os
import time
from pathlib import Path

import pytest

from issuepilot.config import ExecutionConfig
from issuepilot.sandbox import DockerSandbox, HostSandbox
from tests.conftest import requires_docker


def test_host_requires_explicit_trust(tmp_path):
    ok, reason = HostSandbox(ExecutionConfig(sandbox="host"), trusted=False).availability()
    assert not ok and "--trust-repo" in reason


def test_host_scrubs_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLOUD_SECRET_TOKEN", "do-not-leak-0000")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKEFAKEFAKEFAKE")
    res = HostSandbox(ExecutionConfig(sandbox="host"), trusted=True).run(tmp_path, "env", 10)
    assert res.exit_code == 0
    assert "do-not-leak-0000" not in res.output and "AKIAFAKE" not in res.output
    assert f"HOME={Path.home()}" not in res.output


def test_host_timeout_kills_process_group(tmp_path):
    marker = tmp_path / "survived"
    t0 = time.monotonic()
    res = HostSandbox(ExecutionConfig(sandbox="host"), trusted=True).run(
        tmp_path, f"(sleep 3; touch {marker}) & sleep 30", 1
    )
    assert res.timed_out and time.monotonic() - t0 < 10
    time.sleep(3.5)
    assert not marker.exists(), "background child must be killed with the process group"


def test_docker_argv_enforces_policy(tmp_path):
    argv = DockerSandbox(ExecutionConfig()).argv(tmp_path, "true", "n")
    joined = " ".join(argv)
    for flag in (
        "--network none",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--read-only",
        "--pull never",
        "--pids-limit",
        "--memory",
        "--cpus",
    ):
        assert flag in joined
    assert "--privileged" not in joined and "docker.sock" not in joined
    assert str(Path.home()) not in joined or str(tmp_path).startswith(str(Path.home()))
    assert argv[argv.index("--user") + 1].split(":")[0] != "0"
    mounts = [a for a in argv if a.startswith("type=bind")]
    assert mounts == [f"type=bind,source={tmp_path},target=/workspace"]


@requires_docker
@pytest.mark.docker
class TestDockerIsolation:
    sb = DockerSandbox(ExecutionConfig())

    def test_network_is_disabled(self, tmp_path):
        res = self.sb.run(tmp_path, "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), 3)\"", 30)
        assert res.exit_code != 0

    def test_non_root_and_read_only_root(self, tmp_path):
        res = self.sb.run(tmp_path, "id -u; touch /etc/x 2>&1; echo rc=$?", 30)
        assert res.output.splitlines()[0] != "0" and "rc=0" not in res.output

    def test_host_env_and_files_not_visible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FAKE_CLOUD_SECRET_TOKEN", "do-not-leak-0000")
        res = self.sb.run(tmp_path, f"env; ls {Path.home()} 2>&1; ls /var/run/docker.sock 2>&1", 30)
        assert "do-not-leak-0000" not in res.output
        assert "No such file" in res.output

    def test_cannot_modify_original_repo(self, tmp_path, idor_repo):
        ws = tmp_path / "ws"
        ws.mkdir()
        os.chmod(ws, 0o777)  # noqa: S103 - container runs as a different uid
        self.sb.run(ws, f"echo pwned > {idor_repo}/app/dashboard.py", 30)
        assert "pwned" not in (idor_repo / "app" / "dashboard.py").read_text()

    def test_timeout(self, tmp_path):
        res = self.sb.run(tmp_path, "sleep 60", 2)
        assert res.timed_out
