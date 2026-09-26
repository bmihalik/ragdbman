# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""uv-friendly command-line interface for setup and service management."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import tomli_w
import uvicorn

from . import __version__
from .chunking import fetch_tokenizer, tokenizer_path
from .config import GlobalConfig
from .diagnostics import configure_logging
from .errors import RagError

MEDIA_HINTS = """
# Optional programs: disabled until explicitly configured.
# libreoffice_path = "/usr/bin/soffice"
# tesseract_path = "/usr/bin/tesseract"
# whisper_command = "/usr/local/bin/whisper-cli"
# whisper_model_path = "/path/to/ggml-model.bin"
# marker_command = "/usr/local/bin/marker_single"
# mineru_command = "mineru"
# mineru_extra_args = ["-b", "pipeline"]
# scratch_dir = "/path/to/shared/scratch"
"""


def init_config(path: Path):
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = tomli_w.dumps(GlobalConfig().model_dump(exclude_none=True))
    text = text.replace("[media]\n", "[media]\n" + MEDIA_HINTS + "\n")
    try:
        with path.open("x") as stream:
            stream.write(text)
    except FileExistsError as exc:
        raise RagError("CONFIG_INVALID", f"{path} already exists; refusing to overwrite") from exc
    print(f"Wrote {path}. Set storage.allowed_source_roots before scanning.")


def parser():
    result = argparse.ArgumentParser(
        prog="ragdbman", description="Local document intelligence and MCP server"
    )
    result.add_argument("--version", action="version", version=f"ragdbman {__version__}")
    sub = result.add_subparsers(dest="command", required=True)
    for command in ("serve", "init", "registry-repair", "fetch-tokenizer"):
        item = sub.add_parser(command)
        item.add_argument("--config", default="~/.config/ragdbman/config.toml")
        if command == "fetch-tokenizer":
            item.add_argument("--hf-repo", required=True)
            item.add_argument("--model")
            item.add_argument("--revision", default="main")
            item.add_argument("--hub-base-url", default="https://huggingface.co")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            init_config(Path(args.config))
            return
        config = GlobalConfig.load(args.config)
        level = os.environ.get("RAGDBMAN_LOG", config.logging.level).upper()
        configure_logging(level)
        if args.command == "fetch-tokenizer":
            dest = tokenizer_path(config.storage.data_dir, args.model or config.ollama.embedding_model)
            asyncio.run(fetch_tokenizer(args.hub_base_url, args.hf_repo, args.revision, dest))
            print(f"Saved tokenizer to {dest}")
            return
        if config.server.web_auth_mode != "local" and not os.environ.get("RAGDBMAN_AUTH_TOKEN"):
            raise RagError(
                "CONFIG_INVALID", "Set RAGDBMAN_AUTH_TOKEN before enabling authenticated server access"
            )
        from .engine import Engine

        engine = Engine(config)
        if args.command == "registry-repair":
            print(f"Registry repaired: {len(engine.list_collections())} collection(s)")
            asyncio.run(engine.close())
        else:
            from .web import create_app

            uvicorn.run(
                create_app(engine),
                host=config.server.bind,
                port=config.server.port,
                log_level="debug" if level == "TRACE" else config.logging.level.replace("warn", "warning"),
                proxy_headers=False,
            )
    except (RagError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
