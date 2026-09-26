# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""A persistent collection writer and exclusively leased reusable read connections."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from . import db
from .diagnostics import TRACE

log = logging.getLogger(__name__)


class CollectionDatabase:
    def __init__(self, path):
        self.path = path
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"db-{path.stem}")
        self.lock = threading.Lock()
        self.idle = []
        self.writer = None
        self.writer_ident = None
        self.closed = False

    def write(self, function, *args):
        if self.writer is None:
            self.writer = db.connect(self.path)
            self.writer_ident = threading.get_ident()
        return function(*args)

    @contextmanager
    def connection(self):
        if threading.get_ident() == self.writer_ident:
            yield self.writer
            return
        with self.lock:
            conn = self.idle.pop() if self.idle else None
        if conn is None:
            conn = db.connect(self.path)
        else:
            log.log(TRACE, "Reusing SQLite reader database=%s", self.path.name)
        try:
            yield conn
        finally:
            # No transaction or cursor state may leak into the next lease.
            if conn.in_transaction:
                conn.rollback()
            with self.lock:
                if not self.closed and len(self.idle) < 8:
                    self.idle.append(conn)
                else:
                    conn.close()

    def close(self):
        self.executor.shutdown(wait=True)
        with self.lock:
            self.closed = True
            for conn in self.idle:
                conn.close()
            self.idle.clear()
            if self.writer is not None:
                self.writer.close()
                self.writer = None
                self.writer_ident = None
        log.debug("Closed collection connections database=%s", self.path.name)
