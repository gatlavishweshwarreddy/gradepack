"""
tests/test_new_features.py — tests for all new features from Part 1–3:

  - lint_draft() checks (Part 1a)
  - lint stage in factory_stats and funnel (Part 1b)
  - lint-drafts CLI command (Part 1c)
  - domain rotation (Part 1d)
  - mock-data guard in publish (Part 2d)
  - promote lint / title / id-rename checks (Part 2e)
  - resume / progress file (Part 2f)
  - difficulty_warnings in validate (Part 2g)
  - bench mock-data file naming warning (Part 2d)
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

from gradepack import factory as _factory
from gradepack import core
from gradepack import cli as _cli
from gradepack.validate import difficulty_warnings, validate_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_draft_files(
    title="Fix the adder",
    prompt="x" * 200,
    grader_funcs=6,
    bug_comment="",
    time_in_grader=False,
    private_attr_in_grader="",
    extra_prompt="",
) -> dict[str, str]:
    """Return a files dict that passes all lint checks by default."""
    grader_code = (
        "import os, sys\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
        "from adder import add\n\n"
    )
    for i in range(grader_funcs):
        grader_code += f"def test_add_{i}():\n    assert add({i}, 0) == {i}\n\n"
    if time_in_grader:
        grader_code += "import time\ndef test_timing():\n    t = time.time()\n    assert t > 0\n"
    if private_attr_in_grader:
        grader_code += f"def test_private():\n    obj = add\n    x = obj.{private_attr_in_grader}\n"

    starter_code = f"def add(a, b):\n    return a - b{' # ' + bug_comment if bug_comment else ''}\n"

    meta = {
        "id": "000-test",
        "title": title,
        "language": "python",
        "difficulty": "hard",
        "prompt": prompt + extra_prompt,
        "grader": "pytest",
        "version": "1.0",
        "tags": [],
        "estimated_minutes": 5,
        "license": "MIT",
    }
    return {
        "task.json": json.dumps(meta, indent=2),
        "starter/adder.py": starter_code,
        "grader/test_adder.py": grader_code,
        "solution/adder.py": "def add(a, b):\n    return a + b\n",
    }


# ---------------------------------------------------------------------------
# Part 1a: lint_draft checks
# ---------------------------------------------------------------------------

class TestLintDraft:

    def test_clean_draft_passes(self):
        """A well-formed draft must return no lint problems."""
        files = _clean_draft_files()
        problems = _factory.lint_draft(files)
        assert problems == []

    def test_short_title_rejected(self):
        """Title shorter than 8 chars must produce a short_title lint error."""
        files = _clean_draft_files(title="Short")
        problems = _factory.lint_draft(files)
        assert any("short_title" in p for p in problems)

    def test_missing_title_rejected(self):
        """Missing title must produce a short_title lint error."""
        files = _clean_draft_files(title="")
        problems = _factory.lint_draft(files)
        assert any("short_title" in p for p in problems)

    def test_long_title_passes(self):
        """Title ≥ 8 chars must not trigger short_title."""
        files = _clean_draft_files(title="Fix the broken adder function")
        problems = _factory.lint_draft(files)
        assert not any("short_title" in p for p in problems)

    def test_bug_comment_rejected(self):
        """Starter with '# BUG' comment must produce a bug_comment lint error."""
        files = _clean_draft_files(bug_comment="BUG")
        problems = _factory.lint_draft(files)
        assert any("bug_comment" in p for p in problems)

    def test_fixme_comment_rejected(self):
        """Starter with 'FIXME' must be rejected."""
        files = _clean_draft_files(bug_comment="FIXME")
        problems = _factory.lint_draft(files)
        assert any("bug_comment" in p for p in problems)

    def test_intentionally_in_string_rejected(self):
        """Starter with 'intentionally' in text must be rejected."""
        files = _clean_draft_files()
        files["starter/adder.py"] = 'def add(a, b):\n    # intentionally broken\n    return a - b\n'
        problems = _factory.lint_draft(files)
        assert any("bug_comment" in p for p in problems)

    def test_clean_starter_passes(self):
        """Starter without any hint words must pass bug_comment check."""
        files = _clean_draft_files(bug_comment="")
        problems = _factory.lint_draft(files)
        assert not any("bug_comment" in p for p in problems)

    def test_time_assertion_rejected(self):
        """Grader that uses time.time() must produce time_assertion lint error."""
        files = _clean_draft_files(time_in_grader=True)
        problems = _factory.lint_draft(files)
        assert any("time_assertion" in p for p in problems)

    def test_no_time_assertion_passes(self):
        """Clean grader must not trigger time_assertion."""
        files = _clean_draft_files(time_in_grader=False)
        problems = _factory.lint_draft(files)
        assert not any("time_assertion" in p for p in problems)

    def test_prompt_too_long_rejected(self):
        """Prompt longer than 1500 chars must produce a prompt_too_long lint error."""
        files = _clean_draft_files(prompt="x" * 1501)
        problems = _factory.lint_draft(files)
        assert any("prompt_too_long" in p for p in problems)

    def test_prompt_exactly_1500_passes(self):
        """Prompt of exactly 1500 chars must pass."""
        files = _clean_draft_files(prompt="x" * 1500)
        problems = _factory.lint_draft(files)
        assert not any("prompt_too_long" in p for p in problems)

    def test_few_tests_rejected(self):
        """Grader with < 6 test functions must produce a few_tests lint error."""
        files = _clean_draft_files(grader_funcs=3)
        problems = _factory.lint_draft(files)
        assert any("few_tests" in p for p in problems)

    def test_exactly_6_tests_passes(self):
        """Grader with exactly 6 test functions must pass."""
        files = _clean_draft_files(grader_funcs=6)
        problems = _factory.lint_draft(files)
        assert not any("few_tests" in p for p in problems)

    def test_private_attr_not_in_prompt_rejected(self):
        """Grader accessing _secret attr not mentioned in prompt must fail."""
        files = _clean_draft_files()
        files["grader/test_adder.py"] = (
            "import os, sys\n"
            "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
            "from adder import add\n\n"
            "def test_add_0():\n    assert add(0,0)==0\n\n"
            "def test_add_1():\n    assert add(1,2)==3\n\n"
            "def test_add_2():\n    assert add(2,2)==4\n\n"
            "def test_add_3():\n    assert add(3,0)==3\n\n"
            "def test_add_4():\n    assert add(4,0)==4\n\n"
            "def test_private():\n    obj = add\n    x = obj._secret_state\n"
        )
        problems = _factory.lint_draft(files)
        assert any("private_attr" in p for p in problems)
        assert any("_secret_state" in p for p in problems)

    def test_private_attr_in_prompt_allowed(self):
        """Grader accessing _secret_state is allowed if mentioned in prompt."""
        files = _clean_draft_files(prompt="x" * 180 + " _secret_state check")
        files["grader/test_adder.py"] = (
            "import os, sys\n"
            "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
            "from adder import add\n\n"
            "def test_add_0():\n    assert add(0,0)==0\n\n"
            "def test_add_1():\n    assert add(1,2)==3\n\n"
            "def test_add_2():\n    assert add(2,2)==4\n\n"
            "def test_add_3():\n    assert add(3,0)==3\n\n"
            "def test_add_4():\n    assert add(4,0)==4\n\n"
            "def test_private():\n    obj = add\n    x = obj._secret_state\n"
        )
        problems = _factory.lint_draft(files)
        assert not any("private_attr" in p for p in problems)

    def test_dunder_attrs_allowed(self):
        """Dunder attributes like __len__ must not trigger private_attr."""
        files = _clean_draft_files()
        files["grader/test_adder.py"] = (
            "import os, sys\n"
            "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))\n"
            "from adder import add\n\n"
            "def test_add_0():\n    assert add(0,0)==0\n\n"
            "def test_add_1():\n    assert add(1,2)==3\n\n"
            "def test_add_2():\n    assert add(2,2)==4\n\n"
            "def test_add_3():\n    assert add(3,0)==3\n\n"
            "def test_add_4():\n    assert add(4,0)==4\n\n"
            "def test_dunder():\n    assert add.__name__ == 'add'\n"
        )
        problems = _factory.lint_draft(files)
        assert not any("private_attr" in p for p in problems)

    def test_multiple_problems_returned(self):
        """Multiple lint issues must all be reported."""
        files = _clean_draft_files(title="X", grader_funcs=2)
        problems = _factory.lint_draft(files)
        assert len(problems) >= 2


# ---------------------------------------------------------------------------
# Part 1b: lint stage in factory_stats
# ---------------------------------------------------------------------------

class TestLintStats:

    def test_lint_rejection_increments_lint_rejected(self, tmp_path):
        """A draft rejected by lint must increment lint_rejected in stats."""
        stats_file = tmp_path / "factory_stats.json"
        # Mock draft returns a draft with short title (will fail lint)
        bad_files = _clean_draft_files(title="Bad")  # 3 chars < 8
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
            unittest.mock.patch.object(_factory, "_mock_draft", return_value=bad_files),
        ):
            result = _factory._run_factory_once(
                mock=True, lessons=[], probe_attempts=1
            )

        assert result["status"] == "rejected_lint"
        stats = json.loads(stats_file.read_text())
        assert stats.get("lint_rejected", 0) == 1
        assert stats["drafted"] == 1

    def test_lint_rejection_reason_tracked(self, tmp_path):
        """lint_fail_reasons in stats must track which reasons were hit."""
        stats_file = tmp_path / "factory_stats.json"
        bad_files = _clean_draft_files(title="Bad", grader_funcs=2)
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
            unittest.mock.patch.object(_factory, "_mock_draft", return_value=bad_files),
        ):
            _factory._run_factory_once(mock=True, lessons=[], probe_attempts=1)

        stats = json.loads(stats_file.read_text())
        lfr = stats.get("lint_fail_reasons", {})
        # Both short_title and few_tests should be incremented
        assert lfr.get("short_title", 0) >= 1
        assert lfr.get("few_tests", 0) >= 1

    def test_lint_rejection_appends_lesson(self, tmp_path):
        """A lint rejection must append at least one lesson to LESSONS.md."""
        stats_file = tmp_path / "factory_stats.json"
        lessons_file = tmp_path / "LESSONS.md"
        lessons_file.write_text("# LESSONS\n<!-- lessons below -->\n")
        bad_files = _clean_draft_files(title="Bad")
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", lessons_file),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
            unittest.mock.patch.object(_factory, "_mock_draft", return_value=bad_files),
        ):
            _factory._run_factory_once(mock=True, lessons=[], probe_attempts=1)

        text = lessons_file.read_text()
        assert "- " in text  # at least one lesson appended

    def test_lint_pass_not_counted(self, tmp_path):
        """A clean draft that passes lint must not increment lint_rejected."""
        stats_file = tmp_path / "factory_stats.json"
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
        ):
            # Default mock draft passes lint
            _factory._run_factory_once(mock=True, lessons=[], probe_attempts=1)

        stats = json.loads(stats_file.read_text())
        assert stats.get("lint_rejected", 0) == 0


# ---------------------------------------------------------------------------
# Part 1c: lint-drafts CLI command
# ---------------------------------------------------------------------------

class TestLintDraftsCLI:

    def test_lint_drafts_cmd_runs_on_empty_dirs(self, tmp_path, capsys):
        """lint-drafts with empty accepted/too_easy prints no-drafts message."""
        with (
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
        ):
            _factory.cmd_lint_drafts()
        captured = capsys.readouterr()
        assert "No drafts" in captured.out

    def test_lint_drafts_cmd_pass(self, tmp_path, capsys):
        """A clean draft under accepted/ shows PASS."""
        accepted = tmp_path / "accepted"
        accepted.mkdir(parents=True)
        # Write a clean draft
        d = accepted / "037-clean-draft"
        d.mkdir()
        files = _clean_draft_files()
        (d / "task.json").write_text(files["task.json"])
        (d / "starter").mkdir()
        (d / "starter" / "adder.py").write_text(files["starter/adder.py"])
        (d / "grader").mkdir()
        (d / "grader" / "test_adder.py").write_text(files["grader/test_adder.py"])
        (d / "solution").mkdir()
        (d / "solution" / "adder.py").write_text(files["solution/adder.py"])

        with (
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", accepted),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
        ):
            _factory.cmd_lint_drafts()
        captured = capsys.readouterr()
        assert "PASS" in captured.out
        assert "037-clean-draft" in captured.out

    def test_lint_drafts_cmd_fail(self, tmp_path, capsys):
        """A bad draft under accepted/ shows FAIL."""
        accepted = tmp_path / "accepted"
        accepted.mkdir(parents=True)
        d = accepted / "037-bad-draft"
        d.mkdir()
        # Write a bad draft (short title, few tests)
        files = _clean_draft_files(title="Bad", grader_funcs=2)
        (d / "task.json").write_text(files["task.json"])
        (d / "starter").mkdir()
        (d / "starter" / "adder.py").write_text(files["starter/adder.py"])
        (d / "grader").mkdir()
        (d / "grader" / "test_adder.py").write_text(files["grader/test_adder.py"])
        (d / "solution").mkdir()
        (d / "solution" / "adder.py").write_text(files["solution/adder.py"])

        with (
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", accepted),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
        ):
            _factory.cmd_lint_drafts()
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "037-bad-draft" in captured.out

    def test_cli_lint_drafts_dispatch(self, capsys):
        """gradepack lint-drafts dispatches through main()."""
        with (
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR",
                                        pathlib.Path("/nonexistent/accepted")),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR",
                                        pathlib.Path("/nonexistent/too_easy")),
        ):
            _cli.main(["lint-drafts"])
        captured = capsys.readouterr()
        assert "No drafts" in captured.out or "checked" in captured.out


# ---------------------------------------------------------------------------
# Part 1d: domain rotation
# ---------------------------------------------------------------------------

class TestDomainRotation:

    def test_domains_list_has_14_items(self):
        """_DOMAINS must have at least 14 entries."""
        assert len(_factory._DOMAINS) >= 14

    def test_next_domain_cycles(self):
        """_next_domain cycles through all domains."""
        seen = set()
        for _ in range(len(_factory._DOMAINS)):
            seen.add(_factory._next_domain())
        assert len(seen) == len(_factory._DOMAINS)

    def test_next_domain_wraps_around(self):
        """After cycling all domains, wraps back to start."""
        n = len(_factory._DOMAINS)
        first = _factory._DOMAINS[0]
        # Call exactly n times to reset cycle
        with _factory._DOMAIN_COUNTER_LOCK:
            _factory._domain_counter = 0
        domains = [_factory._next_domain() for _ in range(n + 1)]
        assert domains[0] == domains[n], "After n+1 calls, should wrap around"

    def test_mock_draft_includes_domain_in_tags(self):
        """_mock_draft with a domain stores it in task.json tags."""
        files = _factory._mock_draft(domain="string processing")
        meta = json.loads(files["task.json"])
        assert "string processing" in meta.get("tags", [])

    def test_run_factory_once_stores_domain_in_stats(self, tmp_path):
        """After a successful run, domain is stored in per-draft stats."""
        stats_file = tmp_path / "factory_stats.json"
        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_existing_numbers",
                                        return_value=set(range(1, 37))),
        ):
            result = _factory._run_factory_once(
                mock=True, lessons=[], probe_attempts=1, mock_probe_fail=True,
                domain="state machines",
            )

        assert result.get("domain") == "state machines"
        stats = json.loads(stats_file.read_text())
        task_id = result.get("task_id", "")
        draft_info = stats.get("drafts", {}).get(task_id, {})
        assert draft_info.get("domain") == "state machines"


# ---------------------------------------------------------------------------
# Part 2d: mock-data guard
# ---------------------------------------------------------------------------

class TestMockDataGuard:

    def test_publish_refuses_records_with_mock_model(self, tmp_path, capsys):
        """_publish must refuse if any record has model containing 'mock'."""
        from gradepack import bench as _bench
        results_file = tmp_path / "real-model.json"
        records = [{"model": "mock-fast", "provider": "test", "score": 1.0, "task_id": "x"}]
        results_file.write_text(json.dumps(records))

        orig = _bench.core._repo_root
        _bench.core._repo_root = lambda: tmp_path
        try:
            _bench._publish(results_file, include_mock=False)
        finally:
            _bench.core._repo_root = orig

        captured = capsys.readouterr()
        assert "Refusing" in captured.out or "mock" in captured.out.lower()
        # File must NOT be published
        assert not (tmp_path / "docs" / "results" / "real-model.json").exists()

    def test_publish_allows_mock_records_with_include_mock(self, tmp_path):
        """_publish with include_mock=True must publish files with mock records."""
        from gradepack import bench as _bench
        results_file = tmp_path / "mock-model.json"
        records = [{"model": "mock", "provider": "mock", "score": 1.0, "task_id": "x"}]
        results_file.write_text(json.dumps(records))

        orig = _bench.core._repo_root
        _bench.core._repo_root = lambda: tmp_path
        try:
            _bench._publish(results_file, include_mock=True)
        finally:
            _bench.core._repo_root = orig

        assert (tmp_path / "docs" / "results" / "mock-model.json").exists()

    def test_bench_mock_run_warns_if_not_named_mock(self, tmp_path, capsys):
        """bench --mock with model not starting 'mock' should print a warning."""
        from gradepack import bench as _bench
        with (
            unittest.mock.patch("gradepack.bench.core._repo_root", return_value=tmp_path),
            unittest.mock.patch("gradepack.bench.core.all_task_ids",
                                 return_value=["001-pagination-off-by-one"]),
        ):
            _bench.cmd_bench(
                model="my-model",
                mock=True,
                mock_pass=True,
                task_filter=["001-pagination-off-by-one"],
                publish=False,
            )
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "mock" in captured.out.lower()

    def test_bench_mock_run_no_warning_if_named_mock(self, tmp_path, capsys):
        """bench --mock with model='mock-x' must NOT print the warning."""
        from gradepack import bench as _bench
        with (
            unittest.mock.patch("gradepack.bench.core._repo_root", return_value=tmp_path),
            unittest.mock.patch("gradepack.bench.core.all_task_ids",
                                 return_value=["001-pagination-off-by-one"]),
        ):
            _bench.cmd_bench(
                model="mock-x",
                mock=True,
                mock_pass=True,
                task_filter=["001-pagination-off-by-one"],
                publish=False,
            )
        captured = capsys.readouterr()
        # No "WARNING: ... does not start with 'mock'" message
        assert "does not start" not in captured.out


# ---------------------------------------------------------------------------
# Part 2e: promote lint / title / id-rename checks
# ---------------------------------------------------------------------------

class TestPromoteNewChecks:

    def _make_draft(self, tmp_path: pathlib.Path, task_id: str,
                    title="Fix the adder function", grader_funcs=6,
                    bug_comment="") -> pathlib.Path:
        """Make a minimal valid draft in tmp_path/drafts/accepted/<task_id>."""
        draft_dir = tmp_path / "drafts" / "accepted" / task_id
        draft_dir.mkdir(parents=True)
        files = _clean_draft_files(
            title=title,
            grader_funcs=grader_funcs,
            bug_comment=bug_comment,
        )
        meta = json.loads(files["task.json"])
        meta["id"] = task_id
        (draft_dir / "task.json").write_text(json.dumps(meta, indent=2))
        (draft_dir / "starter").mkdir()
        (draft_dir / "starter" / "adder.py").write_text(files["starter/adder.py"])
        (draft_dir / "grader").mkdir()
        (draft_dir / "grader" / "test_adder.py").write_text(files["grader/test_adder.py"])
        (draft_dir / "solution").mkdir()
        (draft_dir / "solution" / "adder.py").write_text(files["solution/adder.py"])
        return draft_dir

    def test_promote_refuses_no_title(self, tmp_path, capsys):
        """promote must fail if task.json has no title."""
        task_id = "099-no-title"
        draft_dir = self._make_draft(tmp_path, task_id)
        # Overwrite task.json with missing title
        meta = json.loads((draft_dir / "task.json").read_text())
        meta["title"] = ""
        (draft_dir / "task.json").write_text(json.dumps(meta, indent=2))

        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch("gradepack.cli.core._repo_root", return_value=tmp_path),
            unittest.mock.patch("gradepack.cli.core.tasks_dir", return_value=fake_tasks),
            pytest.raises(SystemExit) as exc_info,
        ):
            _cli.cmd_promote(task_id)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "title" in captured.out.lower()

    def test_promote_refuses_lint_failure(self, tmp_path, capsys):
        """promote must fail if lint_draft reports problems."""
        task_id = "099-lint-fail"
        draft_dir = self._make_draft(tmp_path, task_id, grader_funcs=2)

        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch("gradepack.cli.core._repo_root", return_value=tmp_path),
            unittest.mock.patch("gradepack.cli.core.tasks_dir", return_value=fake_tasks),
            pytest.raises(SystemExit) as exc_info,
        ):
            _cli.cmd_promote(task_id)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "lint" in captured.out.lower() or "few_tests" in captured.out

    def test_promote_lint_pass_proceeds(self, tmp_path, capsys):
        """promote continues past lint when draft is clean."""
        task_id = "099-lint-pass"
        self._make_draft(tmp_path, task_id)

        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch("gradepack.cli.core._repo_root", return_value=tmp_path),
            unittest.mock.patch("gradepack.cli.core.tasks_dir", return_value=fake_tasks),
            unittest.mock.patch("gradepack.factory._verify_draft_files",
                                 return_value=(True, "")),
        ):
            _cli.cmd_promote(task_id)

        captured = capsys.readouterr()
        assert "PROMOTED" in captured.out


# ---------------------------------------------------------------------------
# Part 2f: resume / progress file
# ---------------------------------------------------------------------------

class TestResume:

    def test_progress_file_written_after_each_draft(self, tmp_path):
        """factory writes _progress.json after each draft."""
        stats_file = tmp_path / "factory_stats.json"
        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path),
            unittest.mock.patch.object(core, "tasks_dir", return_value=fake_tasks),
        ):
            _factory.cmd_factory(
                n=2, probe_attempts=1, parallel=1,
                mock=True, mock_probe_fail=True,
            )

        progress_file = tmp_path / "_progress.json"
        assert progress_file.exists(), "_progress.json should be written"
        progress = json.loads(progress_file.read_text())
        assert len(progress.get("completed", [])) == 2

    def test_resume_skips_already_done(self, tmp_path):
        """--resume with existing progress skips completed drafts."""
        stats_file = tmp_path / "factory_stats.json"
        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()
        # Pre-populate progress with 1 draft already done
        progress_data = {"completed": [{"status": "accepted", "task_id": "000-pre"}], "kept": 1}
        (tmp_path / "_progress.json").write_text(json.dumps(progress_data))

        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path),
            unittest.mock.patch.object(core, "tasks_dir", return_value=fake_tasks),
        ):
            _factory.cmd_factory(
                n=2, probe_attempts=1, parallel=1,
                mock=True, mock_probe_fail=True, resume=True,
            )

        # Should only have run 1 more draft (total n=2, 1 already done)
        stats = json.loads(stats_file.read_text())
        assert stats["drafted"] == 1, (
            f"Should have drafted 1 (not 2) due to resume: {stats}"
        )

    def test_load_progress_returns_defaults_if_missing(self, tmp_path):
        """_load_progress returns empty structure if file doesn't exist."""
        with unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path):
            p = _factory._load_progress()
        assert p == {"completed": [], "kept": 0}

    def test_save_and_load_progress_roundtrip(self, tmp_path):
        """_save_progress and _load_progress are consistent."""
        progress = {"completed": [{"status": "accepted"}], "kept": 1}
        with unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path):
            _factory._save_progress(progress)
            loaded = _factory._load_progress()
        assert loaded == progress


