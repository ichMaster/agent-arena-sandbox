"""ARENA-001 -- the project skeleton and its tooling gates.

These tests guard the harness the rest of the phase is proven in: the three
packages import, and the pytest configuration stays scoped to ``tests/`` so the
code-generation tracker's own suite under ``codegen/`` is never swept into this
one.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        data: dict[str, object] = tomllib.load(handle)
    return data


@pytest.mark.parametrize("package", ["games", "server", "agent"])
def test_the_declared_packages_import(package: str) -> None:
    """Every package pinned in pyproject.toml must actually be importable."""
    assert importlib.import_module(package) is not None


def test_the_package_list_is_pinned_explicitly() -> None:
    """Flat-layout auto-discovery would fail the build; the list must be explicit.

    Without this, setuptools finds web/, profiles/, spec/, scripts/ and codegen/
    as candidate top-level packages and refuses with "Multiple top-level packages
    discovered in a flat-layout".
    """
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    setuptools_cfg = tool["setuptools"]
    assert isinstance(setuptools_cfg, dict)
    assert setuptools_cfg["packages"] == ["games", "server", "agent"]


def test_mypy_is_strict_from_pyproject_alone() -> None:
    """The gate is `mypy games server agent` with no flags, so strict lives here.

    A mypy.ini must never be introduced: mypy treats a missing --config-file as a
    hard error and would silently type-check nothing.
    """
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    mypy_cfg = tool["mypy"]
    assert isinstance(mypy_cfg, dict)
    assert mypy_cfg["strict"] is True
    assert not (REPO_ROOT / "mypy.ini").exists()


def test_pytest_does_not_collect_the_tracker_suite() -> None:
    """testpaths must stay scoped to tests/.

    This file becomes pytest's rootdir config and shadows codegen/pyproject.toml,
    so collecting codegen/tests/ from here would error on its missing `pytester`
    plugin. The tracker suite is run from its own directory instead:
    `cd codegen && pytest`.
    """
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    pytest_cfg = tool["pytest"]
    assert isinstance(pytest_cfg, dict)
    ini_options = pytest_cfg["ini_options"]
    assert isinstance(ini_options, dict)
    assert ini_options["testpaths"] == ["tests"]
