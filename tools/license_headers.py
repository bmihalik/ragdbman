# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Check or mechanically add SPDX headers to first-party code/configuration."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINES = (
    "SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK",
    "SPDX-License-Identifier: Apache-2.0",
)
SUFFIXES = {".py", ".js", ".css", ".html", ".sql", ".toml", ".yml", ".yaml", ".service"}


def targets():
    yield ROOT / "pyproject.toml"
    for directory in ("src", "tests", "tools", "deploy", ".github"):
        yield from sorted(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file() and p.suffix in SUFFIXES and "__pycache__" not in p.parts
        )


def header(path):
    if path.suffix == ".html":
        return "<!--\n" + "\n".join(LINES) + "\n-->\n"
    if path.suffix == ".css":
        return "/*\n" + "\n".join(LINES) + "\n*/\n"
    prefix = "//" if path.suffix == ".js" else "--" if path.suffix == ".sql" else "#"
    return "\n".join(f"{prefix} {line}" for line in LINES) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Add missing headers")
    args = parser.parse_args()
    missing = []
    for path in targets():
        text = path.read_text()
        if text.startswith(header(path)):
            continue
        missing.append(str(path.relative_to(ROOT)))
        if args.write:
            if any(
                line.lstrip().startswith(
                    (
                        "# SPDX-License-Identifier:",
                        "// SPDX-License-Identifier:",
                        "-- SPDX-License-Identifier:",
                        "SPDX-License-Identifier:",
                    )
                )
                for line in text[:500].splitlines()
            ):
                raise SystemExit(f"Refusing to replace a different license: {path}")
            path.write_text(header(path) + "\n" + text)
    if missing:
        print(("Updated: " if args.write else "Missing headers: ") + ", ".join(missing))
    else:
        print("All first-party code headers use Apache-2.0.")
    return 0 if args.write or not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