# ---------------------------------------------------------------------------
# Part 2g: difficulty_warnings in validate
# ---------------------------------------------------------------------------

class TestDifficultyWarnings:

    def test_no_warnings_for_valid_task(self):
        """task 001 must produce no difficulty warnings."""
        warnings = difficulty_warnings("001-pagination-off-by-one")
        assert warnings == []

    def test_difficulty_warnings_returns_list(self):
        """difficulty_warnings always returns a list."""
        result = difficulty_warnings("001-pagination-off-by-one")
        assert isinstance(result, list)

    def test_difficulty_warnings_unknown_task(self):
        """Non-existent task must return empty list (no crash)."""
        result = difficulty_warnings("999-nonexistent")
        assert result == []

    def test_validate_cmd_prints_ok_with_warnings(self, tmp_path, capsys):
        """validate with warnings but no errors prints OK and warnings."""
        from gradepack.validate import cmd_validate
        with (
            unittest.mock.patch("gradepack.validate.core.all_task_ids",
                                 return_value=["001-pagination-off-by-one"]),
            unittest.mock.patch("gradepack.validate.validate_task",
                                 return_value=[]),
            unittest.mock.patch("gradepack.validate.difficulty_warnings",
                                 return_value=["[001-x] difficulty='easy' but has 30 tests"]),
        ):
            cmd_validate()
        captured = capsys.readouterr()
        # Should print OK but also print warning
        assert "OK" in captured.out
        assert "WARNING" in captured.out


