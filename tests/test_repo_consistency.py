# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Offline checks for documentation/source drift and self-contained CLI help."""

import argparse
import ast
import inspect
import re
import shlex
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from markdown_it import MarkdownIt

from ragdbman.cli import parser
from ragdbman.cli_commands import COMMANDS, contract, table
from ragdbman.cli_help import COMMAND_HELP
from ragdbman.config import GlobalConfig
from ragdbman.engine import Engine
from ragdbman.errors import STATUS

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted([*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")])


def subcommands():
    return next(a for a in parser()._actions if isinstance(a, argparse._SubParsersAction)).choices


def test_cli_catalog_and_all_option_explanations():
    commands = subcommands()
    assert (
        set(commands)
        == set(COMMAND_HELP)
        == {"serve", "init", "registry-repair", "fetch-tokenizer", *COMMANDS}
    )
    for name, command in commands.items():
        assert len(command.description) > 100, name
        assert "Example:" in command.epilog, name
        for action in command._actions:
            assert action.help and len(action.help) > 10, (name, action.dest)
    help_text = parser().format_help()
    assert "Getting started:" in help_text
    for name, (summary, _, _) in COMMAND_HELP.items():
        assert name in help_text
        assert summary in " ".join(help_text.split())


@pytest.mark.parametrize("command", COMMAND_HELP)
def test_cli_help_and_examples_are_valid(command, capsys):
    with pytest.raises(SystemExit) as exc:
        parser().parse_args([command, "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Example:" in output and COMMAND_HELP[command][0] in " ".join(output.split())
    assert COMMAND_HELP[command][2] in output  # A copyable, unbroken shell example.
    args = parser().parse_args(shlex.split(COMMAND_HELP[command][2])[1:])
    if command in COMMANDS:
        method, kwargs = contract(args)
        inspect.signature(getattr(Engine, method)).bind(None, **kwargs)


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_document_relative_links_exist(path):
    for token in MarkdownIt().parse(path.read_text(encoding="utf-8")):
        for child in token.children or []:
            target = child.attrGet("href") if child.type == "link_open" else None
            if not target or urlsplit(target).scheme or target.startswith(("#", "//")):
                continue
            target_path = unquote(urlsplit(target).path)
            assert (path.parent / target_path).exists(), (path.relative_to(ROOT), target)


def test_documented_rest_routes_match_source():
    tree = ast.parse((ROOT / "src/ragdbman/web.py").read_text(encoding="utf-8"))
    actual = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr in {"get", "post", "patch", "delete"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                route = decorator.args[0].value
                if route.startswith("/api/") or route.endswith("/events"):
                    actual.add((decorator.func.attr.upper(), route))
    documented = set()
    for line in (ROOT / "docs/API.md").read_text().splitlines():
        match = re.match(r"\| ([A-Z /]+) \| `([^`]+)` \|", line)
        if match:
            documented.update((method.strip(), match[2]) for method in match[1].split("/"))
    assert documented == actual


def test_python_guide_engine_calls_match_signatures():
    guide = (ROOT / "docs/PYTHON_API_GUIDE.md").read_text(encoding="utf-8")
    checked = 0
    for block in re.findall(r"```python\n(.*?)```", guide, re.S):
        tree = ast.parse(block)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "engine"
                and not any(isinstance(arg, ast.Starred) for arg in node.args)
                and all(kw.arg for kw in node.keywords)
            ):
                method = getattr(Engine, node.func.attr)
                inspect.signature(method).bind(
                    None, *([None] * len(node.args)), **{kw.arg: None for kw in node.keywords}
                )
                checked += 1
    assert checked > 20


def test_documented_toml_examples_validate():
    checked = 0
    for path in DOCS:
        if path.name in {"VISION.md", "VERIFICATION.md", "CHANGELOG.md"}:
            continue  # Aspirations/historical records are not current setup instructions.
        for token in MarkdownIt().parse(path.read_text(encoding="utf-8")):
            if token.type == "fence" and token.info.strip() == "toml":
                GlobalConfig.model_validate(tomllib.loads(token.content))
                checked += 1
    assert checked >= 10


def test_literal_application_error_codes_have_http_statuses():
    for path in (ROOT / "src/ragdbman").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "RagError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value in STATUS, (path.name, node.lineno, node.args[0].value)


def test_empty_search_table_preserves_diagnostics():
    output = table(
        "search-multi",
        {
            "results": [],
            "collections_searched": [],
            "collections_failed": [{"collection": "missing", "reason": "not found"}],
            "skipped_filters": [{"field": "unknown", "reason": "not available"}],
        },
    )
    assert output.startswith("(no rows)")
    assert "collections_failed" in output and "missing" in output
    assert "skipped_filters" in output and "unknown" in output
