"""Release hygiene: version strings and packaging metadata stay consistent."""

import configparser
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _version_files():
    pyproject = (ROOT / "pyproject.toml").read_text()
    setup_cfg = configparser.ConfigParser()
    setup_cfg.read(ROOT / "setup.cfg")
    return {
        "pyproject": re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1),
        "setup.cfg": setup_cfg["metadata"]["version"],
        "prof/__init__.py": re.search(r'__version__ = "([^"]+)"',
                                      (ROOT / "prof" / "__init__.py").read_text()).group(1),
        "prof/server.py": re.search(r'^VERSION = "([^"]+)"',
                                    (ROOT / "prof" / "server.py").read_text(), re.M).group(1),
    }


def test_versions_agree():
    versions = _version_files()
    assert len(set(versions.values())) == 1, versions


def test_version_is_release():
    from prof import __version__
    major, minor, patch = (int(x) for x in __version__.split("."))
    assert (major, minor, patch) >= (1, 0, 0)


def test_compose_and_k8s_pin_release_image():
    from prof import __version__
    for f in ("docker-compose.yml", "deploy/k8s.yaml", "Makefile"):
        text = (ROOT / f).read_text()
        assert f"prof-gateway:{__version__}" in text, f


def test_changelog_has_release_entry():
    from prof import __version__
    assert f"## v{__version__}" in (ROOT / "CHANGELOG.md").read_text()
