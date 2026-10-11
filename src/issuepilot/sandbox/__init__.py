"""Restricted execution of repository commands.

Repository commands (tests, linters, build scripts) are untrusted. They run only through a
`Sandbox`. If no sandbox is available, callers must fail closed: record the check as SKIPPED
and never fall back to running on the host.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from issuepilot.config import ExecutionConfig


@dataclass
class ExecResult:
    exit_code: int | None
    output: str
    timed_out: bool
    duration_s: float
    error: str | None = None


class Sandbox(Protocol):
    name: str
    isolated: bool

    def availability(self) -> tuple[bool, str]: ...

    def run(self, workspace: Path, command: str, timeout: int) -> ExecResult: ...

    def limitations(self) -> list[str]: ...


def _text(out: bytes | str | None) -> str:
    if isinstance(out, str):
        return out
    return (out or b"").decode("utf-8", "replace")


def _run_capturing(argv: list[str], timeout: int, on_timeout, **kwargs) -> ExecResult:  # noqa: ANN001
    start = time.monotonic()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, **kwargs)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return ExecResult(proc.returncode, _text(out), False, time.monotonic() - start)
    except subprocess.TimeoutExpired:
        on_timeout(proc)
        out, _ = proc.communicate()
        return ExecResult(None, _text(out), True, time.monotonic() - start)


class DockerSandbox:
    """Docker backend. Enforced flags: no network, non-root user, all capabilities dropped,
    no-new-privileges, read-only root filesystem, pids/memory/cpu limits, only the
    workspace mounted, no host environment passed, image never pulled implicitly."""

    name = "docker"
    isolated = True

    def __init__(self, cfg: ExecutionConfig):
        self.cfg = cfg

    def availability(self) -> tuple[bool, str]:
        if shutil.which("docker") is None:
            return False, "docker CLI not found on PATH"
        try:
            info = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "docker daemon did not respond"
        if info.returncode != 0:
            return False, "docker daemon not reachable"
        img = subprocess.run(
            ["docker", "image", "inspect", self.cfg.docker_image],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if img.returncode != 0:
            return False, (
                f"image {self.cfg.docker_image!r} not present locally; IssuePilot never pulls "
                f"images itself — run `docker pull {self.cfg.docker_image}` if you trust it"
            )
        return True, f"docker {info.stdout.strip()} with image {self.cfg.docker_image}"

    def argv(self, workspace: Path, command: str, name: str) -> list[str]:
        uid = os.getuid() if hasattr(os, "getuid") else 65534
        user = "65534:65534" if uid == 0 else f"{uid}:{os.getgid()}"
        c = self.cfg
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--pull",
            "never",
            "--network",
            "none",
            "--user",
            user,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",  # noqa: S108 - tmpfs inside the container
            "--pids-limit",
            str(c.max_pids),
            "--memory",
            f"{c.max_memory_mb}m",
            "--memory-swap",
            f"{c.max_memory_mb}m",
            "--cpus",
            str(c.max_cpus),
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--mount",
            f"type=bind,source={workspace},target=/workspace",
            "--workdir",
            "/workspace",
            "--entrypoint",
            "sh",
            c.docker_image,
            "-c",
            command,
        ]

    def run(self, workspace: Path, command: str, timeout: int) -> ExecResult:
        name = f"issuepilot-{uuid.uuid4().hex[:12]}"

        def kill(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=30, check=False)
            proc.kill()

        try:
            return _run_capturing(self.argv(workspace, command, name), timeout, kill)
        except OSError as e:
            return ExecResult(None, "", False, 0.0, error=f"docker failed to start: {e}")

    def limitations(self) -> list[str]:
        return [
            "Docker containers share the host kernel; this is not a complete security boundary "
            "against a determined attacker (see docs/SECURITY_MODEL.md).",
        ]


class HostSandbox:
    """Runs commands directly on the host. NOT isolated. Only enabled when the user both sets
    `execution.sandbox: host` and passes `--trust-repo`. Mitigations only: scrubbed environment,
    private HOME/TMPDIR, process-group kill on timeout."""

    name = "host"
    isolated = False

    def __init__(self, cfg: ExecutionConfig, trusted: bool):
        self.cfg = cfg
        self.trusted = trusted

    def availability(self) -> tuple[bool, str]:
        if not self.trusted:
            return False, "host execution requires --trust-repo (repository code would run unisolated)"
        return True, "host execution (UNISOLATED; user asserted the repository is trusted)"

    def run(self, workspace: Path, command: str, timeout: int) -> ExecResult:
        home = tempfile.mkdtemp(prefix="issuepilot-home-")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "TMPDIR": home,
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        def kill(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)

        try:
            return _run_capturing(["sh", "-c", command], timeout, kill, cwd=workspace, env=env)
        except OSError as e:
            return ExecResult(None, "", False, 0.0, error=f"failed to start: {e}")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def limitations(self) -> list[str]:
        return [
            "Checks ran on the host WITHOUT isolation (--trust-repo): network was not restricted, "
            "and repository code could read files your user can read.",
            "execution.network=disabled and resource limits are NOT enforced by the host backend.",
        ]


def get_sandbox(cfg: ExecutionConfig, trust_repo: bool) -> Sandbox:
    if cfg.sandbox == "docker":
        return DockerSandbox(cfg)
    return HostSandbox(cfg, trusted=trust_repo)
