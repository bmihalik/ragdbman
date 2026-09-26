# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Incremental scan primitives; sidecars are always excluded."""

import hashlib
import os
from pathlib import Path

from .config import GlobalConfig


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def classify(existing: dict | None, digest: str, supported: bool) -> str:
    if not supported:
        return "unsupported"
    if not existing:
        return "new"
    if existing["status"] == "failed":
        return "previously_failed"
    if existing["status"] == "indexed" and existing["content_hash_sha256"] == digest:
        return "unchanged"
    return "changed"


def discover(root: Path, cfg: GlobalConfig, recursive: bool = True):
    seen_dirs = set()
    for directory, dirs, names in os.walk(root, followlinks=cfg.defaults.follow_symlinks):
        current = Path(directory)
        real = current.resolve()
        if real in seen_dirs:
            dirs[:] = []
            continue
        seen_dirs.add(real)
        dirs[:] = sorted(
            d
            for d in dirs
            if d != cfg.storage.markdown_sidecar_dir_name
            and (cfg.defaults.index_hidden_files or not d.startswith("."))
            and (cfg.defaults.follow_symlinks or not (current / d).is_symlink())
        )
        for name in sorted(names):
            path = current / name
            if name.startswith(".") and not cfg.defaults.index_hidden_files:
                continue
            if path.is_symlink() and not cfg.defaults.follow_symlinks:
                continue
            if path.is_file():
                yield path
        if not recursive:
            dirs[:] = []
