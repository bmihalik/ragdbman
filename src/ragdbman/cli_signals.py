# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Bounded Ctrl+C/SIGTERM cleanup for foreground CLI operations."""

import asyncio
import os
import signal
import threading

from .extract.process import terminate_all


class Interrupted(KeyboardInterrupt):
    def __init__(self, signum):
        self.exit_code = 128 + int(signum)


class LocalSignals:
    def __init__(self, engine):
        self.engine = engine
        self.previous = {}
        self.timer = None
        self.signum = None

    def __enter__(self):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                self.previous[sig] = signal.signal(sig, self.handle)
        return self

    def force(self):
        terminate_all()
        os._exit(128 + int(self.signum))

    def handle(self, signum, frame):
        if self.signum is not None:
            self.force()
        self.signum = signum
        self.engine.request_shutdown()
        self.loop.call_soon_threadsafe(self.task.cancel)
        self.timer = threading.Timer(self.engine.config.server.shutdown_timeout_seconds, self.force)
        self.timer.daemon = True
        self.timer.start()

    def __exit__(self, typ, value, traceback):
        for sig, previous in self.previous.items():
            signal.signal(sig, previous)
        if self.timer:
            self.timer.cancel()
        if typ is asyncio.CancelledError and self.signum:
            raise Interrupted(self.signum) from None
