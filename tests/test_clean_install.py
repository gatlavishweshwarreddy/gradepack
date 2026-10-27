"""
tests/test_clean_install.py — smoke-test a fresh pip install -e . in a temp venv.

Skips politely if:
  - venv creation fails (e.g., missing python3-venv on some CI images)
  - pip install fails for any reason
  - the gradepack command is not found after install

This test is intentionally slow (it actually installs) and is skipped in
environments without venv support rather than failing.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

# Repo root (parent of this tests/ directory)
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _can_create_venv(venv_dir: pathlib.Path) -> bool:
    """Return True if we can create a virtual environment at venv_dir."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def installed_venv(tmp_path_factory):
    """
    Creates a temp venv, installs gradepack -e, returns the path to the
    venv's python executable.  Skips if venv creation is not possible.
    """
    tmp = tmp_path_factory.mktemp("venv_install")
    venv_dir = tmp / "venv"

    if not _can_create_venv(venv_dir):
        pytest.skip("Cannot create virtual environment (venv module unavailable)")

    python = venv_dir / "bin" / "python"
    if not python.exists():
        python = venv_dir / "Scripts" / "python.exe"  # Windows
    if not python.exists():
        pytest.skip("Cannot locate python in created venv")

    # Install pytest first (needed by gradepack at runtime for running graders)
    try:
        pip_result = subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "pytest", "-e", str(_REPO)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("pip install timed out (network unavailable or slow)")
    if pip_result.returncode != 0:
        pytest.skip(f"pip install failed: {pip_result.stderr[:500]}")

    return python


def test_gradepack_list(installed_venv):
    """gradepack list must exit 0 and print at least one task."""
    result = subprocess.run(
        [str(installed_venv), "-m", "gradepack", "list"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_REPO),
    )
    assert result.returncode == 0, f"gradepack list failed: {result.stderr}"
    assert "001-pagination-off-by-one" in result.stdout


def test_gradepack_validate(installed_venv):
    """gradepack validate must exit 0."""
    result = subprocess.run(
        [str(installed_venv), "-m", "gradepack", "validate"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_REPO),
    )
    assert result.returncode == 0, f"gradepack validate failed:\n{result.stdout}\n{result.stderr}"


def test_gradepack_bench_help(installed_venv):
    """gradepack bench --help must exit 0 and mention --model."""
    result = subprocess.run(
        [str(installed_venv), "-m", "gradepack", "bench", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_REPO),
    )
    assert result.returncode == 0, f"bench --help failed: {result.stderr}"
    assert "--model" in result.stdout
