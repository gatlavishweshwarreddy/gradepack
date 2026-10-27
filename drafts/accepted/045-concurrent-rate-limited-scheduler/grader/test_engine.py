import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))

import engine
from engine import TokenBucket, Scheduler, TaskState


def test_token_bucket_cap():
    b = TokenBucket(capacity=5, refill_rate=3)
    b.tokens = 5
    b.refill()
    assert b.tokens == 5, "tokens must cap at capacity"
    b.tokens = 4
    b.refill()
    assert b.tokens == 5, "refill should cap, not exceed"
    b.tokens = 0
    b.refill()
    assert b.tokens == 3
    b.refill()
    assert b.tokens == 5


def test_token_bucket_consume_and_refill_interaction():
    b = TokenBucket(capacity=2, refill_rate=1)
    sched = Scheduler(max_concurrent=10, bucket=b)
    # consume all tokens via tasks
    b.tokens = 2
    sched.add_task("a", priority=0)
    sched.add_task("b", priority=0)
    sched.add_task("c", priority=0)
    sched.tick()  # refill caps at 2, then starts 2 tasks
    running = [tid for tid, t in sched.tasks.items() if t.state == TaskState.RUNNING]
    assert len(running) == 2, f"should start 2 with 2 tokens, got {running}"
    # next tick: 0 tokens left, refill 1, start 1 more
    for tid in running:
        sched.complete(tid)
    sched.tick()
    running2 = [tid for tid, t in sched.tasks.items() if t.state == TaskState.RUNNING]
    assert len(running2) == 1 and "c" in running2


def test_running_not_cancellable():
    b = TokenBucket(capacity=10, refill_rate=10)
    sched = Scheduler(max_concurrent=10, bucket=b)
    sched.add_task("a")
    sched.tick()
    assert sched.get_state("a") == TaskState.RUNNING
    result = sched.cancel("a")
    assert result is False, "cancel on RUNNING must return False"
    assert sched.get_state("a") == TaskState.RUNNING, "RUNNING must not be cancellable"
    # pending is cancellable
    sched.add_task("b")
    assert sched.cancel("b") is True
    assert sched.get_state("b") == TaskState.CANCELLED
    # ready is cancellable (need to block running slot)
    b2 = TokenBucket(capacity=10, refill_rate=10)
    sched2 = Scheduler(max_concurrent=1, bucket=b2)
    sched2.add_task("x")
    sched2.add_task("y")
    sched2.tick()
    assert sched2.get_state("x") == TaskState.RUNNING
    assert sched2.get_state("y") == TaskState.READY
    assert sched2.cancel("y") is True
    assert sched2.get_state("y") == TaskState.CANCELLED
    # completed not cancellable
    sched.complete("a")
    assert sched.cancel("a") is False


def test_failed_blocks_dependents():
    b = TokenBucket(capacity=10, refill_rate=10)
    sched = Scheduler(max_concurrent=10, bucket=b)
    sched.add_task("root")
    sched.add_task("child", dependencies=["root"])
    sched.add_task("grandchild", dependencies=["child"])
    sched.tick()
    assert sched.get_state("root") == TaskState.RUNNING
    sched.fail("root")
    assert sched.get_state("root") == TaskState.FAILED
    sched.tick()
    # child must never become READY/RUNNING because dependency failed
    assert sched.get_state("child") == TaskState.PENDING, "FAILED dependency must permanently block dependent"
    assert sched.get_state("grandchild") == TaskState.PENDING
    # even after many ticks
    sched.tick()
    sched.tick()
    assert sched.get_state("child") == TaskState.PENDING


def test_cancelled_blocks_dependents():
    b = TokenBucket(capacity=10, refill_rate=10)
    sched = Scheduler(max_concurrent=10, bucket=b)
    sched.add_task("root")
    sched.add_task("child", dependencies=["root"])
    sched.add_task("other", dependencies=[])
    # cancel root while pending (before tick)
    assert sched.cancel("root") is True
    sched.tick()
    assert sched.get_state("child") == TaskState.PENDING
    # other should run
    assert sched.get_state("other") == TaskState.RUNNING


def test_priority_ordering():
    b = TokenBucket(capacity=10, refill_rate=10)
    sched = Scheduler(max_concurrent=10, bucket=b)
    sched.add_task("low", priority=1)
    sched.add_task("high", priority=10)
    sched.add_task("mid", priority=5)
    sched.tick()
    order = sched.get_run_order()
    assert order == ["high", "mid", "low"], f"priority ordering wrong: {order}"

    # tie-break by lexicographic id
    b2 = TokenBucket(capacity=10, refill_rate=10)
    sched2 = Scheduler(max_concurrent=10, bucket=b2)
    sched2.add_task("b", priority=5)
    sched2.add_task("a", priority=5)
    sched2.add_task("c", priority=5)
    sched2.tick()
    order2 = sched2.get_run_order()
    assert order2 == ["a", "b", "c"], f"tie-break wrong: {order2}"

    # priority with rate limit: only 1 token per tick, highest should go first
    b3 = TokenBucket(capacity=1, refill_rate=1)
    b3.tokens = 0
    sched3 = Scheduler(max_concurrent=10, bucket=b3)
    sched3.add_task("low", priority=1)
    sched3.add_task("high", priority=10)
    sched3.tick()  # refill 1, start high
    assert sched3.get_run_order() == ["high"]
    assert sched3.get_state("low") == TaskState.READY
    sched3.complete("high")
    sched3.tick()  # refill 1, start low
    assert sched3.get_run_order() == ["high", "low"]


