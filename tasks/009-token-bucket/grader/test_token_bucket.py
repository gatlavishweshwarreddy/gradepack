import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from token_bucket import TokenBucket


def test_initial_consume():
    tb = TokenBucket(rate=1, capacity=10)
    assert tb.consume(5, 0.0) is True


def test_exhaust_then_fail():
    tb = TokenBucket(rate=1, capacity=5)
    assert tb.consume(5, 0.0) is True
    assert tb.consume(1, 0.0) is False


def test_refill_allows_consume():
    tb = TokenBucket(rate=10, capacity=10)
    tb.consume(10, 0.0)          # empty the bucket
    assert tb.consume(5, 0.5)   # 0.5s * 10 rate = 5 tokens refilled


def test_cap_at_capacity():
    tb = TokenBucket(rate=10, capacity=5)
    tb.consume(0, 0.0)           # initialise _last
    # after 100s worth of refill, tokens must not exceed capacity=5
    assert tb.consume(5, 100.0) is True
    assert tb.consume(1, 100.0) is False


def test_partial_refill_not_enough():
    tb = TokenBucket(rate=1, capacity=10)
    tb.consume(10, 0.0)          # empty
    assert tb.consume(2, 1.0) is False   # only 1 token refilled
