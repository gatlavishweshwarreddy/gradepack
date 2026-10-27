import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
from orchestrator import WorkflowOrchestrator, TaskState
import pytest

def test_submit_and_dependency_promotion():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    assert o.get_state("A") == TaskState.READY
    o.submit("B", ["A"], 2)
    assert o.get_state("B") == TaskState.PENDING
    o.start("A")
    o.complete("A")
    assert o.get_state("B") == TaskState.READY

def test_failed_does_not_unblock_dependents():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    o.submit("B", ["A"], 2)
    o.start("A")
    o.fail("A")
    assert o.get_state("A") == TaskState.FAILED
    assert o.get_state("B") == TaskState.PENDING
    assert "B" not in o.get_runnable_tasks()

def test_cancelled_does_not_unblock_dependents():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    o.submit("B", ["A"], 2)
    o.cancel("A")
    assert o.get_state("A") == TaskState.CANCELLED
    assert o.get_state("B") == TaskState.PENDING
    assert "B" not in o.get_runnable_tasks()

def test_running_non_cancellable():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    o.start("A")
    assert o.get_state("A") == TaskState.RUNNING
    with pytest.raises(RuntimeError):
        o.cancel("A")
    assert o.get_state("A") == TaskState.RUNNING
    assert o.get_running_tokens() == 2

def test_cancel_pending_and_ready_allowed():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    o.submit("B", ["A"], 2)
    o.cancel("B")
    assert o.get_state("B") == TaskState.CANCELLED
    o.cancel("A")
    assert o.get_state("A") == TaskState.CANCELLED

def test_cancel_completed_or_failed_raises():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    o.start("A")
    o.complete("A")
    with pytest.raises(RuntimeError):
        o.cancel("A")
    o.submit("B", [], 2)
    o.start("B")
    o.fail("B")
    with pytest.raises(RuntimeError):
        o.cancel("B")

def test_token_cap_enforced():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 6)
    o.submit("B", [], 6)
    o.start("A")
    assert o.get_running_tokens() == 6
    with pytest.raises(RuntimeError):
        o.start("B")
    assert o.get_state("B") == TaskState.READY
    o.complete("A")
    o.start("B")
    assert o.get_state("B") == TaskState.RUNNING

def test_token_release_on_complete():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 5)
    o.submit("B", [], 5)
    o.submit("C", [], 5)
    o.start("A")
    o.start("B")
    assert o.get_running_tokens() == 10
    with pytest.raises(RuntimeError):
        o.start("C")
    o.complete("A")
    assert o.get_running_tokens() == 5
    o.start("C")
    assert o.get_running_tokens() == 10

def test_token_release_on_fail():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 7)
    o.submit("B", [], 7)
    o.start("A")
    assert o.get_running_tokens() == 7
    o.fail("A")
    assert o.get_running_tokens() == 0
    assert o.get_state("A") == TaskState.FAILED
    o.start("B")
    assert o.get_state("B") == TaskState.RUNNING
    assert o.get_running_tokens() == 7

def test_token_invariant_never_exceeded():
    o = WorkflowOrchestrator(max_tokens=10)
    for i in range(5):
        o.submit(f"T{i}", [], 3)
    o.start("T0")
    o.start("T1")
    o.start("T2")
    assert o.get_running_tokens() == 9
    with pytest.raises(RuntimeError):
        o.start("T3")
    o.complete("T0")
    o.start("T3")
    assert o.get_running_tokens() == 9

def test_get_runnable_respects_token_cap_greedy():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 6)
    o.submit("B", [], 6)
    o.submit("C", [], 4)
    runnable = o.get_runnable_tasks()
    assert runnable == ["A", "C"]
    o.start("A")
    runnable2 = o.get_runnable_tasks()
    assert runnable2 == ["C"]
    assert "B" not in runnable2

def test_get_runnable_ordering_submission_order():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("C", [], 1)
    o.submit("A", [], 1)
    o.submit("B", [], 1)
    runnable = o.get_runnable_tasks()
    assert runnable == ["C", "A", "B"]

def test_get_runnable_after_promotion_order():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 1)
    o.submit("B", [], 1)
    o.submit("C", ["A"], 1)
    o.submit("D", ["B"], 1)
    o.start("A")
    o.complete("A")
    runnable = o.get_runnable_tasks()
    assert runnable == ["B", "C"]

def test_dependency_validation_rejects_missing():
    o = WorkflowOrchestrator(max_tokens=10)
    with pytest.raises(ValueError):
        o.submit("B", ["NONEXISTENT"], 1)
    with pytest.raises(ValueError):
        o.submit("A", [], 11)

def test_complete_only_running():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    with pytest.raises(RuntimeError):
        o.complete("A")
    o.start("A")
    o.complete("A")
    with pytest.raises(RuntimeError):
        o.complete("A")
    with pytest.raises(RuntimeError):
        o.fail("A")

def test_fail_only_running():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    with pytest.raises(RuntimeError):
        o.fail("A")
    o.start("A")
    o.fail("A")
    assert o.get_state("A") == TaskState.FAILED
    with pytest.raises(RuntimeError):
        o.fail("A")

def test_performance_operation_count():
    o = WorkflowOrchestrator(max_tokens=1000)
    n = 80
    for i in range(n):
        deps = [f"T{i-1}"] if i > 0 else []
        o.submit(f"T{i}", deps, 1)
    o._dependency_check_count = 0
    for _ in range(50):
        o.get_runnable_tasks()
    assert o._dependency_check_count < 100, f"get_runnable_tasks did {o._dependency_check_count} dependency checks, expected efficient implementation"

def test_chain_with_failure_blocks_downstream():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 2)
    o.submit("B", ["A"], 2)
    o.submit("C", ["B"], 2)
    o.start("A")
    o.fail("A")
    assert o.get_state("B") == TaskState.PENDING
    assert o.get_state("C") == TaskState.PENDING
    assert o.get_runnable_tasks() == []

def test_submit_duplicate_raises():
    o = WorkflowOrchestrator(max_tokens=10)
    o.submit("A", [], 1)
    with pytest.raises(ValueError):
        o.submit("A", [], 1)