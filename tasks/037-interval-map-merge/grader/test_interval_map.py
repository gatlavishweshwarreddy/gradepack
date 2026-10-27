import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
import pytest
import random
from interval_map import IntervalMap

def make_map(ops):
    m = IntervalMap()
    for op in ops:
        if op[0] == 'set':
            _, l, r, v = op
            m.set(l, r, v)
        elif op[0] == 'remove':
            _, l, r = op
            m.remove(l, r)
    return m

def brute_from_dict(d, lo=0, hi=50):
    # d is dict key->value
    if not d:
        return []
    intervals = []
    keys = sorted(d.keys())
    start = keys[0]
    cur_val = d[start]
    prev = start
    for k in keys[1:]:
        if k == prev + 1 and d[k] == cur_val:
            prev = k
            continue
        else:
            # close interval [start, prev+1)
            intervals.append((start, prev+1, cur_val))
            start = k
            cur_val = d[k]
            prev = k
    intervals.append((start, prev+1, cur_val))
    return intervals

@pytest.mark.parametrize("ops,expected", [
    ([('set', 0, 5, 'a')], [(0, 5, 'a')]),
    ([('set', 0, 5, 'a'), ('set', 5, 10, 'a')], [(0, 10, 'a')]),
    ([('set', 0, 5, 'a'), ('set', 5, 10, 'b')], [(0, 5, 'a'), (5, 10, 'b')]),
    ([('set', 0, 10, 'a'), ('set', 2, 8, 'a')], [(0, 10, 'a')]),
    ([('set', 0, 10, 'a'), ('set', 2, 8, 'b')], [(0, 2, 'a'), (2, 8, 'b'), (8, 10, 'a')]),
    ([('set', 0, 2, 'x'), ('set', 5, 7, 'x'), ('set', 2, 5, 'x')], [(0, 7, 'x')]),
    ([('set', 0, 10, 'a'), ('set', 10, 20, 'a'), ('set', 20, 30, 'a')], [(0, 30, 'a')]),
])
def test_set_merge_parametrized(ops, expected):
    m = make_map(ops)
    assert m.intervals() == expected

@pytest.mark.parametrize("initial_ops,remove_op,expected", [
    ([('set', 0, 10, 'a')], (2, 8), [(0, 2, 'a'), (8, 10, 'a')]),
    ([('set', 0, 10, 'a')], (0, 5), [(5, 10, 'a')]),
    ([('set', 0, 10, 'a')], (5, 10), [(0, 5, 'a')]),
    ([('set', 0, 5, 'a'), ('set', 5, 10, 'b')], (2, 7), [(0, 2, 'a'), (7, 10, 'b')]),
    ([('set', 0, 10, 'a'), ('set', 10, 20, 'b')], (5, 15), [(0, 5, 'a'), (15, 20, 'b')]),
])
def test_remove_split_parametrized(initial_ops, remove_op, expected):
    m = make_map(initial_ops)
    m.remove(*remove_op)
    assert m.intervals() == expected

@pytest.mark.parametrize("key,expected", [
    (0, 'a'),
    (4, 'a'),
    (5, None),
    (9, None),
    (-1, None),
])
def test_get_half_open_boundary(key, expected):
    m = IntervalMap()
    m.set(0, 5, 'a')
    assert m.get(key) == expected

@pytest.mark.parametrize("intervals,query,expected", [
    ([(0, 10, 'a')], (2, 8), [(2, 8, 'a')]),
    ([(0, 10, 'a'), (20, 30, 'b')], (5, 25), [(5, 10, 'a'), (20, 25, 'b')]),
    ([(0, 5, 'a'), (5, 10, 'b')], (0, 10), [(0, 5, 'a'), (5, 10, 'b')]),
    ([(0, 10, 'a')], (10, 20), []),
    ([(0, 10, 'a'), (15, 20, 'b')], (8, 17), [(8, 10, 'a'), (15, 17, 'b')]),
])
def test_overlapping_intervals_clipped(intervals, query, expected):
    m = IntervalMap()
    for l, r, v in intervals:
        m.set(l, r, v)
    assert m.overlapping_intervals(*query) == expected

