import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))

import pytest
from buffered_iterator import BufferedIterator

class CountingIter:
    def __init__(self, data):
        self.data = list(data)
        self.idx = 0
        self.calls = 0
    def __iter__(self):
        return self
    def __next__(self):
        if self.idx >= len(self.data):
            raise StopIteration
        self.calls += 1
        v = self.data[self.idx]
        self.idx += 1
        return v

def test_iterator_protocol_identity_and_exhaustion():
    it = BufferedIterator(iter([1, 2, 3]))
    assert iter(it) is it
    assert next(it) == 1
    assert next(it) == 2
    # for-loop uses same iterator
    remaining = []
    for x in it:
        remaining.append(x)
    assert remaining == [3]
    # after exhaustion, next always raises
    with pytest.raises(StopIteration):
        next(it)
    with pytest.raises(StopIteration):
        next(it)
    assert it.has_next() is False

    # fresh iterator with list source
    it2 = BufferedIterator([10, 20])
    assert iter(it2) is it2
    assert list(it2) == [10, 20]
    assert list(it2) == []

def test_peek_basic_and_default_handling():
    it = BufferedIterator([10, 20, 30])
    assert it.peek() == 10
    assert it.peek() == 10
    assert next(it) == 10
    assert it.peek() == 20
    assert it.peek(1) == 30

    # peek beyond end with default
    it2 = BufferedIterator([1])
    assert it2.peek(0) == 1
    assert it2.peek(1, default="end") == "end"
    # without default should raise
    with pytest.raises(StopIteration):
        it2.peek(1)
    # negative index
    with pytest.raises(ValueError):
        it2.peek(-1)

    # peek does not consume
    it3 = BufferedIterator([5, 6, 7])
    assert it3.peek(0) == 5
    assert it3.peek(1) == 6
    assert it3.peek(2) == 7
    assert next(it3) == 5
    assert next(it3) == 6
    assert next(it3) == 7

    # single element peek must succeed
    it4 = BufferedIterator([99])
    assert it4.peek(0) == 99
    assert it4.peek(0, default=None) == 99

def test_peek_lookahead_efficiency():
    c = CountingIter(['a', 'b', 'c', 'd'])
    it = BufferedIterator(c)
    assert c.calls == 0
    assert it.peek(0) == 'a'
    assert c.calls == 1
    assert it.peek(0) == 'a'
    assert c.calls == 1
    assert it.peek(1) == 'b'
    assert c.calls == 2
    assert it.peek(2) == 'c'
    assert c.calls == 3
    # repeated peek should not add calls
    assert it.peek(1) == 'b'
    assert c.calls == 3
    assert next(it) == 'a'
    assert c.calls == 3
    assert next(it) == 'b'
    assert c.calls == 3
    assert it.peek(0) == 'c'
    assert c.calls == 3
    assert next(it) == 'c'
    assert c.calls == 3
    assert it.peek(0) == 'd'
    assert c.calls == 4
    assert next(it) == 'd'
    assert c.calls == 4
    assert it.has_next() is False
    assert c.calls == 4

def test_push_back_ordering_and_interaction():
    it = BufferedIterator([3, 4])
    it.push_back(1, 2)
    assert next(it) == 1
    assert next(it) == 2
    assert next(it) == 3
    assert next(it) == 4

    # multiple push_backs stack correctly
    it2 = BufferedIterator([5])
    it2.push_back(3)
    it2.push_back(1, 2)
    assert next(it2) == 1
    assert next(it2) == 2
    assert next(it2) == 3
    assert next(it2) == 5

    # push_back after peek
    it3 = BufferedIterator([2, 3])
    assert it3.peek() == 2
    it3.push_back(1)
    assert next(it3) == 1
    assert next(it3) == 2
    assert next(it3) == 3

    # push_back after exhaustion
    it4 = BufferedIterator([])
    it4.push_back(99)
    assert next(it4) == 99
    assert it4.has_next() is False

    # push_back with no args does nothing
    it5 = BufferedIterator([1])
    it5.push_back()
    assert next(it5) == 1

