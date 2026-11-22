"""Every place that states pbidriver's version (or its Python versions) must agree, so a release can't ship
with a stale badge, package file or citation. Run before tagging; the Tests workflow runs it on every push."""
import json
import re
from pathlib import Path

from pbidriver import __version__

ROOT = Path(__file__).resolve().parents[1]
V = __version__


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_package_files():
    assert json.loads(read("npm/package.json"))["version"] == V
    assert json.loads(read("plugins/pbidriver/.claude-plugin/plugin.json"))["version"] == V
    assert re.search(r"^version: (\S+)$", read("CITATION.cff"), re.M).group(1) == V
    assert re.search(r"Version (\d+\.\d+\.\d+), released", read("llms.txt")).group(1) == V


def test_changelog_has_this_version_on_top():
    headings = re.findall(r"^## (\S+)", read("CHANGELOG.md"), re.M)
    released = [h for h in headings if h != "Unreleased"]
    assert released and released[0] == V, f"CHANGELOG's newest release is {released[:1]}, the package is {V}"


def test_readme_badges_match_the_release():
    readme = read("README.md")
    # Version badges carry the version in their own URL: GitHub caches badge images, so badges that look the
    # version up can show an older one for a while after a release.
    assert f"img.shields.io/badge/pypi-v{V}-" in readme and f"pypi.org/project/pbidriver/{V}/" in readme
    assert f"img.shields.io/badge/npm-v{V}-" in readme and f"npmjs.com/package/pbidriver/v/{V}" in readme
    assert "img.shields.io/pypi/v/" not in readme and "img.shields.io/npm/v/" not in readme


def test_python_versions_agree():
    classifiers = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', read("pyproject.toml"))
    assert classifiers, "pyproject.toml lists no Python versions"
    badge = re.search(r"img\.shields\.io/badge/python-([^-]+)-", read("README.md")).group(1)
    assert badge.replace("%20", " ").replace("%7C", "|").split(" | ") == classifiers
    matrix = re.search(r'python-version: \[([^\]]+)\]', read(".github/workflows/tests.yml")).group(1)
    assert re.findall(r'"(3\.\d+)"', matrix) == classifiers, "the Tests workflow must test every listed version"
    minimum = re.search(r'requires-python = ">=(3\.\d+)"', read("pyproject.toml")).group(1)
    assert classifiers[0] == minimum