@pytest.mark.parametrize("ops,expected_covered", [
    ([('set', 0, 5, 'a')], 5),
    ([('set', 0, 5, 'a'), ('set', 5, 10, 'a')], 10),
    ([('set', 0, 10, 'a'), ('remove', 2, 8)], 4),
    ([('set', 0, 5, 'a'), ('set', 10, 15, 'b')], 10),
    ([], 0),
])
def test_total_covered_parametrized(ops, expected_covered):
    m = make_map(ops)
    assert m.total_covered() == expected_covered

def test_intervals_returns_copy_and_tuples():
    m = IntervalMap()
    m.set(0, 5, 'a')
    iv = m.intervals()
    assert len(iv) == 1
    assert isinstance(iv[0], tuple)
    # mutate returned list should not affect internal
    iv.append((10, 20, 'b'))
    assert len(m.intervals()) == 1
    # mutate inner list if it were list reference would affect; check copy
    iv2 = m.intervals()
    iv2[0] = (99, 100, 'z')
    assert m.intervals() == [(0, 5, 'a')]

def test_get_interval():
    m = IntervalMap()
    m.set(0, 5, 'a')
    m.set(10, 15, 'b')
    assert m.get_interval(2) == (0, 5, 'a')
    assert m.get_interval(5) is None
    assert m.get_interval(12) == (10, 15, 'b')
    assert m.get_interval(7) is None

def test_len_and_contains():
    m = IntervalMap()
    assert len(m) == 0
    m.set(0, 5, 'a')
    assert len(m) == 1
    assert 0 in m
    assert 4 in m
    assert 5 not in m
    m.set(5, 10, 'a')
    assert len(m) == 1  # merged
    assert 7 in m
    m.set(20, 25, 'b')
    assert len(m) == 2

def test_error_handling():
    m = IntervalMap()
    with pytest.raises(ValueError):
        m.set(5, 5, 'a')
    with pytest.raises(ValueError):
        m.set(10, 5, 'a')
    with pytest.raises(ValueError):
        m.set(0, 5, None)
    with pytest.raises(ValueError):
        m.remove(5, 5)
    with pytest.raises(ValueError):
        m.overlapping_intervals(5, 5)
    with pytest.raises(ValueError):
        m.overlapping_intervals(10, 2)

def test_remove_middle_split_both_sides():
    m = IntervalMap()
    m.set(0, 10, 'a')
    m.remove(3, 7)
    assert m.intervals() == [(0, 3, 'a'), (7, 10, 'a')]
    assert m.get(2) == 'a'
    assert m.get(3) is None
    assert m.get(6) is None
    assert m.get(7) == 'a'
    assert m.total_covered() == 6

def test_set_overwrite_and_merge_chain():
    m = IntervalMap()
    m.set(0, 2, 'a')
    m.set(4, 6, 'a')
    m.set(8, 10, 'a')
    assert m.intervals() == [(0, 2, 'a'), (4, 6, 'a'), (8, 10, 'a')]
    m.set(2, 8, 'a')
    assert m.intervals() == [(0, 10, 'a')]

def test_random_brute_force_seeded():
    random.seed(42)
    m = IntervalMap()
    brute = {}
    # domain 0..50
    for _ in range(200):
        op = random.choice(['set', 'remove'])
        l = random.randint(0, 49)
        r = random.randint(l+1, 50)
        if op == 'set':
            v = random.choice(['a', 'b', 'c'])
            m.set(l, r, v)
            for k in range(l, r):
                brute[k] = v
        else:
            m.remove(l, r)
            for k in range(l, r):
                brute.pop(k, None)
        # check all keys
        for k in range(0, 50):
            assert m.get(k) == brute.get(k), f"get mismatch at key {k} after op {op} [{l},{r})"
        # check intervals equal brute intervals
        expected_intervals = brute_from_dict(brute, 0, 50)
        assert m.intervals() == expected_intervals, f"intervals mismatch after op {op} [{l},{r}) got {m.intervals()} expected {expected_intervals}"
        # check total_covered
        expected_covered = len(brute)
        assert m.total_covered() == expected_covered
        # check overlapping query random
        ql = random.randint(0, 49)
        qr = random.randint(ql+1, 50)
        # brute overlapping
        brute_over = []
        for a, b, v in expected_intervals:
            if b <= ql or a >= qr:
                continue
            brute_over.append((max(a, ql), min(b, qr), v))
        assert m.overlapping_intervals(ql, qr) == brute_over
        # check len and contains
        assert len(m) == len(expected_intervals)
        for k in range(0, 50):
            assert (k in m) == (k in brute)