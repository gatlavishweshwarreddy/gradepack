import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
import pytest
from scheduler import TaskScheduler

def test_dependency_all_required():
    # D depends on A and B, D priority higher than B, should not jump ahead
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("A", priority=10, deps=[], duration=1)
    s.add_task("B", priority=1, deps=[], duration=1)
    s.add_task("D", priority=5, deps=["A", "B"], duration=1)
    order = s.run(max_ticks=10)
    # Correct: A first (highest priority among ready), then B (only remaining ready), then D
    assert order == ["A", "B", "D"], f"got {order}, D must wait for all deps"

def test_priority_stable_tie_break():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    # insertion order c,b,a with same priority -> must execute in insertion order
    s.add_task("c", priority=5, deps=[], duration=1)
    s.add_task("b", priority=5, deps=[], duration=1)
    s.add_task("a", priority=5, deps=[], duration=1)
    order = s.run(max_ticks=10)
    assert order == ["c", "b", "a"], f"stable tie-break failed, got {order}"

def test_priority_order():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("low", priority=1, deps=[], duration=1)
    s.add_task("high", priority=10, deps=[], duration=1)
    s.add_task("mid", priority=5, deps=[], duration=1)
    order = s.run(max_ticks=10)
    assert order == ["high", "mid", "low"], f"priority order wrong: {order}"

def test_cancellation_transitive():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("A", priority=10, deps=[], duration=1)
    s.add_task("B", priority=5, deps=["A"], duration=1)
    s.add_task("C", priority=1, deps=["B"], duration=1)
    s.cancel("A")
    s.run(max_ticks=10)
    assert s.get_state("A") == "CANCELLED"
    assert s.get_state("B") == "CANCELLED", "B should be cancelled transitively"
    assert s.get_state("C") == "CANCELLED", "C should be cancelled transitively via B"

def test_cancellation_direct():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("A", priority=10, deps=[], duration=1)
    s.add_task("B", priority=5, deps=["A"], duration=1)
    s.add_task("C", priority=1, deps=[], duration=1)
    s.cancel("A")
    order = s.run(max_ticks=10)
    assert "B" not in order
    assert s.get_state("B") == "CANCELLED"
    assert "C" in order

def test_rate_limit_burst():
    s = TaskScheduler(rate_capacity=2, rate_refill_per_tick=1, max_concurrent=10)
    for i in range(5):
        s.add_task(f"t{i}", priority=0, deps=[], duration=1)
    s.run(max_ticks=10)
    # with capacity 2, refill 1 per tick, 5 tasks need ticks 0,0,1,2,3 to start
    assert s.get_start_tick("t0") == 0
    assert s.get_start_tick("t1") == 0
    assert s.get_start_tick("t2") == 1, f"t2 start {s.get_start_tick('t2')} expected 1"
    assert s.get_start_tick("t3") == 2, f"t3 start {s.get_start_tick('t3')} expected 2"
    assert s.get_start_tick("t4") == 3, f"t4 start {s.get_start_tick('t4')} expected 3"
    # ensure no more than capacity at tick 0
    starts_at_0 = [tid for tid in ["t0","t1","t2","t3","t4"] if s.get_start_tick(tid)==0]
    assert len(starts_at_0) == 2, f"burst beyond capacity: {starts_at_0}"

def test_rate_limit_refill():
    s = TaskScheduler(rate_capacity=1, rate_refill_per_tick=1, max_concurrent=10)
    for i in range(3):
        s.add_task(f"x{i}", priority=0, deps=[], duration=1)
    s.run(max_ticks=10)
    assert s.get_start_tick("x0") == 0
    assert s.get_start_tick("x1") == 1
    assert s.get_start_tick("x2") == 2

def test_rate_limit_no_burst_beyond_capacity():
    s = TaskScheduler(rate_capacity=1, rate_refill_per_tick=1, max_concurrent=10)
    for i in range(4):
        s.add_task(f"r{i}", priority=0, deps=[], duration=1)
    s.run(max_ticks=10)
    # with capacity 1, only 1 per tick
    for i in range(4):
        assert s.get_start_tick(f"r{i}") == i, f"r{i} start {s.get_start_tick(f'r{i}')} != {i}"

def test_operation_count_efficiency():
    s = TaskScheduler(rate_capacity=100, rate_refill_per_tick=100, max_concurrent=10)
    n = 100
    for i in range(n):
        deps = [f"t{i-1}"] if i > 0 else []
        s.add_task(f"t{i}", priority=0, deps=deps, duration=1)
    s.run(max_ticks=300)
    # efficient O(V+E) should be ~ n checks, not n^2
    assert s.dependency_checks <= 500, f"too many dependency checks: {s.dependency_checks} (expected <=500 for O(V+E))"

def test_dependency_chain_order():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("A", priority=0, deps=[], duration=1)
    s.add_task("B", priority=0, deps=["A"], duration=1)
    s.add_task("C", priority=0, deps=["B"], duration=1)
    order = s.run(max_ticks=10)
    assert order == ["A", "B", "C"]

def test_complex_interaction():
    # dependencies + priority + rate limit
    s = TaskScheduler(rate_capacity=2, rate_refill_per_tick=1, max_concurrent=1)
    s.add_task("A", priority=10, deps=[], duration=1)
    s.add_task("B", priority=9, deps=[], duration=1)
    s.add_task("C", priority=8, deps=["A"], duration=1)
    s.add_task("D", priority=7, deps=["B"], duration=1)
    order = s.run(max_ticks=20)
    # max_concurrent=1 forces sequential, priority decides between A and B initially
    # A (10) before B (9), then C depends on A, D depends on B
    # After A completes, ready: B(9), C(8) -> B next, then after B, ready: C(8), D(7) -> C next, then D
    assert order == ["A", "B", "C", "D"], f"complex order wrong: {order}"

def test_state_machine_cancelled_not_rerun():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("A", priority=10, deps=[], duration=1)
    s.add_task("B", priority=5, deps=["A"], duration=1)
    s.cancel("A")
    order = s.run(max_ticks=10)
    assert "A" not in order
    assert "B" not in order
    assert s.get_state("A") == "CANCELLED"
    assert s.get_state("B") == "CANCELLED"

def test_max_concurrent_respected():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("a", priority=3, deps=[], duration=2)
    s.add_task("b", priority=2, deps=[], duration=2)
    s.add_task("c", priority=1, deps=[], duration=2)
    s.run(max_ticks=20)
    # with max_concurrent=1 and duration 2, tasks must be sequential
    # start ticks should be 0,2,4
    assert s.get_start_tick("a") == 0
    assert s.get_start_tick("b") == 2
    assert s.get_start_tick("c") == 4

def test_dependency_waiting_cancelled_propagation_on_run():
    s = TaskScheduler(rate_capacity=10, rate_refill_per_tick=10, max_concurrent=1)
    s.add_task("root", priority=10, deps=[], duration=1)
    s.add_task("mid", priority=5, deps=["root"], duration=1)
    s.add_task("leaf", priority=1, deps=["mid"], duration=1)
    s.add_task("independent", priority=0, deps=[], duration=1)
    s.cancel("root")
    order = s.run(max_ticks=10)
    assert s.get_state("mid") == "CANCELLED"
    assert s.get_state("leaf") == "CANCELLED"
    assert order == ["independent"]