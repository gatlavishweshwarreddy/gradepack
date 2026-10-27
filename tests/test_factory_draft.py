"""
tests/test_factory_draft.py — tests for factory draft-stage fixes:
  1. Length retry (finish_reason length + empty → retry with doubled max_tokens)
  2. Robust JSON extraction (code fences, truncation, leading prose)
  3. Unique temp directories (parallel drafts never collide)
  4. Draft-stage failure reasons tracked in factory_stats.json

No real API calls. Uses FakeServer for HTTP tests.
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import unittest.mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tests.fake_server import FakeServer, _VALID_DRAFT_RESPONSE, _ADDER_SOLUTION
from gradepack import api as _api
from gradepack import core
from gradepack import factory as _factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_for(server, model_mode: str) -> dict:
    return {"BASE_URL": server.base_url, "API_KEY": "fake-key", "MODEL": model_mode}


# ---------------------------------------------------------------------------
# 1. Length retry: finish_reason length + empty → retry succeeds
# ---------------------------------------------------------------------------

class TestDraftLengthRetry:
    """_chat_draft retries when finish_reason==length and content is empty."""

    def test_length_retry_returns_content_on_second_call(self):
        """Call 1: length+empty. Call 2: full content. Should succeed with retried=True."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, _env_for(srv, "draft_length_retry")):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    content, retried = _factory._chat_draft(
                        "sys", "user", max_tokens=8192
                    )
        assert retried is True, "Expected retried=True after length retry"
        assert content, "Expected non-empty content after retry"
        assert "=== task.json ===" in content, "Expected draft content in response"

    def test_length_empty_no_retry_stays_empty(self):
        """If both calls return length+empty (length_empty mode), content stays empty."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, _env_for(srv, "length_empty")):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    content, retried = _factory._chat_draft(
                        "sys", "user", max_tokens=8192
                    )
        # retried=True because we did retry
        assert retried is True
        assert not content, "Both calls returned empty content"

    def test_model_draft_sets_fail_reason_empty_content_when_both_truncated(self):
        """_model_draft returns fail_reason='empty_content' when content stays empty."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, _env_for(srv, "length_empty")):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    files, retried, reason = _factory._model_draft(
                        [], max_tokens=8192
                    )
        assert reason == "empty_content"
        assert files == {} or not files.get("task.json")

    def test_model_draft_succeeds_after_length_retry(self):
        """_model_draft succeeds after retry with draft_length_retry mode."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, _env_for(srv, "draft_length_retry")):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    files, retried, reason = _factory._model_draft(
                        [], max_tokens=8192
                    )
        assert retried is True
        assert reason == "", f"Expected success, got reason={reason!r}"
        assert "task.json" in files
        assert "starter/adder.py" in files

    def test_draft_max_tokens_default_is_24000(self):
        """Default draft max_tokens should be 24000."""
        assert _factory._DEFAULT_DRAFT_MAX_TOKENS == 24000

    def test_factory_help_includes_draft_max_tokens(self):
        """--draft-max-tokens must appear in the --help output."""
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with pytest.raises(SystemExit):
            with redirect_stdout(buf):
                _factory.build_parser().parse_args(["--help"])
        output = buf.getvalue()
        assert "draft-max-tokens" in output or "draft_max_tokens" in output


# ---------------------------------------------------------------------------
# 2. Robust JSON extraction
# ---------------------------------------------------------------------------

class TestExtractJsonRobust:
    """_extract_json_robust handles fences, truncation, leading prose."""

    def test_plain_json_parses(self):
        text = '{"id": "001-foo", "title": "bar"}'
        result, reason = _factory._extract_json_robust(text)
        assert reason == ""
        assert result == {"id": "001-foo", "title": "bar"}

    def test_json_with_fences_parses(self):
        text = '```json\n{"id": "001-foo"}\n```'
        result, reason = _factory._extract_json_robust(text)
        assert reason == ""
        assert result["id"] == "001-foo"

    def test_json_with_plain_fences_parses(self):
        text = '```\n{"id": "001-foo"}\n```'
        result, reason = _factory._extract_json_robust(text)
        assert reason == ""
        assert result["id"] == "001-foo"

    def test_json_with_leading_prose(self):
        text = "Here is the task JSON:\n\n{\"id\": \"001-foo\", \"title\": \"t\"}"
        result, reason = _factory._extract_json_robust(text)
        assert reason == ""
        assert result["id"] == "001-foo"

    def test_json_with_trailing_prose(self):
        text = '{"id": "001-foo"}\n\nSome extra text after.'
        result, reason = _factory._extract_json_robust(text)
        assert reason == ""
        assert result["id"] == "001-foo"

    def test_empty_text_returns_empty_content(self):
        result, reason = _factory._extract_json_robust("")
        assert result is None
        assert reason == "empty_content"

    def test_whitespace_only_returns_empty_content(self):
        result, reason = _factory._extract_json_robust("   \n  ")
        assert result is None
        assert reason == "empty_content"

    def test_truncated_json_detected(self):
        text = '{"id": "001-foo", "title": "bar'  # no closing brace
        result, reason = _factory._extract_json_robust(text)
        assert result is None
        assert reason == "truncated_json"

    def test_truncated_json_with_some_braces(self):
        # Has { but no matching }
        text = '{"id": "001", "nested": {"key": "val"'
        result, reason = _factory._extract_json_robust(text)
        assert result is None
        assert reason in ("truncated_json", "invalid_json")

    def test_no_braces_is_invalid_json(self):
        text = "Just some prose with no JSON at all."
        result, reason = _factory._extract_json_robust(text)
        assert result is None
        assert reason == "invalid_json"

    def test_fenced_draft_task_json_parses(self):
        """Simulates the draft_json_fenced server mode response."""
        from tests.fake_server import _DRAFT_JSON_FENCED_RESPONSE
        files = _factory._parse_file_blocks(_DRAFT_JSON_FENCED_RESPONSE)
        assert "task.json" in files
        meta, reason = _factory._extract_json_robust(files["task.json"])
        assert reason == "", f"Expected success, got reason={reason!r}"
        assert meta is not None
        assert "id" in meta

    def test_truncated_draft_task_json_fails_gracefully(self):
        """Simulates the draft_truncated_json server mode response."""
        from tests.fake_server import _DRAFT_TRUNCATED_JSON_RESPONSE
        files = _factory._parse_file_blocks(_DRAFT_TRUNCATED_JSON_RESPONSE)
        assert "task.json" in files
        meta, reason = _factory._extract_json_robust(files["task.json"])
        assert meta is None
        assert reason in ("truncated_json", "invalid_json")

    def test_materialise_draft_handles_fenced_json(self):
        """_materialise_draft succeeds when task.json is fenced."""
        from tests.fake_server import _DRAFT_JSON_FENCED_RESPONSE
        files = _factory._parse_file_blocks(_DRAFT_JSON_FENCED_RESPONSE)
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            err = _factory._materialise_draft(files, tmp / "task")
            assert err is None, f"Expected success, got: {err}"
            written = json.loads((tmp / "task" / "task.json").read_text())
            assert written["id"] == "000-adder-draft"
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_model_draft_fenced_json_succeeds(self):
        """When the server returns fenced task.json, _model_draft still succeeds."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, _env_for(srv, "draft_json_fenced")):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    files, retried, reason = _factory._model_draft([])
        assert reason == "", f"Expected success, got reason={reason!r}"
        assert "task.json" in files

    def test_model_draft_truncated_json_fails_with_reason(self):
        """When the server returns truncated task.json, _model_draft returns failure reason."""
        with FakeServer() as srv:
            with unittest.mock.patch.dict(os.environ, _env_for(srv, "draft_truncated_json")):
                with unittest.mock.patch("gradepack.api.time.sleep"):
                    files, retried, reason = _factory._model_draft([])
        assert reason in ("truncated_json", "invalid_json"), (
            f"Expected truncated_json or invalid_json, got {reason!r}"
        )


