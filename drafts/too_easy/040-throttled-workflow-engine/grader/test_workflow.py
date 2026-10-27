import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
from workflow import Scheduler, TokenBucket, FakeClock
import pytest

def make_scheduler(max_concurrent=1, rate=10, burst=10, start=0.0):
    clock = FakeClock(start)
    bucket = TokenBucket(rate=rate, burst=burst, clock=clock)
    sched = Scheduler(max_concurrent=max_concurrent, bucket=bucket, clock=clock)
    return sched, bucket, clock

def test_token_bucket_cap():
    clock = FakeClock(0)
    bucket = TokenBucket(rate=1, burst=2, clock=clock)
    assert bucket.try_consume(2) == True
    assert abs(bucket.tokens - 0) < 1e-6
    clock.advance(10)
    bucket._refill()
    # must be capped at burst=2, not 10
    assert bucket.tokens <= 2 + 1e-6, f"token cap violated: {bucket.tokens}"
    assert abs(bucket.tokens - 2) < 1e-6

def test_token_bucket_refill_and_consume():
    clock = FakeClock(0)
    bucket = TokenBucket(rate=2, burst=2, clock=clock)
    assert bucket.try_consume(2) == True
    assert bucket.try_consume(1) == False
    clock.advance(0.5)
    # 0.5 * 2 = 1 token refilled
    assert bucket.try_consume(1) == True
    assert bucket.try_consume(1) == False

def test_token_bucket_time_until_next_token():
    clock = FakeClock(0)
    bucket = TokenBucket(rate=1, burst=1, clock=clock)
    assert bucket.try_consume(1) == True
    # need 1 sec for next token
    dt = bucket.time_until_next_token()
    assert abs(dt - 1.0) < 1e-6, f"expected 1.0 got {dt}"
    clock.advance(0.5)
    dt2 = bucket.time_until_next_token()
    assert abs(dt2 - 0.5) < 1e-6, f"expected 0.5 got {dt2}"

def test_cancel_pending_and_queued():
    sched, _, _ = make_scheduler(max_concurrent=1, rate=10, burst=10)
    sched.submit("a", fn=lambda: 1, duration=5)
    sched.submit("b", fn=lambda: 2, dependencies=["a"], duration=0)
    # b is PENDING waiting for a
    assert sched.get_status("b") == "PENDING"
    assert sched.cancel("b") == True
    assert sched.get_status("b") == "CANCELLED"
    # a is QUEUED (no dependencies)
    assert sched.get_status("a") == "QUEUED"
    assert sched.cancel("a") == True
    assert sched.get_status("a") == "CANCELLED"

def test_cancel_running_not_allowed():
    sched, _, clock = make_scheduler(max_concurrent=1, rate=10, burst=10)
    sched.submit("a", fn=lambda: 1, duration=5)
    sched.submit("b", fn=lambda: 2, duration=5)
    # manually start without completing
    sched._refresh_pending()
    sched._enqueue_ready()
    started = sched._start_ready_tasks()
    assert started == 1
    assert sched.get_status("a") == "RUNNING"
    assert sched.get_status("b") == "QUEUED"
    # RUNNING must not be cancellable
    assert sched.cancel("a") == False, "RUNNING task must not be cancellable"
    assert sched.get_status("a") == "RUNNING"
    # QUEUED should be cancellable
    assert sched.cancel("b") == True
    assert sched.get_status("b") == "CANCELLED"
    # terminal not cancellable
    sched.clock.advance(5)
    sched._complete_due_tasks()
    assert sched.get_status("a") == "SUCCEEDED"
    assert sched.cancel("a") == False

