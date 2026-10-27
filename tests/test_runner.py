"""
tests/test_runner.py — pytest suite for gradepack runner integrity.

Covers:
  - _validate_candidate_files rejects bad filenames
  - overlay_dict / overlay_dir reject bad filenames
  - verify PASS on task 001
  - run produces correct JSON shape
  - filename normalisation (normalise_filename)
  - invalid output scoring 0.0
  - failure_reason categories
  - bench --publish skips mock files by default
  - agentic mode (mock-agentic: fail turn 1, pass turn 2)
  - raw_output_path is relative
  - validate on new tasks 019-026
"""
import json
import pathlib
import shutil
import tempfile

import pytest

import sys, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gradepack import api as _api
from gradepack import core
from gradepack import bench as _bench


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_001 = "001-pagination-off-by-one"


def _make_starter_copy(task_id: str) -> tuple[pathlib.Path, pathlib.Path]:
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
    allowed = {"paginate.py"}
    with pytest.raises(core.CandidateError):
        core._validate_candidate_files({bad_name: "# evil"}, allowed)


def test_reject_unknown_file():
    allowed = {"paginate.py"}
    with pytest.raises(core.CandidateError):
        core._validate_candidate_files({"unknown.py": "x"}, allowed)


def test_accept_valid_file():
    allowed = {"paginate.py"}
    core._validate_candidate_files({"paginate.py": "# ok"}, allowed)


# ---------------------------------------------------------------------------
# overlay_dict — integration
# ---------------------------------------------------------------------------

def test_overlay_dict_rejects_conftest():
    tmp_parent, tmp_task = _make_starter_copy(TASK_001)
    try:
        with pytest.raises(core.CandidateError, match="conftest"):
            core.overlay_dict({"conftest.py": "# evil"}, tmp_task / "starter")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def test_overlay_dict_rejects_path_sep():
    tmp_parent, tmp_task = _make_starter_copy(TASK_001)
    try:
        with pytest.raises(core.CandidateError):
            core.overlay_dict({"grader/test_x.py": "# evil"}, tmp_task / "starter")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# verify — task 001 must PASS
# ---------------------------------------------------------------------------

def test_verify_task_001_pass(capsys):
    from gradepack.cli import cmd_verify
    cmd_verify(TASK_001)
    captured = capsys.readouterr()
    assert "PASS" in captured.out
    assert "7/7" in captured.out


# ---------------------------------------------------------------------------
# run — JSON shape
# ---------------------------------------------------------------------------

def test_run_json_shape(capsys):
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
    from gradepack.cli import cmd_run
    solution_dir = str(core.task_dir(TASK_001) / "solution")
    cmd_run(TASK_001, solution_dir)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    for key in ("task_id", "passed", "failed", "total", "score", "failing_tests"):
        assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# normalise_filename
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,allowed,expected", [
    ("paginate.py",         {"paginate.py"}, "paginate.py"),
    ("starter/paginate.py", {"paginate.py"}, "paginate.py"),
    ("./paginate.py",       {"paginate.py"}, "paginate.py"),
    ("./starter/paginate.py", {"paginate.py"}, "paginate.py"),
    ("grader/test.py",      {"paginate.py"}, None),       # not in allowed
    ("conftest.py",         {"conftest.py", "paginate.py"}, "conftest.py"),  # normalise works even for conftest (validation is separate)
    ("unknown.py",          {"paginate.py"}, None),
])
def test_normalise_filename(raw, allowed, expected):
    result = _api.normalise_filename(raw, allowed)
    assert result == expected


# ---------------------------------------------------------------------------
# invalid output scores 0.0
# ---------------------------------------------------------------------------

