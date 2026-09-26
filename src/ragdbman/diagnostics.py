# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Per-extraction dependency log summaries, isolated across async tasks."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar

QUIET_DEPENDENCIES = ("pypdf", "pymupdf")
TRACE = 5
VERBOSE = 15
logging.addLevelName(TRACE, "TRACE")
logging.addLevelName(VERBOSE, "VERBOSE")
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
    numeric = {"TRACE": TRACE, "VERBOSE": VERBOSE, "WARN": logging.WARNING}.get(
        level.upper(), getattr(logging, level.upper(), None)
    )
    if not isinstance(numeric, int):
        raise ValueError(f"Unknown log level: {level}")
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s",
    )
    root = logging.getLogger()
    root.setLevel(numeric)  # basicConfig is a no-op when a host already installed handlers.
    logging.getLogger("ragdbman").setLevel(numeric)
    for handler in root.handlers:
        handler.setLevel(numeric)
        if not any(isinstance(f, DependencySummary) for f in handler.filters):
            handler.addFilter(DependencySummary())
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # SDK DEBUG can include tool arguments; application TRACE is not HTTP/body tracing.
    logging.getLogger("mcp").setLevel(logging.INFO)
    logging.getLogger(__name__).debug(
        "Application logging configured level=%s", logging.getLevelName(numeric)
    )


@contextmanager
def dependency_counts():
    counts = [0, 0]
    token = _counts.set(counts)
    try:
        yield counts
    finally:
        _counts.reset(token)