def test_failed_task_marks_dependents_failed():
    sched, _, _ = make_scheduler(max_concurrent=2, rate=10, burst=10)
    def bad():
        raise ValueError("boom")
    sched.submit("a", fn=bad, duration=0)
    sched.submit("b", fn=lambda: 2, dependencies=["a"], duration=0)
    sched.submit("c", fn=lambda: 3, dependencies=["b"], duration=0)
    sched.run_until_complete()
    assert sched.get_status("a") == "FAILED", f"expected FAILED got {sched.get_status('a')}"
    assert sched.get_status("b") == "FAILED", f"dependent of FAILED should be FAILED, got {sched.get_status('b')}"
    assert sched.get_status("c") == "FAILED"

def test_cancelled_dependency_marks_dependents_failed():
    sched, _, _ = make_scheduler(max_concurrent=1, rate=10, burst=10)
    sched.submit("a", fn=lambda: 1, duration=0)
    sched.submit("b", fn=lambda: 2, dependencies=["a"], duration=0)
    # cancel a while QUEUED
    assert sched.cancel("a") == True
    sched.run_until_complete()
    assert sched.get_status("a") == "CANCELLED"
    # b depends on cancelled -> must be FAILED
    assert sched.get_status("b") == "FAILED", f"dependent of CANCELLED should be FAILED, got {sched.get_status('b')}"

def test_priority_ordering():
    sched, _, _ = make_scheduler(max_concurrent=1, rate=10, burst=10)
    order = []
    def make_fn(name):
        def fn():
            order.append(name)
            return name
        return fn
    sched.submit("low", fn=make_fn("low"), priority=10, duration=0)
    sched.submit("high", fn=make_fn("high"), priority=1, duration=0)
    sched.submit("mid", fn=make_fn("mid"), priority=5, duration=0)
    sched.run_until_complete()
    assert order == ["high", "mid", "low"], f"priority ordering violated: {order}"

def test_priority_tie_break_submission_order():
    sched, _, _ = make_scheduler(max_concurrent=1, rate=10, burst=10)
    order = []
    def make_fn(name):
        def fn():
            order.append(name)
            return name
        return fn
    # same priority, submission order should win, not alphabetical
    sched.submit("c", fn=make_fn("c"), priority=0, duration=0)
    sched.submit("a", fn=make_fn("a"), priority=0, duration=0)
    sched.submit("b", fn=make_fn("b"), priority=0, duration=0)
    sched.run_until_complete()
    assert order == ["c", "a", "b"], f"tie-break should be submission order, got {order}"

def test_concurrency_limit_enforced():
    sched, _, clock = make_scheduler(max_concurrent=2, rate=10, burst=10)
    for i in range(4):
        sched.submit(f"t{i}", fn=lambda: 1, duration=5)
    sched.run_until_complete()
    # with concurrency 2, 4 tasks of duration 5 should take 10 seconds
    # if concurrency is violated (e.g., 3 or 4 at once), it would take 5 seconds
    total_time = clock.now()
    assert abs(total_time - 10) < 1e-6, f"concurrency limit violated, total_time={total_time} expected 10"
    # also check no task started before its turn
    # all tasks should have succeeded
    for i in range(4):
        assert sched.get_status(f"t{i}") == "SUCCEEDED"

def test_concurrency_off_by_one():
    sched, _, clock = make_scheduler(max_concurrent=2, rate=100, burst=10)
    for i in range(3):
        sched.submit(f"x{i}", fn=lambda: 1, duration=5)
    sched.run_until_complete()
    total_time = clock.now()
    # with max_concurrent=2, 3 tasks duration 5 => 10 seconds (2 in parallel, 1 after)
    # with off-by-one (<=), it would allow 3 at once => 5 seconds
    assert abs(total_time - 10) < 1e-6, f"off-by-one concurrency bug, total_time={total_time}"

