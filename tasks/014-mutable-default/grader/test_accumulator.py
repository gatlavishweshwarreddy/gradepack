import os, sys, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

import pytest
from accumulator import Accumulator


def test_independent_instances():
    a = Accumulator()
    b = Accumulator()
    a.add(1)
    assert b.values() == [], "b must be empty after adding to a"


def test_no_shared_default():
    """Three instances created in sequence must each start empty."""
    instances = [Accumulator() for _ in range(3)]
    instances[0].add(99)
    for i, acc in enumerate(instances[1:], 1):
        assert acc.values() == [], f"instance {i} should be empty"


def test_initial_list_is_copied():
    """Mutating the original list after construction must not affect the instance."""
    src = [1, 2, 3]
    a = Accumulator(initial=src)
    src.append(999)
    assert 999 not in a.values()


def test_initial_list_values_present():
    a = Accumulator(initial=[10, 20])
    assert a.total() == 30


@pytest.mark.parametrize("seed", [0, 1, 42, 7, 99])
def test_seeded_random_isolation(seed):
    """Seeded random: two accumulators must stay independent."""
    rng = random.Random(seed)
    a = Accumulator()
    b = Accumulator()
    ops_a = [rng.randint(1, 100) for _ in range(10)]
    ops_b = [rng.randint(1, 100) for _ in range(10)]
    for v in ops_a:
        a.add(v)
    for v in ops_b:
        b.add(v)
    assert a.values() == ops_a
    assert b.values() == ops_b
    assert a.total() == sum(ops_a)
    assert b.total() == sum(ops_b)
