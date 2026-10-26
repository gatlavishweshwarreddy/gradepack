import os, sys, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

import pytest
from window import sliding_max


def _brute_sliding_max(nums, k):
    """Reference implementation."""
    if not nums or k <= 0:
        return []
    return [max(nums[i:i+k]) for i in range(len(nums) - k + 1)]


@pytest.mark.parametrize("nums,k,expected", [
    ([3, 1, 2, 5, 4], 3, [3, 5, 5]),
    ([1], 1, [1]),
    ([], 3, []),
    ([1, 2, 3, 4, 5], 2, [2, 3, 4, 5]),
    ([5, 4, 3, 2, 1], 3, [5, 4, 3]),
    ([1, 3, 1, 3, 1], 3, [3, 3, 3]),
    ([2, 1, 5, 3, 6, 4, 8, 7], 4, [5, 6, 6, 8, 8]),
])
def test_parametrized(nums, k, expected):
    assert sliding_max(nums, k) == expected


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 123])
def test_random_vs_brute(seed):
    rng = random.Random(seed)
    nums = [rng.randint(0, 100) for _ in range(rng.randint(5, 30))]
    k = rng.randint(1, min(5, len(nums)))
    assert sliding_max(nums, k) == _brute_sliding_max(nums, k)
