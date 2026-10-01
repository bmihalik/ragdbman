# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""uv-friendly command-line interface for setup and service management."""

import argparse
import asyncio
import json
import logging
import os
import sys
import textwrap
from pathlib import Path

import tomli_w
import uvicorn

from . import __version__
from .chunking import fetch_tokenizer, tokenizer_path
from .cli_commands import COMMANDS, arguments, contract, emit, exit_status, local, remote
from .cli_help import COMMAND_HELP, OPTION_HELP, complete_help, epilog
from .cli_signals import Interrupted, LocalSignals
from .config import GlobalConfig
from .diagnostics import configure_logging
from .errors import RagError
from .process_lock import DataDirectoryLock

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


class HelpFormatter(argparse.HelpFormatter):
    """Wrap prose while preserving deliberate paragraph and example line breaks."""

    def _fill_text(self, text, width, indent):
        lines = []
        for line in text.splitlines():
            if not line:
                lines.append("")
                continue
            # Keep shell examples copyable as one command, even on narrow terminals.
            if line.lstrip().startswith("ragdbman "):
                lines.append(indent + line)
                continue
            leading = line[: len(line) - len(line.lstrip())]
            prefix = indent + leading
            lines.append(textwrap.fill(line.strip(), width, initial_indent=prefix, subsequent_indent=prefix))
        return "\n".join(lines)


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
        prog="ragdbman",
        allow_abbrev=False,
        description="Index and query local documents, source code and Knowledge Cards; "
        "serve a web UI, REST API and MCP tools.",
        formatter_class=HelpFormatter,
        epilog="Getting started:\n"
        "  ragdbman init                    Write a new TOML configuration.\n"
        "  ragdbman serve                   Start the configured daemon and web UI.\n"
        "  ragdbman COMMAND --help          Explain one command and all its options.\n\n"
        "Service commands run directly against local storage unless --server-url is given.\n"
        "Do not open the same storage while a daemon owns it; use its REST URL instead.\n"
        "See docs/CLI.md for workflows, authentication, output formats and exit statuses.",
    )
    result.add_argument("--version", action="version", version=f"ragdbman {__version__}")
    result.add_argument("--config", default="~/.config/ragdbman/config.toml", help=OPTION_HELP["config"])
    levels = ["trace", "debug", "verbose", "info", "warning", "warn", "error", "critical"]
    result.add_argument("--log-level", choices=levels, help=OPTION_HELP["log_level"])
    sub = result.add_subparsers(dest="command", required=True, title="commands", metavar="COMMAND")
    for command in ("serve", "init", "fetch-tokenizer", *COMMANDS):
        summary, details, _ = COMMAND_HELP[command]
        item = sub.add_parser(
            command,
            allow_abbrev=False,
            help=summary,
            description=f"{summary}\n\n{details}",
            formatter_class=HelpFormatter,
            epilog=epilog(command, command in COMMANDS),
        )
        item.add_argument("--config", default=argparse.SUPPRESS)
        item.add_argument(
            "--log-level",
            choices=levels,
            default=argparse.SUPPRESS,
        )
        if command in COMMANDS:
            arguments(item, command)
        if command == "fetch-tokenizer":
            item.add_argument("--hf-repo", required=True)
            item.add_argument("--model")
            item.add_argument("--revision", default="main")
            item.add_argument("--hub-base-url", default="https://huggingface.co")
        complete_help(item, command)
    return result


async def run_local(config, args, method=None, kwargs=None):
    from .engine import Engine

    engine = Engine(config)
    with LocalSignals(engine):
        try:
            return await local(engine, args, method, kwargs)
        finally:
            await engine.close()


def serve(config, level):
    from .engine import Engine
    from .server import ManagedServer
    from .web import create_app

    engine = Engine(config)
    try:
        server = ManagedServer(
            uvicorn.Config(
                create_app(engine),
                host=config.server.bind,
                port=config.server.port,
                log_level="debug"
                if level in {"TRACE", "DEBUG"}
                else "info"
                if level in {"VERBOSE", "INFO"}
                else "warning"
                if level == "WARN"
                else level.lower(),
                log_config=None,
                timeout_graceful_shutdown=config.server.shutdown_grace_seconds,
                proxy_headers=False,
            ),
            engine,
        )
        server.run()
    finally:
        if not engine.closed:
            asyncio.run(engine.close())


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            init_config(Path(args.config))
            return
        config = GlobalConfig.load(args.config)
        level = (args.log_level or os.environ.get("RAGDBMAN_LOG", config.logging.level)).upper()
        configure_logging(level)
        if args.command in COMMANDS:
            method, kwargs = contract(
                args
            )  # Validate/confirm before opening databases or contacting a daemon.
            if args.server_url is not None:
                payload = asyncio.run(remote(args, kwargs))
            else:
                with DataDirectoryLock(config):
                    payload = asyncio.run(run_local(config, args, method, kwargs))
            emit(args, payload, snapshot=args.command == "scan-job-get" and args.watch)
            status = exit_status(args, payload)
            if status:
                raise SystemExit(status)
            return
        if args.command == "fetch-tokenizer":
            dest = tokenizer_path(config.storage.data_dir, args.model or config.ollama.embedding_model)
            asyncio.run(fetch_tokenizer(args.hub_base_url, args.hf_repo, args.revision, dest))
            print(f"Saved tokenizer to {dest}")
            return
        if (
            args.command == "serve"
            and config.server.web_auth_mode != "local"
            and not os.environ.get("RAGDBMAN_AUTH_TOKEN")
        ):
            raise RagError(
                "CONFIG_INVALID", "Set RAGDBMAN_AUTH_TOKEN before enabling authenticated server access"
            )
        with DataDirectoryLock(config):
            serve(config, level)
    except Interrupted as exc:
        print(
            json.dumps(
                {"code": "JOB_CANCELLED", "message": "Foreground operation interrupted; cleanup completed"}
            ),
            file=sys.stderr,
        )
        raise SystemExit(exc.exit_code) from None
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Console shutdown complete")
        if args.command != "serve":
            raise SystemExit(130) from None
    except BrokenPipeError:
        raise SystemExit(1) from None
    except (RagError, OSError, ValueError) as exc:
        error = (
            exc.as_dict() if isinstance(exc, RagError) else {"code": "CONFIG_INVALID", "message": str(exc)}
        )
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception:
        logging.getLogger(__name__).exception("Unexpected command failure")
        print(
            json.dumps({"code": "INTERNAL", "message": "Unexpected command failure; inspect diagnostics"}),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
