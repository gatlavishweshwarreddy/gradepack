import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from workqueue import WorkQueue
from worker import Worker
import pytest


def _run_concurrent(n_items, n_workers, seed=0):
    import random
    rng = random.Random(seed)
    items = [rng.randint(1, 100) for _ in range(n_items)]
    expected = sorted(x * 2 for x in items)

    q = WorkQueue()
    results = []
    results_lock = threading.Lock()

    barrier = threading.Barrier(n_workers)

    def worker_func():
        barrier.wait()
        w = Worker(q, [])
        w.run()
        with results_lock:
            results.extend(w._results)

    for item in items:
        q.put(item)
    q.done()

    threads = [threading.Thread(target=worker_func) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    return sorted(results), expected


def test_single_worker_all_items():
    got, expected = _run_concurrent(10, 1, seed=1)
    assert got == expected


def test_two_workers_all_items():
    got, expected = _run_concurrent(20, 2, seed=2)
    assert got == expected, f"Lost items: expected {len(expected)}, got {len(got)}"


def test_four_workers_all_items():
    got, expected = _run_concurrent(40, 4, seed=7)
    assert got == expected, f"Lost items: expected {len(expected)}, got {len(got)}"


def test_no_duplicates():
    got, expected = _run_concurrent(30, 3, seed=42)
    assert len(got) == len(expected), (
        f"Count mismatch: expected {len(expected)}, got {len(got)}"
    )
