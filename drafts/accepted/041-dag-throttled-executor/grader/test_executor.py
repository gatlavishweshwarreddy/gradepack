import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
import executor

DAGExecutor = executor.DAGExecutor

def test_token_burst_cap():
    exe = DAGExecutor(max_concurrent=10, rate_limit=2, burst=3)
    assert exe.get_tokens() == 3
    for _ in range(5):
        exe.tick()
    assert exe.get_tokens() == 3, "burst cap must be enforced"
    exe.add_task("a", duration=1)
    exe.add_task("b", duration=1)
    exe.add_task("c", duration=1)
    exe.tick()
    assert exe.get_running_count() == 3
    assert exe.get_tokens() == 0

def test_running_not_cancellable():
    exe = DAGExecutor(max_concurrent=1, rate_limit=10, burst=10)
    exe.add_task("A", duration=2)
    exe.tick()
    assert exe.get_state("A") == DAGExecutor.RUNNING
    result = exe.cancel("A")
    assert result is False, "RUNNING must not be cancellable"
    assert exe.get_state("A") == DAGExecutor.RUNNING

def test_cancel_propagation():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    exe.add_task("A", duration=1)
    exe.add_task("B", duration=1, deps=["A"])
    exe.add_task("C", duration=1, deps=["B"])
    # cancel A while pending/ready
    assert exe.cancel("A") is True
    assert exe.get_state("A") == DAGExecutor.CANCELLED
    exe.tick()
    # B and C should become FAILED transitively
    assert exe.get_state("B") == DAGExecutor.FAILED
    assert exe.get_state("C") == DAGExecutor.FAILED

def test_fail_propagation_and_slot_free():
    exe = DAGExecutor(max_concurrent=1, rate_limit=10, burst=10)
    exe.add_task("A", duration=5)
    exe.add_task("B", duration=1, deps=["A"])
    exe.add_task("C", duration=1)
    exe.tick()  # A and C start, but max_concurrent=1, so only one starts by priority/insertion
    # With max_concurrent=1, only A should be running (insertion order)
    assert exe.get_state("A") == DAGExecutor.RUNNING
    # fail A
    assert exe.fail_task("A") is True
    assert exe.get_state("A") == DAGExecutor.FAILED
    exe.tick()
    assert exe.get_state("B") == DAGExecutor.FAILED
    # slot should be free, C should be able to run
    # C was READY, should now be RUNNING or COMPLETED depending on timing
    assert exe.get_state("C") in (DAGExecutor.RUNNING, DAGExecutor.COMPLETED, DAGExecutor.READY)

def test_concurrency_slot_freed_on_fail():
    exe = DAGExecutor(max_concurrent=1, rate_limit=10, burst=10)
    exe.add_task("A", duration=10)
    exe.tick()
    assert exe.get_running_count() == 1
    exe.fail_task("A")
    assert exe.get_running_count() == 0, "slot must be freed on fail"
    exe.add_task("B", duration=1)
    exe.tick()
    assert exe.get_state("B") == DAGExecutor.RUNNING

def test_priority_ordering():
    exe = DAGExecutor(max_concurrent=1, rate_limit=1, burst=1)
    exe.add_task("low", duration=1, priority=1)
    exe.add_task("high", duration=1, priority=10)
    exe.add_task("mid", duration=1, priority=5)
    exe.tick()  # only 1 token, should pick high
    assert exe.get_state("high") == DAGExecutor.RUNNING
    assert exe.get_state("mid") == DAGExecutor.READY
    assert exe.get_state("low") == DAGExecutor.READY
    exe.tick()  # high completes, next should be mid
    assert exe.get_state("high") == DAGExecutor.COMPLETED
    assert exe.get_state("mid") == DAGExecutor.RUNNING

def test_concurrency_limit():
    exe = DAGExecutor(max_concurrent=2, rate_limit=10, burst=10)
    for i in range(5):
        exe.add_task(f"t{i}", duration=2)
    exe.tick()
    assert exe.get_running_count() == 2
    exe.tick()
    # still 2 running (duration 2 needs 2 ticks after start)
    assert exe.get_running_count() == 2
    exe.tick()
    # first 2 completed, next 2 started
    assert exe.get_running_count() == 2

