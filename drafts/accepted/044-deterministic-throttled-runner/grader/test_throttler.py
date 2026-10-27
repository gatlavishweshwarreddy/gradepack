import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
from throttler import ThrottledRunner

def test_running_not_cancellable():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    r.tick(0)
    assert r.get_state("a") == "RUNNING"
    assert r.cancel("a") == False
    assert r.get_state("a") == "RUNNING"

def test_cancel_pending():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    r.submit("b", priority=0)
    assert r.cancel("b") == True
    assert r.get_state("b") == "CANCELLED"
    started = r.tick(0)
    assert started == ["a"]
    r.complete("a", True)
    started = r.tick(0)
    assert started == []

def test_token_bucket_cap():
    r = ThrottledRunner(max_concurrent=10, rps=1, burst=2)
    r.submit("a", priority=0)
    r.submit("b", priority=0)
    r.submit("c", priority=0)
    started = r.tick(0)
    assert len(started) == 2
    assert set(started) == {"a", "b"}
    r.complete("a", True)
    r.complete("b", True)
    started = r.tick(10)
    assert "c" in started
    assert len(started) == 1
    r.submit("d", priority=0)
    r.submit("e", priority=0)
    r.submit("f", priority=0)
    started2 = r.tick(10)
    assert len(started2) == 1
    assert started2 == ["d"]

def test_token_not_consumed_when_concurrency_full():
    r = ThrottledRunner(max_concurrent=1, rps=1, burst=1)
    r.submit("a", priority=0)
    r.submit("b", priority=0)
    started = r.tick(0)
    assert started == ["a"]
    started = r.tick(1)
    assert started == []
    r.complete("a", True)
    started = r.tick(1)
    assert started == ["b"]

def test_priority_ordering():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("low", priority=1)
    r.submit("high", priority=10)
    r.submit("mid", priority=5)
    started = r.tick(0)
    assert started == ["high"]
    r.complete("high", True)
    started = r.tick(0)
    assert started == ["mid"]
    r.complete("mid", True)
    started = r.tick(0)
    assert started == ["low"]

def test_fifo_same_priority():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=5)
    r.submit("b", priority=5)
    r.submit("c", priority=5)
    assert r.tick(0) == ["a"]
    r.complete("a", True)
    assert r.tick(0) == ["b"]
    r.complete("b", True)
    assert r.tick(0) == ["c"]

def test_failed_state():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    r.tick(0)
    r.complete("a", success=False)
    assert r.get_state("a") == "FAILED"
    assert r.get_state("a") != "COMPLETED"

def test_resubmit_after_completed():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    r.tick(0)
    r.complete("a", True)
    assert r.get_state("a") == "COMPLETED"
    assert r.submit("a", priority=0) == True
    assert r.get_state("a") == "PENDING"

def test_resubmit_after_failed():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    r.tick(0)
    r.complete("a", success=False)
    assert r.get_state("a") == "FAILED"
    assert r.submit("a", priority=0) == True
    assert r.get_state("a") == "PENDING"

def test_resubmit_after_cancelled():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    assert r.cancel("a") == True
    assert r.get_state("a") == "CANCELLED"
    assert r.submit("a", priority=0) == True
    assert r.get_state("a") == "PENDING"

def test_dedup_pending_and_running():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    assert r.submit("a", priority=0) == False
    r.tick(0)
    assert r.submit("a", priority=0) == False
    assert r.get_state("a") == "RUNNING"

def test_complete_releases_slot():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    r.submit("a", priority=0)
    r.submit("b", priority=0)
    assert r.tick(0) == ["a"]
    r.complete("a", True)
    assert r.tick(0) == ["b"]
    assert r.get_state("b") == "RUNNING"

def test_set_rate_caps_tokens():
    r = ThrottledRunner(max_concurrent=10, rps=10, burst=10)
    r.tick(5)
    r.set_rate(rps=1, burst=2)
    for i in range(5):
        r.submit(f"t{i}", priority=0)
    started = r.tick(5)
    assert len(started) == 2

def test_unknown_state():
    r = ThrottledRunner(max_concurrent=1, rps=10, burst=10)
    assert r.get_state("nope") == "UNKNOWN"
    assert r.cancel("nope") == False

def test_cancelled_does_not_consume_token():
    r = ThrottledRunner(max_concurrent=10, rps=10, burst=10)
    r.submit("a", priority=0)
    r.submit("b", priority=0)
    r.cancel("a")
    started = r.tick(0)
    assert started == ["b"]
    r.submit("c", priority=0)
    r.submit("d", priority=0)
    for i in range(9):
        r.submit(f"x{i}", priority=0)
    started2 = r.tick(0)
    assert len(started2) == 9

def test_priority_with_token_limit():
    r = ThrottledRunner(max_concurrent=10, rps=1, burst=1)
    r.submit("low", priority=1)
    r.submit("high", priority=10)
    started = r.tick(0)
    assert started == ["high"]
    started = r.tick(1)
    assert started == ["low"]