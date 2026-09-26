# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Stop work at the first console signal, before Uvicorn drains open streams."""

import logging
import os
import threading

import uvicorn

from .extract.process import terminate_all

log = logging.getLogger(__name__)


class ManagedServer(uvicorn.Server):
    def __init__(self, config, engine):
        super().__init__(config)
        self.engine = engine
        self.watchdog = None

    def force_stop(self, sig, repeated=False):
        reason = "Repeated termination signal" if repeated else "Shutdown deadline reached"
        log.critical(
            "%s; terminating owned converters and exiting. "
            "Uncommitted SQLite work is rolled back on restart.",
            reason,
        )
        terminate_all()
        os._exit(128 + int(sig))

    def handle_exit(self, sig, frame):
        if self.watchdog is None:
            log.warning("Received signal=%s; stopping active work before HTTP drain", sig)
            self.engine.request_shutdown()
            self.watchdog = threading.Timer(
                self.engine.config.server.shutdown_timeout_seconds, self.force_stop, args=(sig,)
            )
            self.watchdog.daemon = True
            self.watchdog.start()
        elif self.should_exit:
            self.force_stop(sig, repeated=True)
        super().handle_exit(sig, frame)

    def run(self, sockets=None):
        try:
            return super().run(sockets=sockets)
        finally:
            if self.watchdog is not None:
                self.watchdog.cancel()