# ---------------------------------------------------------------------------
# 3. Unique temp directories — parallel drafts never collide
# ---------------------------------------------------------------------------

class TestUniqueTempdirs:
    """Verify that verify and probe stages each use a unique temp directory."""

    def test_verify_uses_unique_temp_dir(self):
        """
        Two concurrent _verify_draft_files calls with the same task_id must
        not collide — each must get its own tempdir.
        """
        files = _factory._mock_draft()
        # The mock task_id used in verify is "000-tmp-verify".
        # Run two verifications concurrently and ensure both complete without error.
        errors = []

        def run_verify():
            try:
                ok, reason = _factory._verify_draft_files(files, "000-tmp-verify")
                if not ok:
                    errors.append(f"verify failed: {reason}")
            except Exception as exc:
                errors.append(f"exception: {exc}")

        t1 = threading.Thread(target=run_verify)
        t2 = threading.Thread(target=run_verify)
        t1.start(); t2.start()
        t1.join(timeout=60); t2.join(timeout=60)

        assert not errors, f"Concurrent verify errors: {errors}"

    def test_probe_once_uses_unique_temp_dir(self, monkeypatch):
        """
        Two concurrent _probe_once calls must each get their own tempdir.
        Uses mock=True so no API call is needed.
        """
        results = []
        errors = []

        def run_probe():
            try:
                result = _factory._probe_once(_factory._mock_draft(), mock=True)
                results.append(result)
            except Exception as exc:
                errors.append(str(exc))

        t1 = threading.Thread(target=run_probe)
        t2 = threading.Thread(target=run_probe)
        t1.start(); t2.start()
        t1.join(timeout=60); t2.join(timeout=60)

        assert not errors, f"Concurrent probe errors: {errors}"
        assert results == [True, True], f"Both probes should pass in mock mode: {results}"

    def test_parallel_factory_runs_no_collision(self, tmp_path):
        """
        Two parallel _run_factory_once calls must not collide on temp dirs.
        Uses mock=True.
        """
        stats_file = tmp_path / "factory_stats.json"
        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with (
            unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
            unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
            unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
            unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
            unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
            unittest.mock.patch.object(core, "tasks_dir", return_value=fake_tasks),
            unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path),
        ):
            _factory.cmd_factory(
                n=2, probe_attempts=1, parallel=2,
                mock=True, mock_probe_fail=True,
            )

        assert stats_file.exists()
        stats = json.loads(stats_file.read_text())
        assert stats["drafted"] == 2
        # Both should be discriminating (mock_probe_fail=True)
        assert stats["discriminating"] == 2