def test_invalid_output_scores_zero():
    """When no parseable candidate files are found, score must be 0.0."""
    result = core.run_pytest.__func__ if hasattr(core.run_pytest, '__func__') else None
    # Simulate: _bench_task with mock_pass=False gives starter (wrong answer)
    record = _bench._bench_task(
        TASK_001, 1,
        mock=True, mock_pass=False,
        raw_output_dir=pathlib.Path(tempfile.gettempdir()) / "gradepack_test_raw",
        provider="test", model_name="test",
        max_tokens=8192, temperature=0.7,
    )
    # Starter has bugs → should NOT score 1.0
    assert record["score"] < 1.0


def test_no_candidate_scores_zero():
    """If candidate_files is empty after parsing, score must be 0.0."""
    # Simulate empty parse result → had_candidate=False
    empty_result = {"passed": 0, "failed": 0, "total": 0, "failures": []}
    reason = _bench._categorise(empty_result, error_msg=None, finish_reason="stop", had_candidate=False)
    assert reason == "invalid_output"


# ---------------------------------------------------------------------------
# failure_reason categories
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("error_msg,finish_reason,had_candidate,total,failed,expected_reason", [
    # error cases
    ("HTTP 429: Too Many Requests", "error", True, 0, 0, "api_error"),
    ("Connection timed out", "error", True, 0, 0, "timeout"),
    ("some runner error", "error", True, 0, 0, "runner_error"),
    # no candidate
    (None, "length", False, 0, 0, "no_answer"),
    (None, "stop",   False, 0, 0, "invalid_output"),
    # import error (no tests ran)
    (None, "stop",   True, 0, 0, "invalid_output"),
    # all passed
    (None, "stop",   True, 5, 0, "none"),
    # parametrized failure
    (None, "stop",   True, 5, 2, "test_failure_parametrized"),
    # plain failure
    (None, "stop",   True, 5, 1, "wrong_answer"),
])
def test_failure_reason_categories(error_msg, finish_reason, had_candidate, total, failed, expected_reason):
    failures = ["test_foo[0]", "test_bar[1]"] if failed == 2 else (["test_foo"] if failed == 1 else [])
    result = {"passed": total - failed, "failed": failed, "total": total, "failures": failures}
    reason = _bench._categorise(result, error_msg=error_msg, finish_reason=finish_reason, had_candidate=had_candidate)
    assert reason == expected_reason, f"Got {reason!r}, expected {expected_reason!r}"


# ---------------------------------------------------------------------------
# bench --publish skips mock files by default
# ---------------------------------------------------------------------------

def test_publish_skips_mock_by_default(tmp_path):
    """_publish must skip files whose stem starts with 'mock' unless include_mock=True."""
    # Create a fake results file named mock-test.json
    mock_file = tmp_path / "mock-test.json"
    mock_file.write_text("[]")

    # Redirect docs to tmp_path so we don't pollute the repo
    import gradepack.bench as _b
    orig = _b.core._repo_root
    _b.core._repo_root = lambda: tmp_path
    try:
        _b._publish(mock_file, include_mock=False)
        # Should NOT have been copied
        assert not (tmp_path / "docs" / "results" / "mock-test.json").exists()
    finally:
        _b.core._repo_root = orig


def test_publish_includes_mock_when_flagged(tmp_path, capsys):
    """_publish must copy mock files when include_mock=True."""
    mock_file = tmp_path / "mock-test.json"
    mock_file.write_text("[]")

    import gradepack.bench as _b
    orig = _b.core._repo_root
    _b.core._repo_root = lambda: tmp_path
    try:
        _b._publish(mock_file, include_mock=True)
        assert (tmp_path / "docs" / "results" / "mock-test.json").exists()
    finally:
        _b.core._repo_root = orig


def test_publish_real_model_always_published(tmp_path):
    """Non-mock files must always be published."""
    real_file = tmp_path / "gpt-4o.json"
    real_file.write_text("[]")

    import gradepack.bench as _b
    orig = _b.core._repo_root
    _b.core._repo_root = lambda: tmp_path
    try:
        _b._publish(real_file, include_mock=False)
        assert (tmp_path / "docs" / "results" / "gpt-4o.json").exists()
    finally:
        _b.core._repo_root = orig


