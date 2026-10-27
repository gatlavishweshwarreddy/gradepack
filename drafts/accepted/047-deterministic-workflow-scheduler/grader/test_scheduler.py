import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))

import pytest
from scheduler import Scheduler, Task

def make_task(id, priority=0, resources=None, dependencies=None):
    return Task(id=id, priority=priority, resources=resources or {}, dependencies=dependencies or [])

def test_priority_ordering():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10, "io": 10})
    s.add_task(make_task("c", priority=3))
    s.add_task(make_task("a", priority=1))
    s.add_task(make_task("b", priority=2))
    started = s.tick()
    assert started == ["a", "b", "c"]

def test_tie_break_by_id():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("z", priority=1))
    s.add_task(make_task("a", priority=1))
    s.add_task(make_task("m", priority=1))
    started = s.tick()
    assert started == ["a", "m", "z"]

def test_max_concurrency_enforced():
    s = Scheduler(max_concurrency=2, resource_caps={"cpu": 10})
    for i in range(3):
        s.add_task(make_task(f"t{i}", priority=i))
    started = s.tick()
    assert len(started) == 2
    assert started == ["t0", "t1"]
    # third should remain pending
    assert s.get_state("t2") == Task.PENDING

def test_resource_caps_enforced():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 3, "io": 2})
    s.add_task(make_task("a", priority=0, resources={"cpu": 2, "io": 1}))
    s.add_task(make_task("b", priority=1, resources={"cpu": 2, "io": 1}))
    s.add_task(make_task("c", priority=2, resources={"cpu": 1, "io": 1}))
    started = s.tick()
    # a fits, b would exceed cpu (2+2>3), c fits with a (2+1<=3 and 1+1<=2)
    assert "a" in started
    assert "c" in started
    assert "b" not in started
    assert s.get_state("b") == Task.PENDING

def test_resource_skip_not_block():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 3})
    # running task occupies 2 cpu
    s.add_task(make_task("run", priority=0, resources={"cpu": 2}))
    s.tick()
    assert s.get_state("run") == Task.RUNNING
    # now add ready tasks: high priority needs 2 (won't fit, only 1 left), low priority needs 1 (fits)
    s.add_task(make_task("high", priority=1, resources={"cpu": 2}))
    s.add_task(make_task("low", priority=2, resources={"cpu": 1}))
    started = s.tick()
    assert started == ["low"]
    assert s.get_state("high") == Task.PENDING
    assert s.get_state("low") == Task.RUNNING

def test_running_non_cancellable():
    s = Scheduler(max_concurrency=2, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.tick()
    assert s.get_state("a") == Task.RUNNING
    result = s.cancel("a")
    assert result is False
    assert s.get_state("a") == Task.RUNNING

def test_cancel_pending_and_transitive():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.add_task(make_task("b", priority=0, dependencies=["a"]))
    s.add_task(make_task("c", priority=0, dependencies=["b"]))
    result = s.cancel("a")
    assert result is True
    assert s.get_state("a") == Task.CANCELLED
    assert s.get_state("b") == Task.CANCELLED
    assert s.get_state("c") == Task.CANCELLED

def test_cancel_returns_false_for_terminal():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.tick()
    s.complete("a")
    assert s.get_state("a") == Task.COMPLETED
    assert s.cancel("a") is False
    s.add_task(make_task("b", priority=0))
    s.cancel("b")
    assert s.cancel("b") is False

def test_fail_propagation_transitive():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.add_task(make_task("b", priority=0, dependencies=["a"]))
    s.add_task(make_task("c", priority=0, dependencies=["b"]))
    s.add_task(make_task("d", priority=0, dependencies=["a"]))
    s.tick()
    assert s.get_state("a") == Task.RUNNING
    s.fail("a")
    assert s.get_state("a") == Task.FAILED
    assert s.get_state("b") == Task.CANCELLED
    assert s.get_state("c") == Task.CANCELLED
    assert s.get_state("d") == Task.CANCELLED

def test_fail_releases_all_resources():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 2, "io": 2})
    s.add_task(make_task("a", priority=0, resources={"cpu": 2, "io": 2}))
    s.tick()
    assert s.get_state("a") == Task.RUNNING
    s.fail("a")
    assert s.get_state("a") == Task.FAILED
    # now should be able to start another task needing io
    s.add_task(make_task("b", priority=0, resources={"cpu": 2, "io": 2}))
    started = s.tick()
    assert started == ["b"]
    assert s.get_state("b") == Task.RUNNING

