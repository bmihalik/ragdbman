# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Isolated-process regressions for same-named launchers and source imports."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ragdbman import __version__

ROOT = Path(__file__).resolve().parents[1]


def run(code, directory):
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=directory,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )


@pytest.fixture
def checkout(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "ragdbman.py", tmp_path / "ragdbman.py")
    return tmp_path


def test_launcher_import_has_no_side_effects(checkout):
    result = run(
        "import sys; sys.path.insert(0,'.'); import ragdbman, ragdbman.cli; "
        "from importlib.resources import files; "
        "assert files(ragdbman).joinpath('static','index.html').is_file(); "
        "assert files(ragdbman).joinpath('schema.sql').is_file(); "
        "print(ragdbman.__version__, ragdbman.cli.__name__)",
        checkout,
    )
    assert result.stdout.strip() == f"{__version__} ragdbman.cli"


@pytest.mark.parametrize("module", [False, True])
def test_checkout_launcher_uses_canonical_package(checkout, module):
    code = "import sys, runpy; sys.argv=['ragdbman.py', '--version']; " + (
        "sys.path.insert(0,'.'); runpy.run_module('ragdbman', run_name='__main__')"
        if module
        else "runpy.run_path('ragdbman.py', run_name='__main__')"
    )
    result = run(code, checkout)
    assert result.stdout.strip() == f"ragdbman {__version__}"
    assert not result.stderr


def test_source_qualified_import_never_imports_shadow_launcher(checkout):
    (checkout / "ragdbman.py").write_text("raise RuntimeError('SHADOW LAUNCHER IMPORTED')\n")
    code = """
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import httpx
from src.ragdbman.config import GlobalConfig
from src.ragdbman.engine import Engine
from src.ragdbman.web import create_app

class Embedder:
    async def embed(self, texts, *args):
        return [[1.0, 0.0] for _ in texts]

async def check():
    root = Path.cwd()
    cfg = GlobalConfig(storage={
        'data_dir': str(root/'data'), 'registry_path': str(root/'registry.json')
    }, defaults={'allow_approximate_tokenizer': True})
    engine = Engine(cfg, Embedder())
    try:
        for kind in ('general', 'knowledge_cards'):
            await engine.create_collection(name=kind, kind=kind)
        app = create_app(engine, False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url='http://localhost') as client:
            for path in ('/', '/static/app.js', '/static/style.css', '/api/collections'):
                response = await client.get(path)
                assert response.status_code == 200, (path, response.text)
        assert 'ragdbman' not in sys.modules
        print('UI, assets, both schemas: no launcher import')
    finally:
        await engine.close()
asyncio.run(check())
"""
    assert "no launcher import" in run(code, checkout).stdout


def test_launcher_prefers_local_environment_only_outside_virtualenv(checkout):
    code = """
import sys, runpy, os
from pathlib import Path
root=Path.cwd()
python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
python.parent.mkdir(parents=True)
python.touch()
namespace=runpy.run_path('ragdbman.py',run_name='safe_launcher')
sys.prefix=sys.base_prefix
class Reexecuted(Exception): pass
def execv(path, argv):
    assert path == str(python)
    assert argv[1] == str(root/'ragdbman.py')
    assert argv[2:] == ['serve', '--config', 'custom.toml']
    raise Reexecuted
namespace['launch'].__globals__['os'].execv=execv
sys.argv=['ragdbman.py','serve','--config','custom.toml']
try:
    namespace['launch']()
except Reexecuted:
    print('selected local environment')
else:
    raise AssertionError('Did not reexecute')
"""
    assert "selected local environment" in run(code, checkout).stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable permission")
def test_launcher_is_executable():
    assert os.access(ROOT / "ragdbman.py", os.X_OK)
