# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Opt-in external tools. No shell expansion; timed process groups and private scratch directories."""

import asyncio
import logging
import os
import shutil
import signal
import tempfile
import threading
import time
from pathlib import Path

from ..errors import RagError

log = logging.getLogger(__name__)
_groups = set()
_groups_lock = threading.RLock()


def terminate_group(pid):
    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def terminate_all():
    with _groups_lock:
        for pid in tuple(_groups):
            terminate_group(pid)
    log.debug("External process-group termination requested")


def detect_shebang(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            head = stream.read(256)
        return head.split(b"\n", 1)[0].decode(errors="replace").rstrip() if head.startswith(b"#!") else None
    except OSError:
        return None


def scratch(parent: str | None = None):
    if parent:
        Path(parent).expanduser().mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(
        prefix="ragdbman-", dir=str(Path(parent).expanduser()) if parent else None
    )


async def run(program: str, args: list[str], timeout: float = 600, cwd: Path | None = None) -> str:
    started = time.monotonic()
    program = str(Path(program).expanduser())
    env = {
        k: os.environ[k]
        for k in ("PATH", "HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "SYSTEMROOT", "TEMP", "TMP")
        if k in os.environ
    }
    env["GIO_USE_VFS"] = "local"
    resolved = Path(shutil.which(program) or program).resolve()
    log.debug(
        "External tool: %r arguments=%d cwd=%s resolved=%s shebang=%s",
        program,
        len(args),
        cwd,
        resolved,
        detect_shebang(resolved),
    )
    try:

        async def spawn():
            process = await asyncio.create_subprocess_exec(
                program,
                *map(str, args),
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                start_new_session=os.name == "posix",
            )
            with _groups_lock:
                _groups.add(process.pid)
            return process

        spawning = asyncio.create_task(spawn())
        try:
            proc = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            from ..workers import _drain

            await _drain(spawning)
            if not spawning.cancelled() and spawning.exception() is None:
                orphan = spawning.result()
                terminate_group(orphan.pid)
                await orphan.communicate()
                with _groups_lock:
                    _groups.discard(orphan.pid)
            raise
    except OSError as exc:
        raise RagError("EXTRACTION_FAILED", f"Cannot execute {program}: {exc}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        # A exited parent can leave grandchildren holding stdout/stderr open.
        # Kill the process group even when the parent's returncode is already set.
        terminate_group(proc.pid)
        from ..workers import _drain

        await _drain(asyncio.create_task(proc.communicate()))
        log.warning(
            "External tool interrupted program=%s pid=%d reason=%s elapsed=%.3fs",
            program,
            proc.pid,
            type(exc).__name__,
            time.monotonic() - started,
        )
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise RagError("EXTRACTION_FAILED", f"{program} timed out after {timeout:g}s") from exc
    finally:
        with _groups_lock:
            _groups.discard(proc.pid)
    log.debug(
        "Tool program=%s pid=%d exit=%s stdout_bytes=%d stderr_bytes=%d elapsed=%.3fs",
        program,
        proc.pid,
        proc.returncode,
        len(stdout),
        len(stderr),
        time.monotonic() - started,
    )
    if proc.returncode:
        detail = []
        if stdout.strip():
            detail.append("stdout: " + stdout[-4000:].decode(errors="replace"))
        if stderr.strip():
            detail.append("stderr: " + stderr[-4000:].decode(errors="replace"))
        message = " | ".join(detail) or "the process produced no output on stdout or stderr"
        code = f"signal {-proc.returncode}" if proc.returncode < 0 else str(proc.returncode)
        raise RagError("EXTRACTION_FAILED", f"{program} exited {code}: {message}")
    return stdout.decode("utf-8", errors="replace")
