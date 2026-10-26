import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from min_stack import MinStack


def test_basic_min():
    s = MinStack()
    s.push(3)
    assert s.get_min() == 3


def test_min_updates_on_push():
    s = MinStack()
    s.push(5)
    s.push(2)
    assert s.get_min() == 2


def test_min_restored_after_pop():
    s = MinStack()
    s.push(5)
    s.push(2)
    s.pop()
    assert s.get_min() == 5


def test_pop_non_min_keeps_min():
    # push 3, 5 — min is 3; pop 5 — min must still be 3
    s = MinStack()
    s.push(3)
    s.push(5)
    s.pop()
    assert s.get_min() == 3


def test_duplicate_min():
    s = MinStack()
    s.push(2)
    s.push(2)
    s.pop()
    assert s.get_min() == 2
