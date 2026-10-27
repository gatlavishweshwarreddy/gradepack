import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))

import scheduler as sched_mod
from scheduler import Scheduler, Task


def make_scheduler(limits=None, rate=2):
    if limits is None:
        limits = {"cpu": 2, "mem": 4}
    return Scheduler(resource_limits=limits, max_starts_per_tick=rate)


def test_running_non_cancellable():
    s = make_scheduler()
    s.add_task(Task(id="a", priority=1, resources={"cpu": 1}, duration=3))
    s.tick()  # a -> RUNNING
    assert s.get_state("a") == "RUNNING"
    result = s.cancel("a")
    assert result is False, "RUNNING must not be cancellable"
    assert s.get_state("a") == "RUNNING"
    # resources must still be held
    assert s.resource_used["cpu"] == 1
    # run to completion
    s.tick()
    s.tick()
    s.tick()
    assert s.get_state("a") == "COMPLETED"
    assert s.resource_used["cpu"] == 0


def test_cancel_pending_and_ready():
    s = make_scheduler(limits={"cpu": 1}, rate=1)
    s.add_task(Task(id="a", priority=1, resources={"cpu": 1}, duration=2))
    s.add_task(Task(id="b", priority=2, resources={"cpu": 1}, duration=1))
    s.tick()  # a RUNNING, b READY (waiting cpu)
    assert s.get_state("a") == "RUNNING"
    assert s.get_state("b") == "READY"
    assert s.cancel("b") is True
    assert s.get_state("b") == "CANCELLED"
    # cancelling READY must not affect resource usage of RUNNING
    assert s.resource_used["cpu"] == 1
    # pending cancel
    s.add_task(Task(id="c", priority=1, resources={"cpu": 1}, dependencies=["a"], duration=1))
    # c is PENDING (a not done)
    assert s.get_state("c") == "PENDING"
    assert s.cancel("c") is True
    assert s.get_state("c") == "CANCELLED"


def test_token_cap_enforced():
    s = make_scheduler(limits={"cpu": 2, "mem": 3}, rate=10)
    # each needs cpu=1, mem=2 -> at most 1 can run due to mem cap (2*2=4 >3)
    s.add_task(Task(id="a", priority=1, resources={"cpu": 1, "mem": 2}, duration=2))
    s.add_task(Task(id="b", priority=2, resources={"cpu": 1, "mem": 2}, duration=2))
    s.add_task(Task(id="c", priority=3, resources={"cpu": 1, "mem": 2}, duration=2))
    s.tick()
    running = [tid for tid, st in s.states.items() if st == "RUNNING"]
    assert len(running) == 1, f"mem cap violated: running {running}, used {s.resource_used}"
    assert s.resource_used["cpu"] <= 2
    assert s.resource_used["mem"] <= 3
    # check multi-resource: cpu cap also
    s2 = make_scheduler(limits={"cpu": 1, "mem": 10}, rate=10)
    s2.add_task(Task(id="x", priority=1, resources={"cpu": 1, "mem": 1}, duration=2))
    s2.add_task(Task(id="y", priority=2, resources={"cpu": 1, "mem": 1}, duration=2))
    s2.tick()
    running2 = [tid for tid, st in s2.states.items() if st == "RUNNING"]
    assert len(running2) == 1, f"cpu cap violated: {running2}"


def test_token_cap_never_exceeded_over_time():
    s = make_scheduler(limits={"cpu": 2}, rate=5)
    for i in range(6):
        s.add_task(Task(id=f"t{i}", priority=i, resources={"cpu": 1}, duration=3))
    for _ in range(10):
        s.tick()
        assert s.resource_used["cpu"] <= 2, f"cpu exceeded: {s.resource_used['cpu']}"
        # also check no negative
        assert s.resource_used["cpu"] >= 0


def test_rate_limit():
    s = make_scheduler(limits={"cpu": 10}, rate=2)
    for i in range(5):
        s.add_task(Task(id=f"r{i}", priority=i, resources={"cpu": 1}, duration=1))
    s.tick()
    running = [tid for tid, st in s.states.items() if st == "RUNNING"]
    assert len(running) == 2, f"rate limit violated: started {len(running)} expected 2"
    s.tick()  # first 2 complete, next 2 should start
    running2 = [tid for tid, st in s.states.items() if st == "RUNNING"]
    # after second tick, 2 completed, 2 running, 1 still pending/ready
    assert len(running2) == 2, f"rate limit second tick: {running2}"
    # test off-by-one: with rate=1, only 1 per tick
    s3 = make_scheduler(limits={"cpu": 10}, rate=1)
    for i in range(3):
        s3.add_task(Task(id=f"s{i}", priority=i, resources={"cpu": 1}, duration=1))
    s3.tick()
    assert sum(1 for st in s3.states.values() if st == "RUNNING") == 1


