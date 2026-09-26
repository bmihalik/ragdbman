# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Keep release citation metadata synchronized without network-dependent tests."""

import json
import tomllib
from datetime import date
from pathlib import Path

import yaml

from ragdbman import __version__

ROOT = Path(__file__).resolve().parents[1]


def metadata():
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    codemeta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return citation, codemeta, project


def test_release_identity_and_version():
    citation, codemeta, project = metadata()
    assert citation["cff-version"] == "1.2.0"
    assert citation["type"] == "software"
    assert citation["message"]
    assert citation["title"] == codemeta["name"] == project["name"] == "ragdbman"
    assert citation["version"] == codemeta["softwareVersion"] == project["version"] == __version__
    assert date.fromisoformat(citation["date-released"]) == date.fromisoformat(codemeta["dateModified"])


def test_author_license_and_description():
    citation, codemeta, project = metadata()
    author = citation["authors"][0]
    assert author["given-names"] == codemeta["author"][0]["givenName"] == "Bela Istvan"
    assert author["family-names"] == codemeta["author"][0]["familyName"] == "MIHALIK"
    assert f"{author['given-names']} {author['family-names']}" == project["authors"][0]["name"]
    assert citation["license"] == project["license"] == "Apache-2.0"
    assert codemeta["license"] == "https://spdx.org/licenses/Apache-2.0"
    assert citation["abstract"] == codemeta["description"]
    assert citation["keywords"] == codemeta["keywords"]
    assert codemeta["@type"] == "SoftwareSourceCode"
    assert codemeta["@context"] == "https://w3id.org/codemeta/3.1"


def test_citation_files_are_in_wheel_build_plan():
    build = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["hatch"]["build"]
    include = build["targets"]["wheel"]["force-include"]
    assert include["CITATION.cff"] == "ragdbman/CITATION.cff"
    assert include["codemeta.json"] == "ragdbman/codemeta.json"