# ---------------------------------------------------------------------------
# Ensure_draft_fail_reasons backfills lint_fail_reasons too
# ---------------------------------------------------------------------------

def test_ensure_draft_fail_reasons_backfills_lint_reasons(tmp_path):
    """_ensure_draft_fail_reasons also adds lint_fail_reasons and lint_rejected."""
    old_stats = {"drafted": 5, "failed_draft_stage": 1}
    _factory._ensure_draft_fail_reasons(old_stats)
    assert "lint_fail_reasons" in old_stats
    assert "lint_rejected" in old_stats
    for r in _factory._LINT_REASONS:
        assert r in old_stats["lint_fail_reasons"]


def test_load_stats_includes_lint_fields(tmp_path):
    """Fresh _load_stats must include lint_rejected and lint_fail_reasons."""
    stats_file = tmp_path / "factory_stats.json"
    with unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file):
        stats = _factory._load_stats()
    assert "lint_rejected" in stats
    assert "lint_fail_reasons" in stats
    for r in _factory._LINT_REASONS:
        assert r in stats["lint_fail_reasons"]


# ---------------------------------------------------------------------------
# lint_draft_dir reads on-disk draft correctly
# ---------------------------------------------------------------------------

def test_lint_draft_dir_clean_draft(tmp_path):
    """lint_draft_dir on a clean on-disk draft returns no problems."""
    d = tmp_path / "037-clean"
    d.mkdir()
    files = _clean_draft_files()
    (d / "task.json").write_text(files["task.json"])
    (d / "starter").mkdir()
    (d / "starter" / "adder.py").write_text(files["starter/adder.py"])
    (d / "grader").mkdir()
    (d / "grader" / "test_adder.py").write_text(files["grader/test_adder.py"])
    (d / "solution").mkdir()
    (d / "solution" / "adder.py").write_text(files["solution/adder.py"])
    problems = _factory.lint_draft_dir(d)
    assert problems == []


def test_lint_draft_dir_bad_draft(tmp_path):
    """lint_draft_dir on a bad draft reports problems."""
    d = tmp_path / "037-bad"
    d.mkdir()
    files = _clean_draft_files(title="Bad", grader_funcs=2)
    (d / "task.json").write_text(files["task.json"])
    (d / "starter").mkdir()
    (d / "starter" / "adder.py").write_text(files["starter/adder.py"])
    (d / "grader").mkdir()
    (d / "grader" / "test_adder.py").write_text(files["grader/test_adder.py"])
    (d / "solution").mkdir()
    (d / "solution" / "adder.py").write_text(files["solution/adder.py"])
    problems = _factory.lint_draft_dir(d)
    assert len(problems) >= 2


# ---------------------------------------------------------------------------
# factory --help includes --resume
# ---------------------------------------------------------------------------

def test_factory_help_includes_resume():
    """factory --help must mention --resume."""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with pytest.raises(SystemExit):
        with redirect_stdout(buf):
            _factory.build_parser().parse_args(["--help"])
    output = buf.getvalue()
    assert "--resume" in output
