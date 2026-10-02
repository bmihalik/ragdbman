# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Static-source checks complement actual MCP discovery tests."""

import ast
import runpy
from pathlib import Path

from ragdbman.operations import OPERATIONS, QUERY_OPERATIONS, signature

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/ragdbman/mcp_tools.py"


def declarations():
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "server"
                and decorator.func.attr == "tool"
            ):
                assert node.name not in result
                result[node.name] = (node, {k.arg: k.value for k in decorator.keywords})
    return tree, result


def test_every_tool_has_literal_name_and_four_literal_boolean_hints():
    _, tools = declarations()
    assert tools.keys() == OPERATIONS.keys()
    for name, (node, keywords) in tools.items():
        assert isinstance(keywords["name"], ast.Constant) and keywords["name"].value == name
        assert isinstance(keywords["description"], ast.Constant) and keywords["description"].value
        annotation = keywords["annotations"]
        assert isinstance(annotation, ast.Call) and annotation.func.id == "ToolAnnotations"
        hints = {k.arg: k.value for k in annotation.keywords}
        spec = OPERATIONS[name]
        expected = {
            "readOnlyHint": spec.readonly,
            "destructiveHint": spec.destructive,
            "idempotentHint": spec.idempotent,
            "openWorldHint": False,
        }
        assert hints.keys() == expected.keys()
        for key, value in expected.items():
            assert isinstance(hints[key], ast.Constant), (name, key)
            assert type(hints[key].value) is bool and hints[key].value is value, (name, key)
        assert node.args.kwarg is None  # No generic **kwargs-only tool definitions.
        assert [p.arg for p in node.args.kwonlyargs] == list(signature(name).parameters)


def test_only_query_tools_are_outside_admin_branch():
    tree, _ = declarations()
    register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "register_tools")
    visible = {n.name for n in register.body if isinstance(n, ast.AsyncFunctionDef)}
    assert visible == QUERY_OPERATIONS
    branches = [n for n in register.body if isinstance(n, ast.If)]
    assert len(branches) == 1
    assert isinstance(branches[0].test, ast.Name) and branches[0].test.id == "admin"
    assert {n.name for n in branches[0].body if isinstance(n, ast.AsyncFunctionDef)} == (
        OPERATIONS.keys() - QUERY_OPERATIONS
    )


def test_mcp_source_is_regenerated_without_drift():
    generator = runpy.run_path(str(ROOT / "tools/generate_mcp_tools.py"))
    assert generator["render"]() == TARGET.read_text(encoding="utf-8")