def test_take_uses_buffer():
    it = BufferedIterator([1, 2, 3, 4, 5])
    assert it.peek(1) == 2
    assert it.take(2) == [1, 2]
    assert next(it) == 3
    assert it.take(10) == [4, 5]
    assert it.take(1) == []
    assert it.has_next() is False

    # take zero
    it2 = BufferedIterator([1, 2])
    assert it2.take(0) == []
    assert it2.take(-5) == []
    assert next(it2) == 1

    # take after push_back
    it3 = BufferedIterator([3, 4])
    it3.push_back(1, 2)
    assert it3.take(3) == [1, 2, 3]
    assert next(it3) == 4

def test_window_sliding_and_buffer_integration():
    it = BufferedIterator([1, 2, 3, 4, 5])
    assert list(it.window(3)) == [(1, 2, 3), (2, 3, 4), (3, 4, 5)]

    it2 = BufferedIterator([1, 2, 3, 4, 5, 6])
    assert list(it2.window(2, step=2)) == [(1, 2), (3, 4), (5, 6)]

    it3 = BufferedIterator([1, 2, 3, 4, 5])
    assert list(it3.window(3, step=2)) == [(1, 2, 3), (3, 4, 5)]

    # incomplete trailing windows not yielded
    it4 = BufferedIterator([1, 2, 3, 4])
    assert list(it4.window(3)) == [(1, 2, 3), (2, 3, 4)]
    it5 = BufferedIterator([1, 2])
    assert list(it5.window(3)) == []

    # window respects buffered/peeked data
    it6 = BufferedIterator([1, 2, 3, 4])
    assert it6.peek() == 1
    assert list(it6.window(2)) == [(1, 2), (2, 3), (3, 4)]

    # window after push_back
    it7 = BufferedIterator([3, 4, 5])
    it7.push_back(1, 2)
    assert list(it7.window(3)) == [(1, 2, 3), (2, 3, 4), (3, 4, 5)]

    # invalid args
    with pytest.raises(ValueError):
        list(BufferedIterator([1, 2]).window(0))
    with pytest.raises(ValueError):
        list(BufferedIterator([1, 2]).window(2, step=0))

def test_close_delegation_and_state():
    closed = [False]
    def gen():
        try:
            yield 1
            yield 2
            yield 3
        finally:
            closed[0] = True

    g = gen()
    it = BufferedIterator(g)
    assert next(it) == 1
    assert it.has_next() is True
    it.close()
    assert closed[0] is True
    assert it.has_next() is False
    with pytest.raises(StopIteration):
        next(it)
    with pytest.raises(StopIteration):
        next(it)

    # close clears buffer
    it2 = BufferedIterator([1, 2, 3])
    assert it2.peek() == 1
    it2.close()
    assert it2.has_next() is False
    with pytest.raises(StopIteration):
        next(it2)
    # push_back after close revives
    it2.push_back(99)
    assert next(it2) == 99

    # close on non-generator should still mark exhausted
    it3 = BufferedIterator([1])
    it3.close()
    assert it3.has_next() is False

def test_throw_delegation():
    def gen():
        try:
            yield 1
            yield 2
        except ValueError:
            yield 99
            yield 100

    it = BufferedIterator(gen())
    assert next(it) == 1
    # throw should delegate and return next yielded value
    val = it.throw(ValueError, ValueError("oops"))
    assert val == 99
    assert next(it) == 100

    # throw on non-generator without throw should raise
    it2 = BufferedIterator([1, 2, 3])
    with pytest.raises(RuntimeError):
        it2.throw(RuntimeError, RuntimeError("fail"))

    # throw with exception instance
    it3 = BufferedIterator([1])
    with pytest.raises(ValueError):
        it3.throw(ValueError("instance"))