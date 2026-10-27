import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
from engine import WorkflowEngine

def test_token_bucket_cap():
    eng = WorkflowEngine(max_concurrent=5, rate_limits={"api": (2, 1)})
    for _ in range(5):
        eng.tick()
    assert eng.get_tokens("api") == 2, f"tokens exceeded cap: {eng.get_tokens('api')} != 2"
    # consume one and refill should stay capped
    eng.add_workflow("wf1", [{"id": "a", "deps": [], "group": "api", "fn": lambda: None, "duration": 1}])
    eng.start("wf1")
    eng.tick()  # schedules a, consumes 1
    assert eng.get_tokens("api") == 1
    for _ in range(10):
        eng.tick()
    assert eng.get_tokens("api") == 2

def test_running_non_cancellable():
    eng = WorkflowEngine(max_concurrent=2)
    executed = []
    def fn():
        executed.append(1)
    eng.add_workflow("wf1", [{"id": "a", "deps": [], "fn": fn, "duration": 3, "timeout": 10}])
    eng.start("wf1")
    eng.tick()
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "RUNNING", f"should be RUNNING after tick, got {st['steps']['a']}"
    eng.cancel("wf1")
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "RUNNING", f"RUNNING must not be cancelled, got {st['steps']['a']}"
    assert st["workflow"] == "RUNNING", f"workflow should stay RUNNING while step runs, got {st['workflow']}"
    eng.tick()
    eng.tick()
    eng.tick()
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "COMPLETED"
    assert st["workflow"] == "CANCELLED", f"workflow should be CANCELLED after RUNNING completes, got {st['workflow']}"
    assert executed == [1]

def test_failed_propagation():
    eng = WorkflowEngine(max_concurrent=2)
    def fail_fn():
        raise ValueError("fail")
    eng.add_workflow("wf1", [
        {"id": "a", "deps": [], "fn": fail_fn, "duration": 1, "retries": 0},
        {"id": "b", "deps": ["a"], "fn": lambda: None, "duration": 1},
        {"id": "c", "deps": [], "fn": lambda: None, "duration": 1},
    ])
    eng.start("wf1")
    eng.tick()
    eng.tick()
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "FAILED"
    assert st["steps"]["b"] == "CANCELLED", f"b should be CANCELLED when dep failed, got {st['steps']['b']}"
    assert st["workflow"] == "FAILED"

def test_dependency_all():
    eng = WorkflowEngine(max_concurrent=2)
    eng.add_workflow("wf1", [
        {"id": "a", "deps": [], "fn": lambda: None, "duration": 1},
        {"id": "b", "deps": [], "fn": lambda: None, "duration": 2},
        {"id": "c", "deps": ["a", "b"], "fn": lambda: None, "duration": 1},
    ])
    eng.start("wf1")
    eng.tick()  # a and b start
    eng.tick()  # a completes (duration 1), b still running
    st = eng.get_status("wf1")
    assert st["steps"]["c"] == "PENDING", f"c should wait for both a and b, got {st['steps']['c']}"
    eng.tick()  # b completes
    eng.tick()  # c should be scheduled
    st = eng.get_status("wf1")
    assert st["steps"]["c"] in ("READY", "RUNNING", "COMPLETED"), f"c should be ready after both deps, got {st['steps']['c']}"

def test_ordering_fifo():
    eng = WorkflowEngine(max_concurrent=1)
    order = []
    eng.add_workflow("wf1", [{"id": "a1", "deps": [], "fn": lambda: order.append("a1"), "duration": 1}])
    eng.add_workflow("wf2", [{"id": "b1", "deps": [], "fn": lambda: order.append("b1"), "duration": 1}])
    eng.start("wf1")
    eng.start("wf2")
    eng.tick()
    eng.tick()
    eng.tick()
    assert order == ["a1", "b1"], f"FIFO ordering violated, got {order}"

def test_concurrency_limit():
    eng = WorkflowEngine(max_concurrent=2)
    for i in range(5):
        eng.add_workflow(f"wf{i}", [{"id": "a", "deps": [], "fn": lambda: None, "duration": 3}])
        eng.start(f"wf{i}")
    eng.tick()
    running = sum(1 for wf in eng.workflows.values() for s in wf["steps"].values() if s["state"] == "RUNNING")
    assert running == 2, f"concurrency limit violated, running={running} !=2"
    eng.tick()
    running = sum(1 for wf in eng.workflows.values() for s in wf["steps"].values() if s["state"] == "RUNNING")
    assert running == 2

def test_rate_limiting():
    eng = WorkflowEngine(max_concurrent=5, rate_limits={"api": (1, 1)})
    for i in range(3):
        eng.add_workflow(f"wf{i}", [{"id": "a", "deps": [], "group": "api", "fn": lambda: None, "duration": 1}])
        eng.start(f"wf{i}")
    eng.tick()
    running = sum(1 for wf in eng.workflows.values() for s in wf["steps"].values() if s["state"] == "RUNNING")
    assert running == 1, f"rate limit should allow 1 per tick, got {running}"
    eng.tick()
    # after first completes, second should be running
    running = sum(1 for wf in eng.workflows.values() for s in wf["steps"].values() if s["state"] == "RUNNING")
    assert running == 1
    eng.tick()
    running = sum(1 for wf in eng.workflows.values() for s in wf["steps"].values() if s["state"] == "RUNNING")
    assert running == 1

def test_retry_backoff():
    eng = WorkflowEngine(max_concurrent=2)
    attempts = []
    def fn():
        attempts.append(eng.time)
        if len(attempts) == 1:
            raise ValueError("first fail")
    eng.add_workflow("wf1", [{"id": "a", "deps": [], "fn": fn, "duration": 1, "retries": 1, "timeout": 5}])
    eng.start("wf1")
    eng.tick()  # first attempt fails, backoff 2
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "PENDING", f"should be PENDING during backoff, got {st['steps']['a']}"
    eng.tick()
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "PENDING", f"should still be backoff, got {st['steps']['a']}"
    eng.tick()
    eng.tick()  # should retry and succeed
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "COMPLETED", f"should be COMPLETED after retry, got {st['steps']['a']}"
    assert len(attempts) == 2

def test_timeout():
    eng = WorkflowEngine(max_concurrent=2)
    eng.add_workflow("wf1", [{"id": "a", "deps": [], "fn": lambda: None, "duration": 5, "timeout": 2, "retries": 0}])
    eng.start("wf1")
    eng.tick()
    eng.tick()
    eng.tick()
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "RUNNING", f"should still be RUNNING at elapsed==timeout, got {st['steps']['a']}"
    eng.tick()  # elapsed 3 > 2 => timeout
    st = eng.get_status("wf1")
    assert st["steps"]["a"] == "FAILED", f"should be FAILED after timeout, got {st['steps']['a']}"
    assert st["workflow"] == "FAILED"

def test_performance_linear():
    eng = WorkflowEngine(max_concurrent=10)
    n = 500
    steps = []
    for i in range(n):
        deps = [f"s{i-1}"] if i > 0 else []
        steps.append({"id": f"s{i}", "deps": deps, "fn": lambda: None, "duration": 1})
    eng.add_workflow("wf", steps)
    eng.start("wf")
    for _ in range(n + 5):
        eng.tick()
    st = eng.get_status("wf")
    assert st["workflow"] == "COMPLETED", f"chain should complete, got {st['workflow']}"
    assert eng._check_count < 5000, f"dependency checks not linear: {eng._check_count} >= 5000 (O(N^2) detected)"