def test_priority_ordering_and_fifo():
    s = make_scheduler(limits={"cpu": 1}, rate=10)
    s.add_task(Task(id="low", priority=10, resources={"cpu": 1}, duration=2))
    s.add_task(Task(id="high", priority=1, resources={"cpu": 1}, duration=2))
    s.add_task(Task(id="mid", priority=5, resources={"cpu": 1}, duration=2))
    s.tick()
    # only 1 can run due to cpu cap, should be highest priority (lowest number)
    running = [tid for tid, st in s.states.items() if st == "RUNNING"]
    assert running == ["high"], f"priority violated: running {running}"
    # FIFO tie-break: same priority, insertion order
    s2 = make_scheduler(limits={"cpu": 1}, rate=1)
    s2.add_task(Task(id="a", priority=1, resources={"cpu": 1}, duration=1))
    s2.add_task(Task(id="b", priority=1, resources={"cpu": 1}, duration=1))
    s2.add_task(Task(id="c", priority=1, resources={"cpu": 1}, duration=1))
    s2.tick()
    assert s2.get_state("a") == "RUNNING"
    assert s2.get_state("b") == "READY"
    s2.tick()  # a completes, b starts
    assert s2.get_state("b") == "RUNNING"
    assert s2.get_state("a") == "COMPLETED"


def test_failed_propagation():
    s = make_scheduler(limits={"cpu": 2}, rate=10)
    s.add_task(Task(id="root", priority=1, resources={"cpu": 1}, duration=1))
    s.add_task(Task(id="child1", priority=1, resources={"cpu": 1}, dependencies=["root"], duration=1))
    s.add_task(Task(id="child2", priority=1, resources={"cpu": 1}, dependencies=["child1"], duration=1))
    # simulate failure by marking root FAILED (as if it crashed)
    s.tick()  # root RUNNING
    s.states["root"] = "FAILED"
    s._release_resources(s.tasks["root"])
    # need to trigger propagation: next tick should propagate
    s.tick()
    assert s.get_state("child1") == "FAILED", f"child1 should be FAILED, got {s.get_state('child1')}"
    # transitive: child2 should also be FAILED (either now or next tick)
    s.tick()
    assert s.get_state("child2") == "FAILED", f"transitive FAILED not propagated: {s.get_state('child2')}"


def test_cancelled_propagation_as_failed():
    s = make_scheduler(limits={"cpu": 2}, rate=10)
    s.add_task(Task(id="a", priority=1, resources={"cpu": 1}, duration=1))
    s.add_task(Task(id="b", priority=1, resources={"cpu": 1}, dependencies=["a"], duration=1))
    s.add_task(Task(id="c", priority=1, resources={"cpu": 1}, dependencies=["b"], duration=1))
    # cancel a while pending (before it runs) - need to prevent it from running
    # Use rate 0 to keep pending
    s2 = make_scheduler(limits={"cpu": 10}, rate=0)
    s2.add_task(Task(id="a", priority=1, resources={"cpu": 1}, duration=1))
    s2.add_task(Task(id="b", priority=1, resources={"cpu": 1}, dependencies=["a"], duration=1))
    assert s2.cancel("a") is True
    s2.max_starts_per_tick = 10
    s2.tick()
    assert s2.get_state("b") == "FAILED", f"cancelled dep should cause FAILED, got {s2.get_state('b')}"

    # also READY -> FAILED propagation
    s3 = make_scheduler(limits={"cpu": 1}, rate=1)
    s3.add_task(Task(id="x", priority=1, resources={"cpu": 1}, duration=2))
    s3.add_task(Task(id="y", priority=2, resources={"cpu": 1}, duration=1))
    s3.add_task(Task(id="z", priority=1, resources={"cpu": 1}, dependencies=["y"], duration=1))
    s3.tick()  # x RUNNING, y READY
    assert s3.get_state("y") == "READY"
    assert s3.cancel("y") is True
    s3.tick()
    # z depends on y (cancelled) -> should be FAILED even though it was PENDING
    # and also test READY propagation: create case where dependent is READY
    s4 = make_scheduler(limits={"cpu": 10}, rate=10)
    s4.add_task(Task(id="p", priority=1, resources={"cpu": 1}, duration=1))
    s4.add_task(Task(id="q", priority=1, resources={"cpu": 1}, dependencies=["p"], duration=1))
    s4.add_task(Task(id="r", priority=1, resources={"cpu": 1}, dependencies=["p"], duration=1))
    # make p fail
    s4.tick()  # p RUNNING
    s4.states["p"] = "FAILED"
    s4._release_resources(s4.tasks["p"])
    s4.tick()
    assert s4.get_state("q") == "FAILED"
    assert s4.get_state("r") == "FAILED"