def test_complete_releases_resources():
    s = Scheduler(max_concurrency=1, resource_caps={"cpu": 2})
    s.add_task(make_task("a", priority=0, resources={"cpu": 2}))
    s.add_task(make_task("b", priority=1, resources={"cpu": 2}))
    s.tick()
    assert s.get_state("a") == Task.RUNNING
    assert s.get_state("b") == Task.PENDING
    s.complete("a")
    started = s.tick()
    assert started == ["b"]
    assert s.get_state("b") == Task.RUNNING

def test_dependency_ready_condition():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.add_task(make_task("b", priority=0, dependencies=["a"]))
    started = s.tick()
    assert started == ["a"]
    assert s.get_state("b") == Task.PENDING
    s.complete("a")
    started2 = s.tick()
    assert started2 == ["b"]

def test_add_task_with_failed_dependency_immediately_cancelled():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.tick()
    s.fail("a")
    s.add_task(make_task("b", priority=0, dependencies=["a"]))
    assert s.get_state("b") == Task.CANCELLED
    # transitive
    s.add_task(make_task("c", priority=0, dependencies=["b"]))
    assert s.get_state("c") == Task.CANCELLED

def test_add_task_with_completed_dependency_ready():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.tick()
    s.complete("a")
    s.add_task(make_task("b", priority=0, dependencies=["a"]))
    started = s.tick()
    assert started == ["b"]

def test_complete_non_running_raises():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    with pytest.raises(ValueError):
        s.complete("a")
    s.tick()
    s.complete("a")
    with pytest.raises(ValueError):
        s.complete("a")

def test_fail_non_running_raises():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    with pytest.raises(ValueError):
        s.fail("a")

def test_failed_state_persists():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.tick()
    s.fail("a")
    assert s.get_state("a") == Task.FAILED
    # tick should not change it
    s.tick()
    assert s.get_state("a") == Task.FAILED

def test_cancel_does_not_affect_running_dependents():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    s.add_task(make_task("a", priority=0))
    s.add_task(make_task("b", priority=0, dependencies=["a"]))
    s.tick()
    s.complete("a")
    s.tick()
    assert s.get_state("b") == Task.RUNNING
    # try to cancel a (already completed) should not affect b
    assert s.cancel("a") is False
    assert s.get_state("b") == Task.RUNNING

def test_performance_is_ready_calls():
    # chain of 400 tasks: each depends on previous, so only one ready at a time
    n = 400
    s = Scheduler(max_concurrency=1, resource_caps={"cpu": 10})
    # instrument
    orig = s._is_ready
    count = [0]
    def counting_is_ready(task):
        count[0] += 1
        return orig(task)
    s._is_ready = counting_is_ready

    for i in range(n):
        deps = [f"t{i-1}"] if i > 0 else []
        s.add_task(make_task(f"t{i}", priority=0, dependencies=deps))

    # run chain
    for i in range(n):
        started = s.tick()
        assert started == [f"t{i}"]
        s.complete(f"t{i}")

    # efficient implementation should call _is_ready O(n) times, not O(n^2)
    # starter scans all n each tick => ~80k calls (n*(n+1)/2 avg)
    # threshold 5000 is generous for efficient but catches naive
    assert count[0] < 5000, f"_is_ready called {count[0]} times, expected <5000 (O(n^2) detected)"

def test_tick_maximal_starts():
    s = Scheduler(max_concurrency=10, resource_caps={"cpu": 10})
    for i in range(5):
        s.add_task(make_task(f"t{i}", priority=i, resources={"cpu": 1}))
    started = s.tick()
    assert started == ["t0", "t1", "t2", "t3", "t4"]
    assert len(started) == 5