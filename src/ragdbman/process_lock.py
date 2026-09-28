# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""CLI/daemon ownership guard. OS locks disappear on exit; lock files stay."""

import os
from pathlib import Path

from .errors import RagError


class DataDirectoryLock:
    def __init__(self, config):
        self.paths = sorted(
            {
                Path(config.storage.data_dir).expanduser().resolve() / ".ragdbman.lock",
                Path(str(Path(config.storage.registry_path).expanduser().resolve()) + ".lock"),
            }
        )
        self.streams = []

    def __enter__(self):
        try:
            for path in self.paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = path.open("a+b")
                try:
                    if os.name == "nt":
                        import msvcrt

                        if path.stat().st_size == 0:
                            stream.write(b"\0")
                            stream.flush()
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    stream.close()
                    raise RagError(
                        "DATA_DIRECTORY_BUSY",
                        "Another CLI/daemon owns this data directory or registry. "
                        "Use --server-url to control a running daemon, or stop the owner first.",
                    ) from exc
                self.streams.append(stream)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        for stream in reversed(self.streams):
            try:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
        self.streams.clear()