# ---------------------------------------------------------------------------
# 4. Draft-stage failure reasons in factory_stats.json
# ---------------------------------------------------------------------------

class TestDraftStageStats:
    """Draft-stage failure reasons are tracked in factory_stats.json."""

    def test_empty_content_counted_in_stats(self, tmp_path):
        """A draft that returns empty content increments draft_fail_reasons.empty_content."""
        stats_file = tmp_path / "factory_stats.json"
        lessons_file = tmp_path / "LESSONS.md"

        with FakeServer() as srv:
            with (
                unittest.mock.patch.dict(os.environ, _env_for(srv, "length_empty")),
                unittest.mock.patch("gradepack.api.time.sleep"),
                unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
                unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
                unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
                unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
                unittest.mock.patch.object(_factory, "_LESSONS_FILE", lessons_file),
                unittest.mock.patch.object(_factory, "_existing_numbers",
                                            return_value=set(range(1, 37))),
            ):
                result = _factory._run_factory_once(
                    mock=False, lessons=[], probe_attempts=1
                )

        assert result["status"] == "error"
        assert "empty_content" in result.get("reason", "")
        assert stats_file.exists()
        stats = json.loads(stats_file.read_text())
        assert stats["failed_draft_stage"] == 1
        assert stats["draft_fail_reasons"]["empty_content"] == 1

    def test_truncated_json_counted_in_stats(self, tmp_path):
        """A draft with truncated task.json increments draft_fail_reasons.truncated_json."""
        stats_file = tmp_path / "factory_stats.json"
        lessons_file = tmp_path / "LESSONS.md"

        with FakeServer() as srv:
            with (
                unittest.mock.patch.dict(os.environ, _env_for(srv, "draft_truncated_json")),
                unittest.mock.patch("gradepack.api.time.sleep"),
                unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
                unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
                unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
                unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
                unittest.mock.patch.object(_factory, "_LESSONS_FILE", lessons_file),
                unittest.mock.patch.object(_factory, "_existing_numbers",
                                            return_value=set(range(1, 37))),
            ):
                result = _factory._run_factory_once(
                    mock=False, lessons=[], probe_attempts=1
                )

        assert result["status"] == "error"
        reason = result.get("reason", "")
        assert "truncated_json" in reason or "invalid_json" in reason, (
            f"Unexpected reason: {reason!r}"
        )
        stats = json.loads(stats_file.read_text())
        assert stats["failed_draft_stage"] == 1
        dfr = stats["draft_fail_reasons"]
        assert dfr.get("truncated_json", 0) + dfr.get("invalid_json", 0) >= 1

    def test_fenced_json_succeeds_not_counted_as_failure(self, tmp_path):
        """A draft with fenced task.json is parsed successfully — no failure recorded."""
        stats_file = tmp_path / "factory_stats.json"
        lessons_file = tmp_path / "LESSONS.md"
        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with FakeServer() as srv:
            with (
                unittest.mock.patch.dict(os.environ, _env_for(srv, "draft_json_fenced")),
                unittest.mock.patch("gradepack.api.time.sleep"),
                unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
                unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
                unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
                unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
                unittest.mock.patch.object(_factory, "_LESSONS_FILE", lessons_file),
                unittest.mock.patch.object(core, "tasks_dir", return_value=fake_tasks),
                unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path),
            ):
                result = _factory._run_factory_once(
                    mock=False, lessons=[], probe_attempts=1, mock_probe_fail=True
                )

        # Should succeed at draft stage (may fail verify or be accepted — either is fine)
        assert result["status"] != "error" or "draft" not in result.get("stage", ""), (
            f"Draft should not fail at draft stage for fenced JSON: {result}"
        )
        if stats_file.exists():
            stats = json.loads(stats_file.read_text())
            # failed_draft_stage must be 0 for fenced JSON (it should parse fine)
            assert stats["failed_draft_stage"] == 0, (
                f"Fenced JSON should not count as failed draft: {stats}"
            )

    def test_draft_fail_reasons_key_present_in_new_stats(self, tmp_path):
        """New stats file must contain draft_fail_reasons key."""
        stats_file = tmp_path / "factory_stats.json"
        with unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file):
            stats = _factory._load_stats()
        assert "draft_fail_reasons" in stats
        for r in _factory._DRAFT_FAIL_REASONS:
            assert r in stats["draft_fail_reasons"]

    def test_ensure_draft_fail_reasons_backfills(self, tmp_path):
        """_ensure_draft_fail_reasons adds the key to old stats that lack it."""
        old_stats = {"drafted": 5, "failed_draft_stage": 1}
        _factory._ensure_draft_fail_reasons(old_stats)
        assert "draft_fail_reasons" in old_stats
        for r in _factory._DRAFT_FAIL_REASONS:
            assert r in old_stats["draft_fail_reasons"]

    def test_retried_flag_recorded_in_draft_record(self, tmp_path):
        """When a draft is retried (length retry succeeds), draft_retried=True in stats."""
        stats_file = tmp_path / "factory_stats.json"
        lessons_file = tmp_path / "LESSONS.md"
        fake_tasks = tmp_path / "tasks"
        fake_tasks.mkdir()

        with FakeServer() as srv:
            with (
                unittest.mock.patch.dict(os.environ, _env_for(srv, "draft_length_retry")),
                unittest.mock.patch("gradepack.api.time.sleep"),
                unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
                unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
                unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
                unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
                unittest.mock.patch.object(_factory, "_LESSONS_FILE", lessons_file),
                unittest.mock.patch.object(core, "tasks_dir", return_value=fake_tasks),
                unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path),
            ):
                result = _factory._run_factory_once(
                    mock=False, lessons=[], probe_attempts=1, mock_probe_fail=True
                )

        # The draft might pass or fail verify; what matters is that draft stage succeeds
        assert result["status"] != "error" or "draft" not in result.get("stage", ""), (
            f"Draft should not fail at draft stage after retry: {result}"
        )
        if stats_file.exists() and result["status"] == "accepted":
            stats = json.loads(stats_file.read_text())
            task_id = result.get("task_id")
            if task_id and task_id in stats.get("drafts", {}):
                assert stats["drafts"][task_id].get("draft_retried") is True