def test_rate_limiting_respected():
    sched, bucket, clock = make_scheduler(max_concurrent=10, rate=1, burst=1)
    for i in range(3):
        sched.submit(f"r{i}", fn=lambda: 1, duration=0)
    sched.run_until_complete()
    # burst 1, rate 1/s: tasks should start at t=0,1,2 => total time 2
    total_time = clock.now()
    assert abs(total_time - 2) < 1e-6, f"rate limiting violated, total_time={total_time} expected 2"
    # check start times are spaced
    times = [sched.tasks[f"r{i}"].start_time for i in range(3)]
    assert times[0] == 0
    assert abs(times[1] - 1) < 1e-6
    assert abs(times[2] - 2) < 1e-6

def test_dependency_ordering():
    sched, _, _ = make_scheduler(max_concurrent=2, rate=10, burst=10)
    order = []
    def make_fn(name):
        def fn():
            order.append(name)
            return name
        return fn
    sched.submit("a", fn=make_fn("a"), duration=1)
    sched.submit("b", fn=make_fn("b"), dependencies=["a"], duration=1)
    sched.submit("c", fn=make_fn("c"), dependencies=["a"], duration=1)
    sched.submit("d", fn=make_fn("d"), dependencies=["b", "c"], duration=1)
    sched.run_until_complete()
    # a must be first, d must be last
    assert order[0] == "a"
    assert order[-1] == "d"
    assert sched.get_status("d") == "SUCCEEDED"
    # b and c after a, before d
    assert order.index("b") > order.index("a")
    assert order.index("c") > order.index("a")
    assert order.index("d") > order.index("b")
    assert order.index("d") > order.index("c")

def test_no_duplicate_execution():
    sched, _, _ = make_scheduler(max_concurrent=2, rate=10, burst=10)
    counts = {}
    def make_fn(name):
        def fn():
            counts[name] = counts.get(name, 0) + 1
            return name
        return fn
    for i in range(5):
        sched.submit(f"dup{i}", fn=make_fn(f"dup{i}"), duration=1)
    sched.run_until_complete()
    for i in range(5):
        assert counts.get(f"dup{i}", 0) == 1, f"task dup{i} executed {counts.get(f'dup{i}',0)} times"

def test_terminal_states_immutable():
    sched, _, _ = make_scheduler(max_concurrent=1, rate=10, burst=10)
    sched.submit("a", fn=lambda: 1, duration=0)
    sched.run_until_complete()
    assert sched.get_status("a") == "SUCCEEDED"
    # trying to cancel terminal should fail and not change status
    assert sched.cancel("a") == False
    assert sched.get_status("a") == "SUCCEEDED"

def test_mixed_concurrency_and_rate():
    # burst 2, rate 1, concurrency 2, 4 tasks duration 2
    # At t0: 2 tokens burst, start 2 tasks (concurrency 2)
    # At t1: 1 token refilled, but concurrency full until t2
    # At t2: 2 tasks complete, 1 more token (total 2 tokens at t2? burst 2, so capped)
    # Should start next 2 tasks at t2
    # Complete at t4
    sched, _, clock = make_scheduler(max_concurrent=2, rate=1, burst=2)
    for i in range(4):
        sched.submit(f"m{i}", fn=lambda: 1, duration=2)
    sched.run_until_complete()
    total_time = clock.now()
    assert abs(total_time - 4) < 1e-6, f"mixed concurrency/rate failed, total_time={total_time} expected 4"

def test_failed_task_not_retried_and_no_token_leak():
    sched, bucket, clock = make_scheduler(max_concurrent=1, rate=1, burst=1)
    call_count = [0]
    def bad():
        call_count[0] += 1
        raise RuntimeError("fail")
    sched.submit("a", fn=bad, duration=0)
    sched.submit("b", fn=lambda: 1, duration=0)
    sched.run_until_complete()
    assert sched.get_status("a") == "FAILED"
    assert call_count[0] == 1, "failed task should not be retried"
    assert sched.get_status("b") == "SUCCEEDED"
    # b should have started at t=1 due to rate limit (a consumed token at t0)
    assert abs(sched.tasks["b"].start_time - 1) < 1e-6