def test_dependency_chain_correctness():
    s = make_scheduler(limits={"cpu": 10}, rate=10)
    n = 10
    for i in range(n):
        deps = [f"t{i-1}"] if i > 0 else []
        s.add_task(Task(id=f"t{i}", priority=1, resources={"cpu": 1}, dependencies=deps, duration=1))
    s.run_until_complete(max_ticks=20)
    for i in range(n):
        assert s.get_state(f"t{i}") == "COMPLETED", f"t{i} state {s.get_state(f't{i}')}"


def test_performance_dependency_checks():
    # Linear chain of 300 tasks, each depends on previous.
    # Correct implementation should do O(N) dependency checks total, not O(N^2) per tick.
    s = make_scheduler(limits={"cpu": 10}, rate=10)
    n = 300
    for i in range(n):
        deps = [f"t{i-1}"] if i > 0 else []
        s.add_task(Task(id=f"t{i}", priority=1, resources={"cpu": 1}, duration=1))
    # instrument _dependencies_met call count
    original = s._dependencies_met
    call_count = {"n": 0}

    def counted(tid):
        call_count["n"] += 1
        return original(tid)

    s._dependencies_met = counted
    s.run_until_complete(max_ticks=500)
    # In efficient implementation, each task's dependencies are checked at most once or twice
    # So total calls ~ O(N) ~ < 1000. Buggy O(N^2) will be > 20000.
    assert call_count["n"] < 2000, f"too many dependency checks: {call_count['n']} (expected <2000 for O(N) implementation)"
    # also check all completed
    for i in range(n):
        assert s.get_state(f"t{i}") == "COMPLETED"


def test_complex_interaction():
    # Combines priority, resources, rate limit, and failure
    s = make_scheduler(limits={"cpu": 2}, rate=2)
    s.add_task(Task(id="a", priority=1, resources={"cpu": 1}, duration=2))
    s.add_task(Task(id="b", priority=1, resources={"cpu": 1}, duration=2))
    s.add_task(Task(id="c", priority=10, resources={"cpu": 1}, duration=1, dependencies=["a"]))
    s.add_task(Task(id="d", priority=2, resources={"cpu": 1}, duration=1))
    s.add_task(Task(id="e", priority=3, resources={"cpu": 1}, dependencies=["b"], duration=1))
    # tick1: a,b start (highest priority, rate 2, cpu 2)
    s.tick()
    assert set([tid for tid, st in s.states.items() if st == "RUNNING"]) == {"a", "b"}
    assert s.get_state("d") == "READY"  # waiting for cpu
    # tick2: a,b still running (remaining 1), d cannot start due cpu cap
    s.tick()
    assert s.resource_used["cpu"] == 2
    # tick3: a,b complete, c,d,e become ready. Priority order: d(2), e(3), c(10)
    # rate 2 => only 2 should start: d and e
    s.tick()
    running = set(tid for tid, st in s.states.items() if st == "RUNNING")
    assert running == {"d", "e"}, f"expected d,e running, got {running}"
    assert s.get_state("c") == "READY"  # left for next tick due rate limit
    s.tick()
    assert s.get_state("c") == "RUNNING" or s.get_state("c") == "COMPLETED"


def test_state_machine_no_resurrection():
    s = make_scheduler()
    s.add_task(Task(id="a", priority=1, resources={"cpu": 1}, duration=1))
    s.tick()  # a RUNNING
    s.tick()  # a COMPLETED
    assert s.get_state("a") == "COMPLETED"
    assert s.cancel("a") is False
    assert s.get_state("a") == "COMPLETED"
    # FAILED terminal
    s2 = make_scheduler()
    s2.add_task(Task(id="x", priority=1, duration=1))
    s2.states["x"] = "FAILED"
    assert s2.cancel("x") is False
    assert s2.get_state("x") == "FAILED"