import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

import pytest
from retry import retry


def test_success_no_retry():
    calls = []

    @retry(3, (ValueError,))
    def ok():
        calls.append(1)
        return 42

    assert ok() == 42
    assert len(calls) == 1


def test_retries_then_succeeds():
    calls = []

    @retry(3, (ValueError,))
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("fail")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3


def test_exhausted_raises():
    calls = []

    @retry(3, (ValueError,))
    def always_fail():
        calls.append(1)
        raise ValueError("always")

    with pytest.raises(ValueError):
        always_fail()
    assert len(calls) == 3


def test_exact_attempt_count():
    """max_attempts=1 means only one call, no retries."""
    calls = []

    @retry(1, (ValueError,))
    def fail_once():
        calls.append(1)
        raise ValueError("x")

    with pytest.raises(ValueError):
        fail_once()
    assert len(calls) == 1


def test_unspecified_exception_not_caught():
    @retry(3, (ValueError,))
    def wrong_exc():
        raise TypeError("wrong type")

    with pytest.raises(TypeError):
        wrong_exc()
