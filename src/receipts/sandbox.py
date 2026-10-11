"""Where untrusted commands actually run.

Two backends:

* DockerSandbox  - the default. No network, no capabilities, read-only root,
                   CPU/memory/pid limits, no secrets. Use this for anything
                   that came from outside your team.
* LocalSandbox   - plain subprocess with a scrubbed environment and a timeout.
                   It is NOT a security boundary. It exists for trusted
                   examples, the benchmark and unit tests, and the CLI makes
                   you opt in with --unsafe-local.
"""

from __future__ import annotations

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

from .policy import Policy

WINDOWS_NOT_FOUND = "is not recognized as an internal or external command"


class SandboxError(RuntimeError):
    """The sandbox could not run (infrastructure problem, not the contributor's fault)."""


@dataclass
class RunResult:
    exit_code: int | None
    timed_out: bool
    output: str
    duration_s: float
    error: str | None = None


class Sandbox(Protocol):
    name: str

    def prepare(self) -> None: ...

    def run(self, workdir: Path, command: str, *, timeout: int, network: bool = False) -> RunResult: ...


def _tail(handle, limit: int) -> str:
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(max(0, size - limit))
    data = handle.read()
    text = data.decode("utf-8", "replace")
    if size > limit:
        text = f"[... {size - limit} earlier bytes truncated ...]\n" + text
    return text


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, check=False, timeout=15)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


class LocalSandbox:
    name = "local"

    def __init__(self, policy: Policy):
        self.policy = policy

    def prepare(self) -> None:
        return None

    @staticmethod
    def scrubbed_env(home: Path) -> dict[str, str]:
        """Only what a command needs to start. No tokens, no credentials."""
        keep = ["PATH", "SYSTEMROOT", "SystemDrive", "COMSPEC", "PATHEXT", "WINDIR"]
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env.update({
            "HOME": str(home), "USERPROFILE": str(home),
            "TEMP": str(home), "TMP": str(home), "TMPDIR": str(home),
            "CI": "true", "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        })
        return env

    def run(self, workdir: Path, command: str, *, timeout: int, network: bool = False) -> RunResult:
        home = Path(tempfile.mkdtemp(prefix="receipts-home-"))
        started = time.monotonic()
        try:
            with tempfile.TemporaryFile() as out:
                options: dict = {}
                if os.name == "nt":
                    options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    options["start_new_session"] = True
                try:
                    proc = subprocess.Popen(
                        command, shell=True, cwd=workdir, env=self.scrubbed_env(home),
                        stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, **options)
                except OSError as exc:
                    return RunResult(None, False, "", 0.0, error=f"could not start command: {exc}")
                timed_out = False
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _kill_tree(proc)
                duration = time.monotonic() - started
                text = _tail(out, self.policy.max_output_bytes)
                code = None if timed_out else proc.returncode
                if os.name == "nt" and code == 1 and WINDOWS_NOT_FOUND in text:
                    code = 127  # mirror POSIX "command not found"
                return RunResult(code, timed_out, text, duration)
        finally:
            shutil.rmtree(home, ignore_errors=True)


class DockerSandbox:
    name = "docker"

    def __init__(self, policy: Policy):
        self.policy = policy
        self._ready = False

    def prepare(self) -> None:
        if self._ready:
            return
        if shutil.which("docker") is None:
            raise SandboxError("docker is not installed or not on PATH")
        probe = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                               capture_output=True, text=True, timeout=60, check=False)
        if probe.returncode != 0:
            raise SandboxError("the docker daemon is not reachable")
        inspect = subprocess.run(["docker", "image", "inspect", self.policy.image],
                                 capture_output=True, check=False, timeout=60)
        if inspect.returncode != 0:
            pull = subprocess.run(["docker", "pull", "--quiet", self.policy.image],
                                  capture_output=True, text=True, timeout=900, check=False)
            if pull.returncode != 0:
                raise SandboxError(f"could not pull image {self.policy.image}")
        self._ready = True

    def argv(self, workdir: Path, command: str, *, name: str, network: bool) -> list[str]:
        """Build the `docker run` command line. Pure, so it can be unit-tested."""
        p = self.policy
        argv = [
            "docker", "run", "--rm", "--name", name,
            "--network", "bridge" if network else "none",
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=128m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(p.pids),
            "--memory", p.memory, "--memory-swap", p.memory, "--cpus", p.cpus,
        ]
        if hasattr(os, "getuid"):
            argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
        argv += [
            "-e", "HOME=/tmp", "-e", "CI=true",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONUNBUFFERED=1",
            "-v", f"{workdir}:/work", "-w", "/work",
            p.image, "sh", "-c", command,
        ]
        return argv

    def run(self, workdir: Path, command: str, *, timeout: int, network: bool = False) -> RunResult:
        name = f"receipts-{uuid.uuid4().hex[:12]}"
        argv = self.argv(workdir, command, name=name, network=network)
        started = time.monotonic()
        with tempfile.TemporaryFile() as out:
            try:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out,
                                        stderr=subprocess.STDOUT)
            except OSError as exc:
                return RunResult(None, False, "", 0.0, error=f"could not start docker: {exc}")
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(["docker", "kill", name], capture_output=True, check=False, timeout=30)
                _kill_tree(proc)
            duration = time.monotonic() - started
            text = _tail(out, self.policy.max_output_bytes)
            code = None if timed_out else proc.returncode
            return RunResult(code, timed_out, text, duration)


def make_sandbox(name: str, policy: Policy) -> Sandbox:
    if name == "docker":
        return DockerSandbox(policy)
    if name == "local":
        return LocalSandbox(policy)
    raise SandboxError(f"unknown sandbox {name!r}")
