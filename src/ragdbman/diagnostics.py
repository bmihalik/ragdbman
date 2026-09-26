# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Per-extraction dependency log summaries, isolated across async tasks."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar

QUIET_DEPENDENCIES = ("pypdf", "pymupdf")
_counts: ContextVar[list[int] | None] = ContextVar("dependency_log_counts", default=None)


def is_quiet_target(name: str) -> bool:
    return any(name == target or name.startswith(target + ".") for target in QUIET_DEPENDENCIES)


class DependencySummary(logging.Filter):
    def filter(self, record):
        counts = _counts.get()
        if counts is not None and is_quiet_target(record.name) and record.levelno >= logging.WARNING:
            counts[1 if record.levelno >= logging.ERROR else 0] += 1
            return False
        return True


def configure_logging(level: str = "info"):
    logging.basicConfig(
        level={"TRACE": logging.DEBUG, "WARN": logging.WARNING}.get(level.upper(), level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, DependencySummary) for f in handler.filters):
            handler.addFilter(DependencySummary())
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@contextmanager
def dependency_counts():
    counts = [0, 0]
    token = _counts.set(counts)
    try:
        yield counts
    finally:
        _counts.reset(token)
