import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from limiter import RateLimiter
import pytest


def test_allows_up_to_limit():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    t = 0
    assert rl.allow("user1", t + 1) is True
    assert rl.allow("user1", t + 2) is True
    assert rl.allow("user1", t + 3) is True


def test_blocks_at_limit():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    t = 0
    rl.allow("user1", t + 1)
    rl.allow("user1", t + 2)
    rl.allow("user1", t + 3)
    result = rl.allow("user1", t + 4)
    assert result is False, "Should be blocked after max_requests"


def test_independent_keys():
    rl = RateLimiter(max_requests=2, window_seconds=60)
    rl.allow("alice", 1)
    rl.allow("alice", 2)
    assert rl.allow("alice", 3) is False
    assert rl.allow("bob", 3) is True


def test_expired_requests_not_counted():
    rl = RateLimiter(max_requests=2, window_seconds=10)
    rl.allow("user1", 1)
    rl.allow("user1", 2)
    assert rl.allow("user1", 5) is False
    assert rl.allow("user1", 15) is True


def test_limit_of_one():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("x", 1) is True
    assert rl.allow("x", 2) is False


def test_window_boundary():
    rl = RateLimiter(max_requests=2, window_seconds=10)
    rl.allow("u", 1)
    rl.allow("u", 10)
    assert rl.allow("u", 11) is False
    assert rl.allow("u", 12) is True