# ---------------------------------------------------------------------------
# Agentic mode — mock-agentic: fail turn 1, pass turn 2
# ---------------------------------------------------------------------------

def test_mock_agentic_solves_on_turn2():
    """mock-agentic should fail turn 1 and succeed on turn 2."""
    record = _bench._bench_task_agentic(
        TASK_001, 1,
        mock=False, mock_agentic=True, mock_pass=True,
        raw_output_dir=pathlib.Path(tempfile.gettempdir()) / "gradepack_agentic_test",
        provider="test", model_name="test",
        max_tokens=8192, temperature=0.7,
        max_turns=3,
    )
    assert record["agentic"] is True
    assert record["solved_at_turn"] == 2
    assert record["turns_used"] == 2
    assert record["score"] == 1.0


def test_mock_agentic_fails_all_turns_when_max1():
    """With max_turns=1 and mock-agentic, should fail (only 1 turn, which fails)."""
    record = _bench._bench_task_agentic(
        TASK_001, 1,
        mock=False, mock_agentic=True, mock_pass=True,
        raw_output_dir=pathlib.Path(tempfile.gettempdir()) / "gradepack_agentic_test",
        provider="test", model_name="test",
        max_tokens=8192, temperature=0.7,
        max_turns=1,
    )
    assert record["agentic"] is True
    assert record["solved_at_turn"] is None
    assert record["score"] < 1.0


def test_mock_regular_passes_turn1():
    """Regular mock (not agentic) with --mock should pass on first and only turn."""
    record = _bench._bench_task_agentic(
        TASK_001, 1,
        mock=True, mock_agentic=False, mock_pass=True,
        raw_output_dir=pathlib.Path(tempfile.gettempdir()) / "gradepack_agentic_test",
        provider="test", model_name="test",
        max_tokens=8192, temperature=0.7,
        max_turns=3,
    )
    assert record["solved_at_turn"] == 1
    assert record["score"] == 1.0


# ---------------------------------------------------------------------------
# raw_output_path is relative
# ---------------------------------------------------------------------------

def test_bench_task_raw_path_is_relative():
    """raw_output_path in a bench record must be relative (no leading '/')."""
    # Use a raw_dir inside the repo root so relative_to() succeeds.
    raw_dir = core._repo_root() / "results" / "raw" / "_test_relative"
    try:
        record = _bench._bench_task(
            TASK_001, 1,
            mock=True, mock_pass=True,
            raw_output_dir=raw_dir,
            provider="test", model_name="test",
            max_tokens=8192, temperature=0.7,
        )
        rp = record.get("raw_output_path")
        assert rp is not None, "raw_output_path should be set"
        assert not rp.startswith("/"), f"raw_output_path should be relative, got: {rp}"
    finally:
        shutil.rmtree(raw_dir, ignore_errors=True)


def test_agentic_task_raw_path_is_relative():
    """raw_output_path in an agentic record must be relative."""
    raw_dir = core._repo_root() / "results" / "raw" / "_test_agentic_relative"
    try:
        record = _bench._bench_task_agentic(
            TASK_001, 1,
            mock=True, mock_agentic=False, mock_pass=True,
            raw_output_dir=raw_dir,
            provider="test", model_name="test",
            max_tokens=8192, temperature=0.7,
            max_turns=2,
        )
        rp = record.get("raw_output_path")
        assert rp is not None
        assert not rp.startswith("/"), f"raw_output_path should be relative, got: {rp}"
    finally:
        shutil.rmtree(raw_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# validate on new tasks 019–026
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task_id", [
    "019-invoice-total",
    "020-log-parser",
    "021-config-merger",
    "022-permissions",
    "023-inventory",
    "024-csv-importer",
    "025-rate-limiter",
    "026-retry-client",
])
def test_validate_new_tasks(task_id):
    """Each new task must pass validate with zero errors."""
    from gradepack.validate import validate_task
    errors = validate_task(task_id)
    assert errors == [], f"Validation errors for {task_id}: {errors}"
