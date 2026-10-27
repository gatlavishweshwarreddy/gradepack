import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
import scheduler
from scheduler import Scheduler, TaskState

def test_token_bucket_cap():
    s = Scheduler(max_concurrency=10, rate_per_sec=5, burst=2)
    s.submit("t1", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.tick(0)
    s.tick(100)
    assert s.bucket.tokens == 2, f"tokens should cap at burst 2, got {s.bucket.tokens}"
    s2 = Scheduler(max_concurrency=10, rate_per_sec=5, burst=2)
    for i in range(5):
        s2.submit(f"t{i}", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s2.tick(0)
    running = [tid for tid, t in s2.tasks.items() if t.state == TaskState.RUNNING]
    assert len(running) == 2, f"burst should limit to 2, got {len(running)}"

def test_token_bucket_refill():
    s = Scheduler(max_concurrency=10, rate_per_sec=1, burst=1)
    s.submit("t1", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.submit("t2", priority=1, deps=[], func=lambda: 2, duration=1.0)
    s.tick(0)
    assert s.get_state("t1") == TaskState.RUNNING
    assert s.get_state("t2") == TaskState.READY
    s.tick(0.5)
    assert s.get_state("t2") == TaskState.READY, "not enough tokens at 0.5s"
    s.tick(1)
    assert s.get_state("t1") == TaskState.COMPLETED
    assert s.get_state("t2") == TaskState.RUNNING

def test_running_non_cancellable():
    s = Scheduler(max_concurrency=1, rate_per_sec=10, burst=10)
    s.submit("long", priority=1, deps=[], func=lambda: 42, duration=10.0)
    s.tick(0)
    assert s.get_state("long") == TaskState.RUNNING
    result = s.cancel("long")
    assert result == False, "RUNNING task should not be cancellable"
    assert s.get_state("long") == TaskState.RUNNING
    s.tick(10)
    assert s.get_state("long") == TaskState.COMPLETED

def test_cancel_pending_and_ready():
    s = Scheduler(max_concurrency=1, rate_per_sec=10, burst=10)
    s.submit("a", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.submit("b", priority=1, deps=[], func=lambda: 2, duration=1.0)
    s.submit("c", priority=1, deps=[], func=lambda: 3, duration=1.0)
    # cancel pending b before tick
    assert s.cancel("b") == True
    assert s.get_state("b") == TaskState.CANCELLED
    s.tick(0)
    assert s.get_state("a") == TaskState.RUNNING
    assert s.get_state("b") == TaskState.CANCELLED
    # cancel terminal should fail
    s.tick(1)
    assert s.cancel("a") == False
    assert s.get_state("a") == TaskState.COMPLETED

def test_failed_propagation():
    def failing():
        raise ValueError("fail")
    s = Scheduler(max_concurrency=10, rate_per_sec=10, burst=10)
    s.submit("a", priority=1, deps=[], func=failing, duration=1.0)
    s.submit("b", priority=1, deps=["a"], func=lambda: 42, duration=1.0)
    s.tick(0)
    assert s.get_state("a") == TaskState.RUNNING
    s.tick(1)
    assert s.get_state("a") == TaskState.FAILED
    assert s.get_state("b") == TaskState.FAILED, "dependent of FAILED should be FAILED"

def test_cancel_propagation():
    s = Scheduler(max_concurrency=10, rate_per_sec=10, burst=10)
    s.submit("a", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.submit("b", priority=1, deps=["a"], func=lambda: 2, duration=1.0)
    s.cancel("a")
    assert s.get_state("a") == TaskState.CANCELLED
    s.tick(0)
    assert s.get_state("b") == TaskState.FAILED, "dependent of CANCELLED should be FAILED"

def test_failed_chain_propagation():
    def failing():
        raise RuntimeError("oops")
    s = Scheduler(max_concurrency=10, rate_per_sec=10, burst=10)
    s.submit("a", priority=1, deps=[], func=failing, duration=1.0)
    s.submit("b", priority=1, deps=["a"], func=lambda: 1, duration=1.0)
    s.submit("c", priority=1, deps=["b"], func=lambda: 2, duration=1.0)
    s.tick(0)
    s.tick(1)
    assert s.get_state("a") == TaskState.FAILED
    assert s.get_state("b") == TaskState.FAILED
    # c should also be FAILED after next tick (propagation is per tick)
    s.tick(2)
    assert s.get_state("c") == TaskState.FAILED

def test_priority_order():
    s = Scheduler(max_concurrency=1, rate_per_sec=10, burst=10)
    s.submit("low", priority=10, deps=[], func=lambda: 1, duration=1.0)
    s.submit("high", priority=1, deps=[], func=lambda: 2, duration=1.0)
    s.submit("mid", priority=5, deps=[], func=lambda: 3, duration=1.0)
    s.tick(0)
    assert s.get_state("high") == TaskState.RUNNING
    s.tick(1)
    assert s.get_state("high") == TaskState.COMPLETED
    assert s.get_state("mid") == TaskState.RUNNING
    s.tick(2)
    assert s.get_state("mid") == TaskState.COMPLETED
    assert s.get_state("low") == TaskState.RUNNING

def test_priority_fifo_tiebreak():
    s = Scheduler(max_concurrency=1, rate_per_sec=10, burst=10)
    s.submit("task_b", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.submit("task_a", priority=1, deps=[], func=lambda: 2, duration=1.0)
    s.submit("task_c", priority=1, deps=[], func=lambda: 3, duration=1.0)
    s.tick(0)
    assert s.get_state("task_b") == TaskState.RUNNING, "FIFO tie-break: first submitted should run first"
    assert s.get_state("task_a") == TaskState.READY
    s.tick(1)
    assert s.get_state("task_b") == TaskState.COMPLETED
    assert s.get_state("task_a") == TaskState.RUNNING
    s.tick(2)
    assert s.get_state("task_a") == TaskState.COMPLETED
    assert s.get_state("task_c") == TaskState.RUNNING

def test_max_concurrency():
    s = Scheduler(max_concurrency=2, rate_per_sec=10, burst=10)
    for i in range(4):
        s.submit(f"t{i}", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.tick(0)
    running = [tid for tid, t in s.tasks.items() if t.state == TaskState.RUNNING]
    assert len(running) == 2, f"expected 2 running, got {len(running)}"
    s.tick(1)
    completed = [tid for tid, t in s.tasks.items() if t.state == TaskState.COMPLETED]
    assert len(completed) == 2
    running = [tid for tid, t in s.tasks.items() if t.state == TaskState.RUNNING]
    assert len(running) == 2
    s.tick(2)
    completed = [tid for tid, t in s.tasks.items() if t.state == TaskState.COMPLETED]
    assert len(completed) == 4

def test_dependency_chain():
    s = Scheduler(max_concurrency=10, rate_per_sec=10, burst=10)
    s.submit("a", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.submit("b", priority=1, deps=["a"], func=lambda: 2, duration=1.0)
    s.submit("c", priority=1, deps=["b"], func=lambda: 3, duration=1.0)
    s.tick(0)
    assert s.get_state("a") == TaskState.RUNNING
    assert s.get_state("b") == TaskState.PENDING
    s.tick(1)
    assert s.get_state("a") == TaskState.COMPLETED
    assert s.get_state("b") == TaskState.RUNNING
    s.tick(2)
    assert s.get_state("b") == TaskState.COMPLETED
    assert s.get_state("c") == TaskState.RUNNING
    s.tick(3)
    assert s.get_state("c") == TaskState.COMPLETED

def test_tick_returns_completed_order():
    s = Scheduler(max_concurrency=10, rate_per_sec=10, burst=10)
    s.submit("low", priority=10, deps=[], func=lambda: 1, duration=1.0)
    s.submit("high", priority=1, deps=[], func=lambda: 2, duration=1.0)
    s.tick(0)
    completed = s.tick(1)
    assert set(completed) == {"low", "high"}
    assert completed == ["high", "low"], f"completed should be priority ordered, got {completed}"

def test_performance_no_expensive_sort():
    scheduler._expensive_sort_calls = 0
    s = Scheduler(max_concurrency=10, rate_per_sec=1000, burst=1000)
    for i in range(200):
        s.submit(f"task_{i}", priority=i % 5, deps=[], func=lambda: 42, duration=1.0)
    s.tick(0)
    s.tick(1)
    assert scheduler._expensive_sort_calls == 0, f"expensive sort called {scheduler._expensive_sort_calls} times, expected 0 (use heap, not sort)"

def test_state_machine_terminal():
    s = Scheduler(max_concurrency=10, rate_per_sec=10, burst=10)
    s.submit("a", priority=1, deps=[], func=lambda: 1, duration=1.0)
    s.tick(0)
    s.tick(1)
    assert s.get_state("a") == TaskState.COMPLETED
    assert s.cancel("a") == False

def test_submit_validation():
    s = Scheduler(max_concurrency=1, rate_per_sec=10, burst=10)
    s.submit("a", priority=1, deps=[], func=lambda: 1, duration=1.0)
    try:
        s.submit("a", priority=1, deps=[], func=lambda: 1, duration=1.0)
        assert False, "duplicate task should raise"
    except ValueError:
        pass
    try:
        s.submit("b", priority=1, deps=["unknown"], func=lambda: 1, duration=1.0)
        assert False, "unknown dep should raise"
    except ValueError:
        pass
    try:
        s.tick(-1)
        assert False, "time going backwards should raise"
    except ValueError:
        pass