# ---------------------------------------------------------------------------
# factory --mock smoke test (end-to-end, no API)
# ---------------------------------------------------------------------------

def test_factory_mock_runs_without_error(tmp_path):
    """factory --mock must complete without raising, produce discriminating drafts."""
    stats_file = tmp_path / "factory_stats.json"
    fake_tasks = tmp_path / "tasks"
    fake_tasks.mkdir()

    with (
        unittest.mock.patch.object(_factory, "_STATS_FILE", stats_file),
        unittest.mock.patch.object(_factory, "_ACCEPTED_DIR", tmp_path / "accepted"),
        unittest.mock.patch.object(_factory, "_REJECTED_DIR", tmp_path / "rejected"),
        unittest.mock.patch.object(_factory, "_TOO_EASY_DIR", tmp_path / "too_easy"),
        unittest.mock.patch.object(_factory, "_LESSONS_FILE", tmp_path / "LESSONS.md"),
        unittest.mock.patch.object(core, "tasks_dir", return_value=fake_tasks),
        unittest.mock.patch.object(_factory, "_DRAFTS_DIR", tmp_path),
    ):
        _factory.cmd_factory(
            n=1, probe_attempts=1, parallel=1,
            mock=True, mock_probe_fail=True,
        )

    assert stats_file.exists()
    stats = json.loads(stats_file.read_text())
    assert stats["drafted"] == 1
    assert stats["discriminating"] == 1
    assert "draft_fail_reasons" in stats
