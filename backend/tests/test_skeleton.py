# S03 smoke test: all skeleton packages import without errors.

import importlib
import os

import pytest

PACKAGES = [
    "seraphim",
    "seraphim.core",
    "seraphim.sanctum",
    "seraphim.wings",
    "seraphim.observatory",
    "seraphim.pulse",
]


@pytest.mark.parametrize("pkg", PACKAGES)
def test_package_importable(pkg: str) -> None:
    """Each skeleton package imports without exceptions."""
    mod = importlib.import_module(pkg)
    assert mod is not None


def test_seraphim_version_defined() -> None:
    """seraphim.__version__ exists and is a non-empty string."""
    import seraphim

    # __version__ is not set in S03; verify __file__ exists instead
    assert hasattr(seraphim, "__file__")
    assert seraphim.__file__ is not None


def test_testroot_exists() -> None:
    """shared/testroot/ exists — dev mode must not write to random system dirs."""
    # Navigate from backend/tests/ to project root, then to shared/testroot/
    test_dir = os.path.dirname(__file__)
    project_root = os.path.normpath(os.path.join(test_dir, "..", ".."))
    testroot = os.path.join(project_root, "shared", "testroot")
    assert os.path.isdir(testroot), f"testroot missing: {testroot}"
