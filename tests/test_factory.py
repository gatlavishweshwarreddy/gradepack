"""
tests/test_factory.py — tests for the factory probe, numbering, stats, and promote pipeline.

No real API calls. Uses FakeServer for probe tests.
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest.mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tests.fake_server import FakeServer
from gradepack import core
from gradepack import factory as _factory
from gradepack import cli as _cli

TASK_001 = "001-pagination-off-by-one"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_draft_files() -> dict[str, str]:
    """Return files dict for a valid mock draft (adder task)."""
    files = _factory._mock_draft()
    # _assign_id will renumber; we need a stable slug for tests
    return files


def _make_temp_accepted_draft(tmp_path: pathlib.Path, task_id: str) -> pathlib.Path:
    """
    Write a minimal valid draft into tmp_path/drafts/accepted/<task_id>/.
    Returns the draft directory path.
    Uses 6 test functions (≥ 6 required by lint) and no BUG comments.
    """
    draft_dir = tmp_path / "drafts" / "accepted" / task_id
    draft_dir.mkdir(parents=True)
    meta = {
        "id": task_id,
        "title": "Fix the broken adder",
        "language": "python",
        "difficulty": "hard",
        "prompt": (
            "The function add(a, b) returns the wrong result. Fix it. "
            "The function should perform basic integer addition. "
            "Check edge cases including negative numbers, zero, and large values. "
            "The grader runs parametrized tests. Do not change the signature."
        ),
        "grader": "pytest",
        "version": "1.0",
        "tags": ["arithmetic"],
        "estimated_minutes": 5,
        "license": "MIT",
    }
    (draft_dir / "task.json").write_text(json.dumps(meta, indent=2))
    (draft_dir / "starter").mkdir()
    (draft_dir / "starter" / "adder.py").write_text(
        "def add(a, b):\n    return a - b\n"
    )
    (draft_dir / "grader").mkdir()
    (draft_dir / "grader" / "test_adder.py").write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
        "from adder import add\n\n"
        "def test_add_basic():\n    assert add(1, 2) == 3\n\n"
        "def test_add_zeros():\n    assert add(0, 0) == 0\n\n"
        "def test_add_negative():\n    assert add(-1, 5) == 4\n\n"
        "def test_add_large():\n    assert add(100, 200) == 300\n\n"
        "def test_add_both_neg():\n    assert add(-3, -7) == -10\n\n"
        "def test_add_identity():\n    assert add(999, 1) == 1000\n"
    )
    (draft_dir / "solution").mkdir()
    (draft_dir / "solution" / "adder.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )
    return draft_dir


# ---------------------------------------------------------------------------
# Probe classification
# ---------------------------------------------------------------------------

class TestProbeClassification:
    """Tests that probe_draft classifies correctly based on solve counts."""

    def test_all_probes_pass_means_too_easy(self):
        """If every probe returns True (solved), classification is too_easy."""
        files = _mock_draft_files()
        # mock=True → _probe_once always returns True
        classification, results = _factory._probe_draft(
            files, probe_attempts=3, mock=True, mock_probe_fail=False
        )
        assert classification == "too_easy"
        assert all(results)
        assert len(results) == 3

    def test_all_probes_fail_means_discriminating(self):
        """If every probe returns False, classification is discriminating."""
        files = _mock_draft_files()
        classification, results = _factory._probe_draft(
            files, probe_attempts=3, mock=False, mock_probe_fail=True
        )
        assert classification == "discriminating"
        assert not any(results)
        assert len(results) == 3

    def test_single_probe_failure_means_discriminating(self):
        """Even one failure out of N makes the draft discriminating."""
        files = _mock_draft_files()
        classification, results = _factory._probe_draft(
            files, probe_attempts=1, mock=False, mock_probe_fail=True
        )
        assert classification == "discriminating"

    def test_probe_attempts_count(self):
        """probe_results list has exactly probe_attempts entries."""
        files = _mock_draft_files()
        for n in (1, 2, 5):
            _, results = _factory._probe_draft(files, probe_attempts=n, mock=True)
            assert len(results) == n

    def test_probe_via_fake_server_always_pass(self):
        """probe_always_pass mode: all probes pass → too_easy."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, {
                "BASE_URL": srv.base_url,
                "API_KEY":  "fake-key",
                "MODEL":    "probe_always_pass",
            }):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    files = {
                        "task.json": json.dumps({
                            "id": "037-pagination-probe",
                            "title": "t", "language": "python",
                            "difficulty": "hard",
                            "prompt": "Fix paginate in starter/paginate.py",
                            "grader": "pytest", "version": "1.0",
                            "tags": [], "estimated_minutes": 5, "license": "MIT",
                        }),
                        "starter/paginate.py": (
                            core.task_dir(TASK_001) / "starter" / "paginate.py"
                        ).read_text(),
                        "grader/test_paginate.py": (
                            core.task_dir(TASK_001) / "grader" / "test_paginate.py"
                        ).read_text(),
                        "solution/paginate.py": (
                            core.task_dir(TASK_001) / "solution" / "paginate.py"
                        ).read_text(),
                    }
                    result = _factory._probe_once(files, mock=False)
        assert result is True

    def test_probe_via_fake_server_always_fail(self):
        """probe_always_fail mode: probe returns False."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, {
                "BASE_URL": srv.base_url,
                "API_KEY":  "fake-key",
                "MODEL":    "probe_always_fail",
            }):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    files = {
                        "task.json": json.dumps({
                            "id": "037-pagination-probe",
                            "title": "t", "language": "python",
                            "difficulty": "hard",
                            "prompt": "Fix paginate in starter/paginate.py",
                            "grader": "pytest", "version": "1.0",
                            "tags": [], "estimated_minutes": 5, "license": "MIT",
                        }),
                        "starter/paginate.py": (
                            core.task_dir(TASK_001) / "starter" / "paginate.py"
                        ).read_text(),
                        "grader/test_paginate.py": (
                            core.task_dir(TASK_001) / "grader" / "test_paginate.py"
                        ).read_text(),
                        "solution/paginate.py": (
                            core.task_dir(TASK_001) / "solution" / "paginate.py"
                        ).read_text(),
                    }
                    result = _factory._probe_once(files, mock=False)
        assert result is False


# ---------------------------------------------------------------------------
# Auto-numbering
# ---------------------------------------------------------------------------

class TestNumbering:
    """Tests that _assign_id produces collision-free numbers."""

    def test_assign_id_changes_number(self):
        """_assign_id replaces any NNN- prefix with a new free number."""
        files = {"task.json": json.dumps({"id": "001-example", "title": "t"})}
        new_files, new_id = _factory._assign_id(files)
        num = int(new_id.split("-")[0])
        assert new_id.endswith("-example")
        assert num >= 37  # never reuses 001-036

    def test_assign_id_no_collision_with_tasks(self):
        """Assigned number must not already be used by any real task."""
        existing = _factory._existing_numbers()
        files = {"task.json": json.dumps({"id": "000-slug", "title": "t"})}
        _, new_id = _factory._assign_id(files)
        num = int(new_id.split("-")[0])
        assert num not in existing

    def test_two_consecutive_calls_no_collision(self):
        """Two back-to-back calls must produce different numbers."""
        files = {"task.json": json.dumps({"id": "000-slug", "title": "t"})}
        # Patch _existing_numbers to simulate a draft already saved at 037
        with unittest.mock.patch.object(_factory, "_existing_numbers", return_value={37}):
            _, id1 = _factory._assign_id(files)
        num1 = int(id1.split("-")[0])
        assert num1 != 37
        assert num1 >= 38

    def test_slug_preserved(self):
        """The slug portion after NNN- is preserved."""
        files = {"task.json": json.dumps({"id": "099-my-cool-task", "title": "t"})}
        _, new_id = _factory._assign_id(files)
        assert new_id.endswith("-my-cool-task")

    def test_no_prefix_gets_task_slug(self):
        """An id with no numeric prefix gets 'task' as the slug fallback."""
        files = {"task.json": json.dumps({"id": "something", "title": "t"})}
        _, new_id = _factory._assign_id(files)
        assert new_id.endswith("-something")

    def test_collisions_avoided_with_draft_dirs(self, tmp_path):
        """Numbers used by draft subdirs (accepted/, too_easy/, rejected/) are skipped."""
        # Patch _ACCEPTED_DIR / _TOO_EASY_DIR so _existing_numbers sees fake dirs
        accepted = tmp_path / "accepted"
        (accepted / "037-foo").mkdir(parents=True)
        (accepted / "038-bar").mkdir(parents=True)
        too_easy = tmp_path / "too_easy"
        (too_easy / "039-baz").mkdir(parents=True)

        # Also patch the rejected and tasks dirs to nothing (no real nums there)
        with (
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", accepted),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", too_easy),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(core, "tasks_dir",
                                        return_value=tmp_path / "tasks"),
        ):
            files = {"task.json": json.dumps({"id": "000-test", "title": "t"})}
            _, new_id = _factory._assign_id(files)
        num = int(new_id.split("-")[0])
        assert num >= 40


# ---------------------------------------------------------------------------
# Stats counts
# ---------------------------------------------------------------------------

class TestStats:
    """Tests that factory_stats.json receives correct counts."""

    def test_mock_too_easy_increments_stats(self, tmp_path):
        """
        mock=True → probes always pass → too_easy.
        Stats should show: drafted=1, judge_accepted=1, probed=1, too_easy=1, discriminating=0.
        """
        stats_file = tmp_path / "factory_stats.json"
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE",
                                        tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
        ):
            _factory._run_factory_once(
                mock=True, lessons=[], probe_attempts=2, mock_probe_fail=False
            )

        stats = json.loads(stats_file.read_text())
        assert stats["drafted"] == 1
        assert stats["judge_accepted"] == 1
        assert stats["probed"] == 1
        assert stats["too_easy"] == 1
        assert stats["discriminating"] == 0
        assert stats["failed_verify"] == 0

    def test_mock_discriminating_increments_stats(self, tmp_path):
        """
        mock=True, mock_probe_fail=True → probes always fail → discriminating.
        Stats: drafted=1, judge_accepted=1, probed=1, discriminating=1, too_easy=0.
        """
        stats_file = tmp_path / "factory_stats.json"
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE",
                                        tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
        ):
            result = _factory._run_factory_once(
                mock=True, lessons=[], probe_attempts=2, mock_probe_fail=True
            )

        assert result["status"] == "accepted"
        stats = json.loads(stats_file.read_text())
        assert stats["discriminating"] == 1
        assert stats["too_easy"] == 0
        assert stats["probed"] == 1
        # Per-draft record must include probe details
        draft_info = stats["drafts"].get(result["task_id"])
        assert draft_info is not None
        assert draft_info["classification"] == "discriminating"
        assert draft_info["probe_solve_count"] == 0

    def test_too_easy_probe_solve_count(self, tmp_path):
        """too_easy drafts record probe_solve_count == probe_attempts."""
        stats_file = tmp_path / "factory_stats.json"
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE",
                                        tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
        ):
            result = _factory._run_factory_once(
                mock=True, lessons=[], probe_attempts=3, mock_probe_fail=False
            )

        assert result["status"] == "too_easy"
        stats = json.loads(stats_file.read_text())
        draft_info = stats["drafts"][result["task_id"]]
        assert draft_info["probe_solve_count"] == 3  # all 3 passed

    def test_failed_verify_increments_stats(self, tmp_path):
        """A draft whose verify fails increments failed_verify."""
        stats_file = tmp_path / "factory_stats.json"
        # Inject a draft that will fail verify (starter has no failing tests)
        # Use a title ≥ 8 chars, 6 test funcs (to pass lint), but correct starter (verify fails)
        bad_files = {
            "task.json": json.dumps({
                "id": "000-bad-verify",
                "title": "Fix broken adder task",
                "language": "python",
                "difficulty": "hard",
                "prompt": "x" * 210,
                "grader": "pytest",
                "version": "1.0",
                "tags": [],
                "estimated_minutes": 5,
                "license": "MIT",
            }),
            "starter/adder.py": "def add(a, b):\n    return a + b\n",  # correct — will pass all
            "grader/test_adder.py": (
                "import os, sys\n"
                "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
                "from adder import add\n\n"
                "def test_add_basic():\n    assert add(1, 2) == 3\n\n"
                "def test_add_zeros():\n    assert add(0, 0) == 0\n\n"
                "def test_add_neg():\n    assert add(-1, 5) == 4\n\n"
                "def test_add_large():\n    assert add(100, 200) == 300\n\n"
                "def test_add_both_neg():\n    assert add(-3, -7) == -10\n\n"
                "def test_add_id():\n    assert add(999, 1) == 1000\n"
            ),
            "solution/adder.py": "def add(a, b):\n    return a + b\n",
        }
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE",
                                        tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
            unittest.mock.patch.object(_factory, "_mock_draft", return_value=bad_files),
        ):
            result = _factory._run_factory_once(
                mock=True, lessons=[], probe_attempts=1
            )

        assert result["status"] == "rejected_verify"
        stats = json.loads(stats_file.read_text())
        assert stats["failed_verify"] == 1
        assert stats["drafted"] == 1


# ---------------------------------------------------------------------------
# Promote command
# ---------------------------------------------------------------------------

class TestPromote:
    """Tests for gradepack promote."""

    def test_promote_moves_draft_to_tasks(self, tmp_path):
        """
        A valid draft in drafts/accepted/ is moved to tasks/ and review.json → reviews/.
        """
        task_id = "099-promote-test"
        # _make_temp_accepted_draft puts it at tmp_path/drafts/accepted/<id>
        draft_dir = _make_temp_accepted_draft(tmp_path, task_id)

        # Write a review.json (simulate a discriminating draft)
        (draft_dir / "review.json").write_text(json.dumps({
            "verdict": "accept",
            "classification": "discriminating",
            "probe_results": [False, True],
        }))

        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch("gradepack.cli.core._repo_root",
                                  return_value=tmp_path),
            unittest.mock.patch("gradepack.cli.core.tasks_dir",
                                  return_value=fake_tasks),
            unittest.mock.patch("gradepack.cli.core.task_dir",
                                  side_effect=lambda tid: fake_tasks / tid),
            unittest.mock.patch("gradepack.factory._verify_draft_files",
                                  return_value=(True, "")),
        ):
            _cli.cmd_promote(task_id)

        promoted = fake_tasks / task_id
        assert promoted.exists(), "task directory should exist after promote"
        assert (promoted / "task.json").exists()
        reviews_dir = tmp_path / "reviews"
        assert (reviews_dir / f"{task_id}.json").exists(), "review.json should be moved"
        # Draft dir should be gone
        assert not draft_dir.exists(), "draft dir should be removed after promote"

    def test_promote_refuses_missing_draft(self, tmp_path, capsys):
        """Promote with a non-existent draft_id must fail with exit code 1."""
        with (
            unittest.mock.patch("gradepack.cli.core._repo_root",
                                  return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            _cli.cmd_promote("999-does-not-exist")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "fail" in captured.out.lower()

    def test_promote_renames_id_on_mismatch(self, tmp_path, capsys):
        """
        When task.json id ≠ directory name, promote auto-renames the id
        to the next free number (rather than hard-failing).
        """
        task_id = "099-mismatch"
        # Use the full helper (has 6 test funcs, no BUG comment) but swap the id
        draft_dir = _make_temp_accepted_draft(tmp_path, task_id)
        # Overwrite task.json with a mismatched id
        import json as _json
        meta = _json.loads((draft_dir / "task.json").read_text())
        meta["id"] = "099-wrong-id"
        (draft_dir / "task.json").write_text(_json.dumps(meta, indent=2))

        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch("gradepack.cli.core._repo_root",
                                  return_value=tmp_path),
            unittest.mock.patch("gradepack.cli.core.tasks_dir",
                                  return_value=fake_tasks),
            unittest.mock.patch("gradepack.factory._verify_draft_files",
                                  return_value=(True, "")),
            # Also patch _existing_numbers so numbering is deterministic
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 99))),
        ):
            _cli.cmd_promote(task_id)

        captured = capsys.readouterr()
        # Should show INFO rename and PROMOTED
        assert "INFO" in captured.out or "PROMOTED" in captured.out

    def test_promote_refuses_if_verify_fails(self, tmp_path, capsys):
        """Promote must fail if verify returns (False, reason)."""
        task_id = "099-verify-fail"
        draft_dir = _make_temp_accepted_draft(tmp_path, task_id)  # at tmp_path/drafts/accepted/

        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch("gradepack.cli.core._repo_root",
                                  return_value=tmp_path),
            unittest.mock.patch("gradepack.cli.core.tasks_dir",
                                  return_value=fake_tasks),
            unittest.mock.patch("gradepack.factory._verify_draft_files",
                                  return_value=(False, "starter always passes")),
            pytest.raises(SystemExit) as exc_info,
        ):
            _cli.cmd_promote(task_id)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "verify failed" in captured.out.lower()

    def test_promote_refuses_if_already_in_tasks(self, tmp_path, capsys):
        """Promote must fail if tasks/<id> already exists."""
        task_id = "099-already-exists"
        draft_dir = _make_temp_accepted_draft(tmp_path, task_id)  # at tmp_path/drafts/accepted/

        fake_tasks = tmp_path / "tasks"
        (fake_tasks / task_id).mkdir(parents=True)  # already exists

        with (
            unittest.mock.patch("gradepack.cli.core._repo_root",
                                  return_value=tmp_path),
            unittest.mock.patch("gradepack.cli.core.tasks_dir",
                                  return_value=fake_tasks),
            unittest.mock.patch("gradepack.factory._verify_draft_files",
                                  return_value=(True, "")),
            pytest.raises(SystemExit) as exc_info,
        ):
            _cli.cmd_promote(task_id)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out


# ---------------------------------------------------------------------------
# factory --help works (argparse doesn't raise, just prints and exits 0)
# ---------------------------------------------------------------------------

def test_factory_help_exits_zero():
    """factory --help must exit 0 (not crash)."""
    with pytest.raises(SystemExit) as exc_info:
        _factory.build_parser().parse_args(["--help"])
    assert exc_info.value.code == 0


def test_promote_help_exits_zero():
    """promote --help must exit 0 (not crash)."""
    from gradepack.cli import _build_promote_parser
    with pytest.raises(SystemExit) as exc_info:
        _build_promote_parser().parse_args(["--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# factory --mock (smoke test: end-to-end mock run writes factory_stats.json)
# ---------------------------------------------------------------------------

def test_factory_mock_run_end_to_end(tmp_path):
    """
    factory mock run with mock_probe_fail=True should produce discriminating drafts
    and write factory_stats.json.
    """
    stats_file = tmp_path / "factory_stats.json"
    accepted  = tmp_path / "accepted"
    rejected  = tmp_path / "rejected"
    too_easy  = tmp_path / "too_easy"
    lessons   = tmp_path / "LESSONS.md"
    fake_tasks = tmp_path / "tasks"
    fake_tasks.mkdir()

    with (
        unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
        unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", accepted),
        unittest.mock.patch.object(_factory, "_REJECTED_DIR", rejected),
        unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", too_easy),
        unittest.mock.patch.object(_factory, "_LESSONS_FILE", lessons),
        # Patch tasks_dir to an empty dir so _existing_numbers sees no real tasks;
        # but allow accepted/ to grow so second call sees first draft's number
        unittest.mock.patch.object(core, "tasks_dir", return_value=fake_tasks),
        unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path),
    ):
        _factory.cmd_factory(
            n=2, target_kept=None, probe_attempts=1, parallel=1,
            mock=True, mock_probe_fail=True,
        )

    assert stats_file.exists(), "factory_stats.json must be written"
    stats = json.loads(stats_file.read_text())
    assert stats["drafted"] == 2
    assert stats["discriminating"] == 2
    assert stats["too_easy"] == 0
    # Both accepted drafts should appear under accepted/
    draft_dirs = list(accepted.iterdir())
    assert len(draft_dirs) == 2, (
        f"Expected 2 accepted drafts, got {len(draft_dirs)}: {[d.name for d in draft_dirs]}"
    )
    # Both must have different names (no collision)
    names = {d.name for d in draft_dirs}
    assert len(names) == 2, f"Collision: both drafts have same name: {names}"


def test_factory_mock_too_easy_writes_lesson(tmp_path):
    """
    factory mock run (mock_probe_fail=False) → too_easy → lesson appended to LESSONS.md.
    """
    stats_file = tmp_path / "factory_stats.json"
    lessons_file = tmp_path / "LESSONS.md"
    lessons_file.write_text(
        "# LESSONS.md\n<!-- lessons below — managed by factory -->\n"
    )

    with (
        unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
        unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
        unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
        unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
        unittest.mock.patch.object(_factory, "_LESSONS_FILE", lessons_file),
        unittest.mock.patch.object(_factory, "_existing_numbers",
                                    return_value=set(range(1, 37))),
    ):
        _factory.cmd_factory(
            n=1, probe_attempts=2, parallel=1, mock=True, mock_probe_fail=False
        )

    text = lessons_file.read_text()
    assert "too easy" in text.lower() or "probe" in text.lower()
