#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Source-checkout launcher; prefer the uv-managed environment when available."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# A same-named convenience script normally shadows a src-layout package when
# the checkout root is importable. A canonical import must resolve to the actual
# package, including its resource loader, not a partial package imitation.
if __name__ == "ragdbman":
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "ragdbman",
        ROOT / "src" / "ragdbman" / "__init__.py",
        submodule_search_locations=[str(ROOT / "src" / "ragdbman")],
    )
    package = module_from_spec(spec)
    sys.modules["ragdbman"] = package
    spec.loader.exec_module(package)


def launch():
    local_python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if sys.prefix == sys.base_prefix and local_python.is_file():
        os.execv(str(local_python), [str(local_python), str(ROOT / "ragdbman.py"), *sys.argv[1:]])
    # The src package must win over this same-named script and installed copies.
    sys.path.insert(0, str(ROOT / "src"))
    from ragdbman.cli import main

    main()


if __name__ == "__main__":
    launch()
