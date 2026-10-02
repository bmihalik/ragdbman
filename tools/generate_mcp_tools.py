# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Generate inspectable MCP declarations without duplicating the operation contracts."""

import argparse
import inspect
import subprocess
import sys
from pathlib import Path

from ragdbman.operations import OPERATIONS, QUERY_OPERATIONS

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/ragdbman/mcp_tools.py"


def render():
    lines = [
        "# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK",
        "# SPDX-License-Identifier: Apache-2.0",
        "",
        '"""Generated MCP declarations. Edit operations.py, then run tools/generate_mcp_tools.py.',
        "",
        "Literal tool names and boolean hints are intentional for static source inspection.",
        'The canonical signatures/validation still come from the shared operation catalog."""',
        "",
        "from typing import Literal, Optional",
        "",
        "from mcp.types import CallToolResult, ToolAnnotations",
        "",
        "from .models import SearchFilters",
        "from .operations import invoke, signature",
        "",
        "",
        "def canonical_signature(name):",
        '    """Preserve model constraints and default factories in the runtime tool schema."""',
        "    def decorate(function):",
        "        function.__signature__ = signature(name, mcp=True)",
        "        function.__annotations__ = {",
        "            p.name: p.annotation for p in function.__signature__.parameters.values()",
        "        }",
        '        function.__annotations__["return"] = CallToolResult',
        "        return function",
        "    return decorate",
        "",
        "",
        "def register_tools(server, engine, admin, present):",
        '    """Register three query tools and, only when enabled, named administrative tools."""',
    ]

    def declaration(name, spec, indent):
        block = [
            "@server.tool(",
            f"    name={name!r},",
            f"    description={spec.description!r},",
            "    annotations=ToolAnnotations(",
            f"        readOnlyHint={spec.readonly!r},",
            f"        destructiveHint={spec.destructive!r},",
            f"        idempotentHint={spec.idempotent!r},",
            "        openWorldHint=False,",
            "    ),",
            ")",
            f"@canonical_signature({name!r})",
        ]
        fields = spec.model.model_fields
        if fields:
            block += [f"async def {name}(", "    *,"]
            for key, field in fields.items():
                annotation = (
                    inspect.formatannotation(field.annotation)
                    .replace("typing.", "")
                    .replace("ragdbman.models.", "")
                )
                if field.is_required():
                    default = ""
                elif field.default_factory:
                    annotation = f"Optional[{annotation}]"
                    default = " = None"
                else:
                    value = "llm" if key == "format" else field.default
                    default = f" = {value!r}"
                block.append(f"    {key}: {annotation}{default},")
            block += [") -> CallToolResult:", "    arguments = {"]
            block += [f"        {key!r}: {key}," for key in fields]
            block.append("    }")
            for key, field in fields.items():
                if field.default_factory:
                    block += [f"    if {key} is None:", f"        arguments.pop({key!r})"]
            block += [f"    return present(await invoke(engine, {name!r}, arguments, admin=admin))"]
        else:
            block += [
                f"async def {name}() -> CallToolResult:",
                f"    return present(await invoke(engine, {name!r}, {{}}, admin=admin))",
            ]
        lines.extend(indent + line if line else "" for line in block)
        lines.append("")

    for name, spec in OPERATIONS.items():
        if name in QUERY_OPERATIONS:
            declaration(name, spec, "    ")
    lines.append("    if admin:")
    for name, spec in OPERATIONS.items():
        if name not in QUERY_OPERATIONS:
            declaration(name, spec, "        ")
    # Formatting is deterministic under the development lockfile.
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", str(TARGET), "-"],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the generated declarations are stale.")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            raise SystemExit("MCP declarations are stale; run tools/generate_mcp_tools.py")
        print("Explicit MCP declarations are current.")
    else:
        TARGET.write_text(text, encoding="utf-8")
        print(TARGET)
