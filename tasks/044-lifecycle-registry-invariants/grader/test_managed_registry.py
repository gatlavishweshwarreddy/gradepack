import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
import pytest
from managed_registry import LifecycleRegistry, InvalidTransition, ResourceInUse, RegistryClosed

def test_registry_lifecycle_no_reopen():
    r = LifecycleRegistry()
    assert r.state == "CREATED"
    r.open()
    assert r.state == "OPEN"
    r.close()
    assert r.is_closed
    assert r.state == "CLOSED"
    try:
        r.open()
        assert False, "reopen after close must raise RegistryClosed"
    except RegistryClosed:
        pass
    try:
        r.register("new")
        assert False, "operation after close must raise RegistryClosed"
    except RegistryClosed:
        pass
    # context manager cannot reopen closed
    try:
        with r:
            assert False
    except RegistryClosed:
        pass

def test_suspend_resume_strict():
    r = LifecycleRegistry()
    r.open()
    r.register("x", "d1")
    r.initialize("x")
    assert r.get_resource_state("x") == "ACTIVE"
    r.suspend("x")
    assert r.get_resource_state("x") == "SUSPENDED"
    try:
        r.suspend("x")
        assert False, "double suspend must raise InvalidTransition"
    except InvalidTransition:
        pass
    assert r.get_resource_state("x") == "SUSPENDED"
    r.resume("x")
    assert r.get_resource_state("x") == "ACTIVE"
    try:
        r.resume("x")
        assert False, "resume when ACTIVE must raise InvalidTransition"
    except InvalidTransition:
        pass
    # suspend from PENDING must fail
    r.register("y")
    try:
        r.suspend("y")
        assert False
    except InvalidTransition:
        pass
    # resume from ACTIVE must fail (already tested) and from PENDING must fail
    try:
        r.resume("y")
        assert False
    except InvalidTransition:
        pass

def test_dispose_refcount_zero_required():
    r = LifecycleRegistry()
    r.open()
    r.register("a", "val")
    r.initialize("a")
    r.acquire("a")
    assert r.get_refcount("a") == 1
    try:
        r.dispose("a")
        assert False, "dispose with refcount 1 must raise ResourceInUse"
    except ResourceInUse:
        pass
    assert r.get_resource_state("a") != "DISPOSED"
    r.release("a")
    assert r.get_refcount("a") == 0
    r.dispose("a")
    assert r.get_resource_state("a") == "DISPOSED"
    # dispose already disposed must raise
    try:
        r.dispose("a")
        assert False
    except InvalidTransition:
        pass
    # acquire with two holders
    r.register("b")
    r.initialize("b")
    r.acquire("b")
    r.acquire("b")
    assert r.get_refcount("b") == 2
    try:
        r.dispose("b")
        assert False
    except ResourceInUse:
        pass
    r.release("b")
    try:
        r.dispose("b")
        assert False, "still 1 holder must raise"
    except ResourceInUse:
        pass
    r.release("b")
    r.dispose("b")
    assert r.get_resource_state("b") == "DISPOSED"

def test_close_disposes_all_states():
    r = LifecycleRegistry()
    r.open()
    r.register("p1", "pending_data")
    r.register("a1", "active_data")
    r.initialize("a1")
    r.register("s1", "susp_data")
    r.initialize("s1")
    r.suspend("s1")
    r.register("f1", "fail_data")
    r.initialize("f1")
    r.fail("f1")
    assert r.get_resource_state("p1") == "PENDING"
    assert r.get_resource_state("s1") == "SUSPENDED"
    assert r.get_resource_state("f1") == "FAILED"
    r.close()
    assert r.is_closed
    for rid in ["p1", "a1", "s1", "f1"]:
        assert r.get_resource_state(rid) == "DISPOSED", f"{rid} not disposed after close"
    # after close, operations must raise RegistryClosed
    try:
        r.get("a1")
        assert False
    except RegistryClosed:
        pass

def test_close_with_active_refcount_fails():
    r = LifecycleRegistry()
    r.open()
    r.register("a", "data")
    r.initialize("a")
    r.acquire("a")
    try:
        r.close()
        assert False, "close with refcount>0 must raise ResourceInUse"
    except ResourceInUse:
        pass
    assert not r.is_closed, "registry must remain OPEN after failed close"
    assert r.get_resource_state("a") == "ACTIVE"
    r.release("a")
    r.close()
    assert r.is_closed
    assert r.get_resource_state("a") == "DISPOSED"

