"""Tests for where the Agency finds its data when it is INSTALLED.

THE PROBLEM
------------
In a source checkout the package is at ``app/src/tis``, so the project
root is three levels up — and the registry, the conversational
catalogue and the assets all live there.

In an INSTALL the package is in ``site-packages``, and three levels up
is the virtualenv. The registry is not there. So a cask or a pip
install of this package would find no models at all, and the Agency
would come up empty-handed with no error to explain why.

THE RULE
--------
The data is found by LOOKING FOR IT, not by counting directories. A
source checkout is recognised by its registry; an install is
recognised by the data the cask put beside the virtualenv; and if
neither is there, the paths land in the user's own directory rather
than in a place that does not exist.

The order is fixed and stated, because "where did it put my images"
is a question that should have one answer:

1. ``TIIS_REGISTRY_PATH`` — an explicit override always wins.
2. the source checkout, if that is what this is.
3. ``<prefix>/share/tiiny-image-agency`` — where the cask installs it.
4. ``~/.tiiny-image-agency`` — the user's own directory.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tis.config import Settings


def _write_registry(root: Path) -> Path:
    """A registry file, so the resolver has something to find."""
    registry_dir = root / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / "image-models.json"
    path.write_text(json.dumps({"models": [], "planner": {}}), encoding="utf-8")
    return path


def test_the_explicit_override_wins(tmp_path, monkeypatch):
    """An explicit path is an explicit path."""
    elsewhere = tmp_path / "elsewhere" / "image-models.json"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TIIS_REGISTRY_PATH", str(elsewhere))

    settings = Settings()

    assert settings.registry_path == elsewhere


def test_a_source_checkout_is_found_by_its_registry(tmp_path, monkeypatch):
    """A checkout is recognised by the data being there."""
    checkout = tmp_path / "checkout"
    _write_registry(checkout)
    monkeypatch.delenv("TIIS_REGISTRY_PATH", raising=False)
    monkeypatch.setattr("tis.config._checkout_root", lambda: checkout)

    settings = Settings()

    assert settings.registry_path == checkout / "registry" / "image-models.json"
    assert settings.roles_path == checkout / "registry" / "roles.json"


def test_an_install_is_found_beside_the_virtualenv(tmp_path, monkeypatch):
    """The cask puts the data in the virtualenv's share directory."""
    prefix = tmp_path / "venv"
    installed = prefix / "share" / "tiiny-image-agency"
    _write_registry(installed)
    monkeypatch.delenv("TIIS_REGISTRY_PATH", raising=False)
    monkeypatch.setattr("tis.config.sys.prefix", str(prefix))
    monkeypatch.setattr("tis.config._checkout_root",
                        lambda: prefix)  # not a checkout

    settings = Settings()

    assert settings.registry_path == (
        installed / "registry" / "image-models.json")
    assert settings.roles_path == installed / "registry" / "roles.json"


def test_with_nothing_installed_the_paths_land_in_the_users_directory(
        tmp_path, monkeypatch):
    """A missing directory is a bad default. The user's own directory
    is at least writable and somewhere they can find."""
    monkeypatch.delenv("TIIS_REGISTRY_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tis.config.sys.prefix", str(tmp_path / "venv"))
    monkeypatch.setattr("tis.config._checkout_root",
                        lambda: tmp_path / "venv")

    settings = Settings()

    assert settings.registry_path == (
        tmp_path / "home" / ".tiiny-image-agency" / "registry"
        / "image-models.json")
    assert settings.assets_dir == (
        tmp_path / "home" / ".tiiny-image-agency" / "assets")


def test_the_data_directory_is_the_one_place_that_is_looked_in(
        tmp_path, monkeypatch):
    """Everything that travels with the package travels together."""
    monkeypatch.delenv("TIIS_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("TIIS_ROLES_PATH", raising=False)
    monkeypatch.delenv("TIIS_ASSETS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tis.config.sys.prefix", str(tmp_path / "venv"))
    monkeypatch.setattr("tis.config._checkout_root",
                        lambda: tmp_path / "venv")

    settings = Settings()

    assert settings.registry_path.parent.parent == settings.roles_path.parent.parent
    assert settings.assets_dir.parent == settings.registry_path.parent.parent
