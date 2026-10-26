"""
tests/test_runner.py — pytest suite for gradepack runner integrity.

Covers:
  - _validate_candidate_files rejects bad filenames
  - overlay_dict / overlay_dir reject bad filenames
  - verify PASS on task 001
  - run produces correct JSON shape
"""
import json
import pathlib
import shutil
import tempfile

import pytest

# Adjust import path so tests work from repo root and from gradepack/ subdir.
import sys, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gradepack import core


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_001 = "001-pagination-off-by-one"
_TASKS = core.tasks_dir()


def _make_starter_copy(task_id: str) -> tuple[pathlib.Path, pathlib.Path]:
    """Return (tmp_parent, tmp_task_root). Caller must clean up tmp_parent."""
    tmp_task = core.make_temp_copy(task_id)
    return tmp_task.parent, tmp_task


# ---------------------------------------------------------------------------
# _validate_candidate_files — rejection cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_name", [
    "conftest.py",
    "../escape.py",
    "subdir/attack.py",
    "grader/test_hack.py",
    "..\\windows.py",
])
def test_reject_bad_filename(bad_name):
    """_validate_candidate_files must raise CandidateError for forbidden names."""
    allowed = {"paginate.py"}
    with pytest.raises(core.CandidateError):
        core._validate_candidate_files({bad_name: "# evil"}, allowed)


def test_reject_unknown_file():
    """A filename not in the starter must be rejected."""
    allowed = {"paginate.py"}
    with pytest.raises(core.CandidateError):
        core._validate_candidate_files({"unknown.py": "x"}, allowed)


def test_accept_valid_file():
    """A filename present in the starter must be accepted."""
    allowed = {"paginate.py"}
    # Should not raise
    core._validate_candidate_files({"paginate.py": "# ok"}, allowed)


# ---------------------------------------------------------------------------
# overlay_dict — integration
# ---------------------------------------------------------------------------

def test_overlay_dict_rejects_conftest():
    tmp_parent, tmp_task = _make_starter_copy(TASK_001)
    try:
        with pytest.raises(core.CandidateError, match="conftest"):
            core.overlay_dict(
                {"conftest.py": "# evil"},
                tmp_task / "starter",
            )
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def test_overlay_dict_rejects_path_sep():
    tmp_parent, tmp_task = _make_starter_copy(TASK_001)
    try:
        with pytest.raises(core.CandidateError):
            core.overlay_dict(
                {"grader/test_x.py": "# evil"},
                tmp_task / "starter",
            )
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# verify — task 001 must PASS
# ---------------------------------------------------------------------------

def test_verify_task_001_pass(capsys):
    """verify on task 001 must print PASS and exit 0."""
    from gradepack.cli import cmd_verify
    cmd_verify(TASK_001)
    captured = capsys.readouterr()
    assert "PASS" in captured.out
    assert "7/7" in captured.out


# ---------------------------------------------------------------------------
# run — JSON shape
# ---------------------------------------------------------------------------

def test_run_json_shape(capsys):
    """run on task 001 with the solution must produce valid JSON with the right keys."""
    from gradepack.cli import cmd_run
    solution_dir = str(core.task_dir(TASK_001) / "solution")
    cmd_run(TASK_001, solution_dir)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["task_id"] == TASK_001
    assert data["passed"] == 7
    assert data["failed"] == 0
    assert data["total"] == 7
    assert data["score"] == 1.0
    assert data["failing_tests"] == []


def test_run_json_shape_keys(capsys):
    """run output must have all required keys."""
    from gradepack.cli import cmd_run
    solution_dir = str(core.task_dir(TASK_001) / "solution")
    cmd_run(TASK_001, solution_dir)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    for key in ("task_id", "passed", "failed", "total", "score", "failing_tests"):
        assert key in data, f"Missing key: {key}"