def test_acquire_disposed_and_failed_rejected():
    r = LifecycleRegistry()
    r.open()
    r.register("a", "v")
    r.initialize("a")
    r.dispose("a")
    assert r.get_resource_state("a") == "DISPOSED"
    try:
        r.acquire("a")
        assert False, "acquire on DISPOSED must raise InvalidTransition"
    except InvalidTransition:
        pass
    try:
        r.get("a")
        assert False, "get on DISPOSED must raise InvalidTransition"
    except InvalidTransition:
        pass
    r.register("b", "v2")
    r.initialize("b")
    r.fail("b")
    assert r.get_resource_state("b") == "FAILED"
    try:
        r.acquire("b")
        assert False, "acquire on FAILED must raise"
    except InvalidTransition:
        pass
    try:
        r.get("b")
        assert False, "get on FAILED must raise InvalidTransition"
    except InvalidTransition:
        pass
    # acquire on PENDING must also raise
    r.register("c")
    try:
        r.acquire("c")
        assert False
    except InvalidTransition:
        pass
    # release without acquire must raise
    try:
        r.release("c")
        assert False
    except InvalidTransition:
        pass

def test_get_put_performance_o1():
    r = LifecycleRegistry()
    r.open()
    n = 600
    for i in range(n):
        rid = f"id{i}"
        r.register(rid, f"val{i}")
        r.initialize(rid)
    r.lookup_steps = 0
    for i in range(n):
        v = r.get(f"id{i}")
        assert v == f"val{i}"
    # O(1) per op => steps ~ n, not O(n^2) ~ 180k
    assert r.lookup_steps < n * 3, f"get not O(1): steps={r.lookup_steps} for n={n}"
    r.lookup_steps = 0
    for i in range(n):
        r.put(f"id{i}", f"new{i}")
    assert r.lookup_steps < n * 3, f"put not O(1): steps={r.lookup_steps} for n={n}"
    # verify puts took effect with O(1) still
    r.lookup_steps = 0
    for i in range(n):
        assert r.get(f"id{i}") == f"new{i}"
    assert r.lookup_steps < n * 3
    # put on non-ACTIVE must raise
    r.suspend("id0")
    try:
        r.put("id0", "bad")
        assert False
    except InvalidTransition:
        pass
    # get on SUSPENDED is allowed
    assert r.get("id0") == "new0"

def test_session_context_manager():
    r = LifecycleRegistry()
    r.open()
    r.register("s", "sdata")
    r.initialize("s")
    assert r.get_refcount("s") == 0
    with r.session("s"):
        assert r.get_refcount("s") == 1
        assert r.get("s") == "sdata"
        r.put("s", "updated")
    assert r.get_refcount("s") == 0
    assert r.get("s") == "updated"
    # exception safety: release even if inner raises
    try:
        with r.session("s"):
            assert r.get_refcount("s") == 1
            raise ValueError("inner")
    except ValueError:
        pass
    assert r.get_refcount("s") == 0
    # cannot dispose while acquired via session
    with r.session("s"):
        try:
            r.dispose("s")
            assert False, "dispose while acquired must raise ResourceInUse"
        except ResourceInUse:
            pass
        assert r.get_resource_state("s") == "ACTIVE"
    # nested sessions
    with r.session("s"):
        with r.session("s"):
            assert r.get_refcount("s") == 2
        assert r.get_refcount("s") == 1
    assert r.get_refcount("s") == 0
    # registry context manager
    with LifecycleRegistry() as r2:
        assert r2.state == "OPEN"
        r2.register("k", "v")
        r2.initialize("k")
    assert r2.is_closed
    assert r2.get_resource_state("k") == "DISPOSED"

def test_failed_terminal_invariants():
    r = LifecycleRegistry()
    r.open()
    r.register("f", "data")
    r.initialize("f")
    r.fail("f")
    assert r.get_resource_state("f") == "FAILED"
    for op in [lambda: r.suspend("f"), lambda: r.resume("f"), lambda: r.initialize("f")]:
        try:
            op()
            assert False, "operation on FAILED must raise InvalidTransition"
        except InvalidTransition:
            pass
    # FAILED cannot be put
    try:
        r.put("f", "x")
        assert False
    except InvalidTransition:
        pass
    # but can be disposed
    r.dispose("f")
    assert r.get_resource_state("f") == "DISPOSED"
    for op in [lambda: r.initialize("f"), lambda: r.suspend("f"), lambda: r.resume("f"), lambda: r.fail("f"), lambda: r.dispose("f")]:
        try:
            op()
            assert False, "operation on DISPOSED must raise InvalidTransition"
        except InvalidTransition:
            pass
    # FAILED from PENDING
    r.register("fp")
    r.fail("fp")
    assert r.get_resource_state("fp") == "FAILED"
    r.dispose("fp")
    assert r.get_resource_state("fp") == "DISPOSED"