def test_duration_correctness():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    exe.add_task("A", duration=2)
    exe.tick()
    assert exe.get_state("A") == DAGExecutor.RUNNING
    exe.tick()
    assert exe.get_state("A") == DAGExecutor.RUNNING, "duration 2 should need 2 full ticks in RUNNING"
    exe.tick()
    assert exe.get_state("A") == DAGExecutor.COMPLETED

def test_tick_ordering_slot_reuse():
    exe = DAGExecutor(max_concurrent=1, rate_limit=10, burst=10)
    exe.add_task("A", duration=1)
    exe.add_task("B", duration=1)
    exe.tick()  # A starts
    assert exe.get_state("A") == DAGExecutor.RUNNING
    assert exe.get_state("B") == DAGExecutor.READY
    exe.tick()  # A completes, B should start same tick
    assert exe.get_state("A") == DAGExecutor.COMPLETED
    assert exe.get_state("B") == DAGExecutor.RUNNING, "slot freed by completion must be reusable same tick"

def test_dependency_promotion():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    exe.add_task("A", duration=1)
    exe.add_task("B", duration=1, deps=["A"])
    exe.tick()  # A starts, B pending
    assert exe.get_state("A") == DAGExecutor.RUNNING
    assert exe.get_state("B") == DAGExecutor.PENDING
    exe.tick()  # A completes, B should become RUNNING same tick? Actually promotion then scheduling same tick
    # After A completes, B should be promoted and scheduled in same tick
    # So after tick2, A completed, B running
    assert exe.get_state("A") == DAGExecutor.COMPLETED
    assert exe.get_state("B") == DAGExecutor.RUNNING

def test_failed_task_not_scheduled():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    exe.add_task("A", duration=1)
    exe.add_task("B", duration=1, deps=["A"])
    exe.cancel("A")
    exe.tick()
    assert exe.get_state("B") == DAGExecutor.FAILED
    exe.tick()
    assert exe.get_state("B") == DAGExecutor.FAILED
    assert exe.get_running_count() == 0

def test_cycle_detection_self():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    try:
        exe.add_task("A", duration=1, deps=["A"])
        assert False, "self-cycle must raise ValueError"
    except ValueError:
        pass

def test_cycle_detection_indirect():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    exe.add_task("A", duration=1, deps=["B"])
    try:
        exe.add_task("B", duration=1, deps=["A"])
        assert False, "indirect cycle must raise ValueError"
    except ValueError:
        pass

def test_rate_limiting():
    exe = DAGExecutor(max_concurrent=10, rate_limit=1, burst=1)
    exe.add_task("a", duration=1)
    exe.add_task("b", duration=1)
    exe.add_task("c", duration=1)
    exe.tick()
    assert exe.get_running_count() == 1
    exe.tick()
    # one completed, one new started, still 1 running
    assert exe.get_running_count() == 1
    assert exe.get_tokens() == 0

def test_performance_scan_count():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    n = 500
    exe.add_task("t0", duration=1)
    for i in range(1, n):
        exe.add_task(f"t{i}", duration=1, deps=[f"t{i-1}"])
    start = time.time()
    for _ in range(n+5):
        exe.tick()
        if time.time() - start > 2.0:
            break
    assert exe.get_state(f"t{n-1}") == DAGExecutor.COMPLETED
    # efficient implementation must not do linear scans per edge
    assert exe._scan_count < 5000, f"scan_count too high: {exe._scan_count}, must avoid O(n^2) lookups"
    assert time.time() - start < 1.5, "too slow, likely O(n^2) per tick"

def test_cancel_returns_false_for_completed():
    exe = DAGExecutor(max_concurrent=10, rate_limit=10, burst=10)
    exe.add_task("A", duration=1)
    exe.tick()
    exe.tick()
    assert exe.get_state("A") == DAGExecutor.COMPLETED
    assert exe.cancel("A") is False
    assert exe.fail_task("A") is False