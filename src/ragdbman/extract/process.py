# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Opt-in external tools. No shell expansion; timed process groups and private scratch directories."""

import asyncio
import logging
import os
import shutil
import signal
import tempfile
from pathlib import Path

from ..errors import RagError

log = logging.getLogger(__name__)


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
    program = str(Path(program).expanduser())
    env = {
        k: os.environ[k]
        for k in ("PATH", "HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "SYSTEMROOT", "TEMP", "TMP")
        if k in os.environ
    }
    env["GIO_USE_VFS"] = "local"
    resolved = Path(shutil.which(program) or program).resolve()
    log.debug(
        "External tool: %r %r cwd=%s resolved=%s shebang=%s",
        program,
        args,
        cwd,
        resolved,
        detect_shebang(resolved),
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            program,
            *map(str, args),
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        raise RagError("EXTRACTION_FAILED", f"Cannot execute {program}: {exc}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if proc.returncode is None:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
        await proc.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise RagError("EXTRACTION_FAILED", f"{program} timed out after {timeout:g}s") from exc
    log.debug(
        "Tool exit=%s stdout=%s stderr=%s",
        proc.returncode,
        stdout[-8000:].decode(errors="replace"),
        stderr[-8000:].decode(errors="replace"),
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
