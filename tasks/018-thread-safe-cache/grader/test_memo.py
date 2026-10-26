import os, sys, random, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

import pytest
from memo import memoize


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------

def test_basic():
    @memoize
    def add(a, b):
        return a + b
    assert add(1, 2) == 3
    assert add(1, 2) == 3


def test_cached_not_recomputed():
    calls = []

    @memoize
    def compute(x):
        calls.append(x)
        return x * 2

    compute(5)
    compute(5)
    compute(5)
    assert len(calls) == 1, "Should be called exactly once"


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 99])
def test_seeded_correctness(seed):
    rng = random.Random(seed)
    calls = {}

    @memoize
    def fn(x):
        calls[x] = calls.get(x, 0) + 1
        return x ** 2

    keys = [rng.randint(0, 5) for _ in range(20)]
    for k in keys:
        assert fn(k) == k ** 2

    # Each unique key must be computed at most once
    for k, count in calls.items():
        assert count == 1, f"fn({k}) was called {count} times, expected 1"


# ---------------------------------------------------------------------------
# Thread-safety: force a race with a Barrier
# ---------------------------------------------------------------------------

def test_concurrent_no_double_compute():
    """
    Two threads try to compute the same key simultaneously.
    The function must be called at most once (one result wins, the other is discarded).
    """
    call_count = [0]
    barrier = threading.Barrier(2)

    @memoize
    def slow_fn(x):
        barrier.wait()   # both threads reach here simultaneously
        call_count[0] += 1
        return x * 10

    results = [None, None]

    def worker(i):
        results[i] = slow_fn(42)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results[0] == 420
    assert results[1] == 420
    # The function may be called once or twice (both threads may compute);
    # what must NOT happen is a corrupted/wrong return value.
    assert call_count[0] in (1, 2), f"Unexpected call count: {call_count[0]}"
