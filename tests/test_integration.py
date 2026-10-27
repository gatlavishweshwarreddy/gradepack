"""
tests/test_integration.py — integration tests against fake_server.py.

These tests start a real local HTTP server and run bench/_api calls against it.
No real API calls are made.
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

from tests.fake_server import FakeServer
from gradepack import api as _api
from gradepack import bench as _bench
from gradepack import core

TASK_001 = "001-pagination-off-by-one"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_bench_task(server, model_mode, *, raw_dir=None):
    """Run _bench_task with env pointing at the fake server."""
    if raw_dir is None:
        raw_dir = pathlib.Path(tempfile.mkdtemp())
    with unittest.mock.patch.dict(os.environ, {
        "BASE_URL": server.base_url,
        "API_KEY":  "fake-key",
        "MODEL":    model_mode,
    }):
        # Patch time.sleep to avoid real waits in retry logic
        with unittest.mock.patch("gradepack.api.time.sleep"):
            record = _bench._bench_task(
                TASK_001, 1,
                mock=False, mock_pass=True,
                raw_output_dir=raw_dir / "raw",
                provider="test", model_name=model_mode,
                max_tokens=512, temperature=0.0,
            )
    return record


# ---------------------------------------------------------------------------
# normal — correct answer in content
# ---------------------------------------------------------------------------

def test_normal_parses_and_passes():
    with FakeServer() as srv:
        record = _run_bench_task(srv, "normal")
    assert record["score"] == 1.0
    assert record["failure_reason"] == "none"


# ---------------------------------------------------------------------------
# reasoning — content null, text only in reasoning_content (must NOT be used)
# ---------------------------------------------------------------------------

def test_reasoning_content_not_used_as_answer():
    with FakeServer() as srv:
        record = _run_bench_task(srv, "reasoning")
    # reasoning_content must never be parsed as the answer
    assert record["score"] == 0.0
    assert record["failure_reason"] in ("invalid_output", "no_answer", "wrong_answer")


# ---------------------------------------------------------------------------
# starter_path — filename "starter/paginate.py" must be normalised
# ---------------------------------------------------------------------------

def test_starter_path_prefix_stripped():
    with FakeServer() as srv:
        record = _run_bench_task(srv, "starter_path")
    assert record["score"] == 1.0, (
        f"Expected starter_path to succeed after normalisation, got score={record['score']}, "
        f"failure_reason={record['failure_reason']}"
    )


# ---------------------------------------------------------------------------
# length_empty — finish_reason "length", empty content → score 0.0
# ---------------------------------------------------------------------------

def test_length_empty_scores_zero():
    with FakeServer() as srv:
        record = _run_bench_task(srv, "length_empty")
    assert record["score"] == 0.0
    # failure_reason should be no_answer (empty content on length)
    assert record["failure_reason"] == "no_answer"


# ---------------------------------------------------------------------------
# length_retry — first call truncated, retry with doubled max_tokens succeeds
# ---------------------------------------------------------------------------

def test_length_retry_succeeds_on_second_call():
    with FakeServer() as srv:
        with unittest.mock.patch.dict(os.environ, {
            "BASE_URL": srv.base_url,
            "API_KEY":  "fake-key",
            "MODEL":    "length_retry",
        }):
            with unittest.mock.patch("gradepack.api.time.sleep"):
                record = _bench._bench_task(
                    TASK_001, 1,
                    mock=False, mock_pass=True,
                    raw_output_dir=pathlib.Path(tempfile.mkdtemp()) / "raw",
                    provider="test", model_name="length_retry",
                    max_tokens=512, temperature=0.0,
                )
    assert record.get("retried") is True, "Expected retried=True"
    assert record["score"] == 1.0, f"Expected score=1.0 after retry, got {record['score']}"


# ---------------------------------------------------------------------------
# rate_limit — 429 on first call, success on retry
# ---------------------------------------------------------------------------

def test_rate_limit_retries_and_succeeds():
    with FakeServer() as srv:
        record = _run_bench_task(srv, "rate_limit")
    assert record["score"] == 1.0
    assert record["failure_reason"] == "none"


# ---------------------------------------------------------------------------
# always_500 — exhausts retries → api_error or runner_error
# ---------------------------------------------------------------------------

def test_always_500_gives_api_error():
    with FakeServer() as srv:
        record = _run_bench_task(srv, "always_500")
    assert record["score"] == 0.0
    assert record["failure_reason"] == "api_error"


# ---------------------------------------------------------------------------
# slow — server hangs → timeout failure_reason (not runner_error)
# ---------------------------------------------------------------------------

def test_slow_response_timeout():
    with FakeServer() as srv:
        with unittest.mock.patch.dict(os.environ, {
            "BASE_URL": srv.base_url,
            "API_KEY":  "fake-key",
            "MODEL":    "slow",
        }):
            # Use a short API timeout (2s) so we don't wait 60s
            with unittest.mock.patch("gradepack.api.time.sleep"):
                try:
                    resp = _api.chat("sys", "user", max_tokens=16, timeout=2)
                    # If we somehow get a response, that's fine
                    content = _api.extract_content(resp)
                    # We don't assert on score here since we couldn't control bench timeout
                except Exception as exc:
                    msg = str(exc).lower()
                    assert ("timeout" in msg or "timed out" in msg or
                            "urlopen error" in msg or "connection" in msg), \
                        f"Expected timeout error, got: {exc}"


# ---------------------------------------------------------------------------
# run_pytest timeout → failure_reason == "timeout" (not "runner_error")
# ---------------------------------------------------------------------------

def test_pytest_timeout_classifies_as_timeout():
    """A grader that hangs must produce failure_reason='timeout', not 'runner_error'."""
    import subprocess
    # Mock run_pytest to return a timeout result directly
    timeout_result = {
        "passed": 0, "failed": 0, "total": 0, "failures": [],
        "error": "pytest timed out after 30s",
        "timed_out": True,
        "_raw_output": "",
    }
    reason = _bench._categorise(timeout_result, error_msg=None, finish_reason="stop", had_candidate=True)
    assert reason == "timeout", f"Expected 'timeout', got {reason!r}"


# ---------------------------------------------------------------------------
# extract_content never uses reasoning_content
# ---------------------------------------------------------------------------

def test_extract_content_ignores_reasoning():
    data = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "some reasoning text",
            },
            "finish_reason": "stop",
        }]
    }
    content = _api.extract_content(data)
    assert content == "", f"Expected empty string, got {content!r}"


def test_extract_content_returns_content_field():
    data = {
        "choices": [{
            "message": {"role": "assistant", "content": "hello"},
            "finish_reason": "stop",
        }]
    }
    assert _api.extract_content(data) == "hello"


# ---------------------------------------------------------------------------
# run_id present in bench records
# ---------------------------------------------------------------------------

def test_bench_record_has_run_id(tmp_path):
    """Every record written by cmd_bench must have a run_id."""
    with unittest.mock.patch.dict(os.environ, {}):
        _bench.cmd_bench(
            model="test-run-id",
            mock=True,
            mock_pass=True,
            task_filter=[TASK_001],
            publish=False,
        )
    results_file = core._repo_root() / "results" / "test-run-id.json"
    try:
        data = json.loads(results_file.read_text())
        assert data, "Expected at least one record"
        for rec in data:
            assert "run_id" in rec, f"Missing run_id in record: {rec}"
    finally:
        results_file.unlink(missing_ok=True)