def test_concurrency_limit():
    b = TokenBucket(capacity=10, refill_rate=10)
    sched = Scheduler(max_concurrent=2, bucket=b)
    for i in range(5):
        sched.add_task(f"t{i}")
    sched.tick()
    running = [t for t in sched.tasks.values() if t.state == TaskState.RUNNING]
    assert len(running) == 2, f"concurrency limit violated: {len(running)} running, expected 2"
    # complete one, next tick should start one more, still cap 2
    sched.complete("t0")
    sched.tick()
    running2 = [t for t in sched.tasks.values() if t.state == TaskState.RUNNING]
    assert len(running2) == 2, f"expected 2 running after completing 1 and tick, got {len(running2)}"
    # with max_concurrent=1
    b2 = TokenBucket(capacity=10, refill_rate=10)
    sched2 = Scheduler(max_concurrent=1, bucket=b2)
    sched2.add_task("a")
    sched2.add_task("b")
    sched2.tick()
    running3 = [t for t in sched2.tasks.values() if t.state == TaskState.RUNNING]
    assert len(running3) == 1


def test_dependency_chain_completion():
    b = TokenBucket(capacity=10, refill_rate=10)
    sched = Scheduler(max_concurrent=10, bucket=b)
    sched.add_task("a")
    sched.add_task("b", dependencies=["a"])
    sched.add_task("c", dependencies=["b"])
    sched.tick()
    assert sched.get_state("a") == TaskState.RUNNING
    assert sched.get_state("b") == TaskState.PENDING
    sched.complete("a")
    sched.tick()
    assert sched.get_state("b") == TaskState.RUNNING
    sched.complete("b")
    sched.tick()
    assert sched.get_state("c") == TaskState.RUNNING


def test_performance_dependency_checks():
    b = TokenBucket(capacity=10000, refill_rate=10000)
    sched = Scheduler(max_concurrent=10000, bucket=b)
    N = 500
    # build chain: t0 -> t1 -> t2 -> ... -> tN-1
    sched.add_task("t0")
    for i in range(1, N):
        sched.add_task(f"t{i}", dependencies=[f"t{i-1}"])

    # instrument _is_dependency_met
    orig = sched._is_dependency_met
    count = [0]
    def counting(*args, **kwargs):
        count[0] += 1
        return orig(*args, **kwargs)
    sched._is_dependency_met = counting

    # initial tick starts t0
    sched.tick()
    assert sched.get_state("t0") == TaskState.RUNNING
    # complete chain one by one, tick each time
    for i in range(N-1):
        sched.complete(f"t{i}")
        sched.tick()
        # next should be running
        assert sched.get_state(f"t{i+1}") == TaskState.RUNNING, f"t{i+1} should be RUNNING after completing t{i}"

    # For chain, efficient implementation should call _is_dependency_met O(N) times
    # Naive scan-every-tick would be O(N^2) ~ 125k for N=500
    # Set limit to 3*N to allow some overhead but catch O(N^2)
    assert count[0] <= 3 * N, f"too many dependency checks: {count[0]} for N={N}, expected O(N) <= {3*N} (naive O(N^2) detected)"

    # also test diamond graph doesn't explode
    b2 = TokenBucket(capacity=10000, refill_rate=10000)
    sched2 = Scheduler(max_concurrent=10000, bucket=b2)
    sched2.add_task("root")
    for i in range(200):
        sched2.add_task(f"mid{i}", dependencies=["root"])
    sched2.add_task("leaf", dependencies=[f"mid{i}" for i in range(200)])
    orig2 = sched2._is_dependency_met
    count2 = [0]
    def counting2(*args, **kwargs):
        count2[0] += 1
        return orig2(*args, **kwargs)
    sched2._is_dependency_met = counting2
    sched2.tick()
    assert sched2.get_state("root") == TaskState.RUNNING
    sched2.complete("root")
    sched2.tick()
    # all mids should be running
    for i in range(200):
        assert sched2.get_state(f"mid{i}") == TaskState.RUNNING
    for i in range(200):
        sched2.complete(f"mid{i}")
    sched2.tick()
    assert sched2.get_state("leaf") == TaskState.RUNNING
    # leaf has 200 deps, should check 200 times, not 200*200
    assert count2[0] <= 600, f"diamond graph too many checks: {count2[0]}"


def test_failed_state_terminal_and_order_determinism():
    b = TokenBucket(capacity=10, refill_rate=10)
    sched = Scheduler(max_concurrent=10, bucket=b)
    sched.add_task("a", priority=5)
    sched.add_task("b", priority=5)
    sched.add_task("c", priority=5)
    sched.tick()
    # deterministic order by id
    assert sched.get_run_order() == ["a", "b", "c"]
    sched.fail("b")
    assert sched.get_state("b") == TaskState.FAILED
    # cannot complete failed
    try:
        sched.complete("b")
        assert False, "should not be able to complete FAILED task"
    except ValueError:
        pass
    # failed not cancellable
    assert sched.cancel("b") is False