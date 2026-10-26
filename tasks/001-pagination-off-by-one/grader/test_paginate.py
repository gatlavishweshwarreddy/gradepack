import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from paginate import paginate

ITEMS = list(range(1, 11))


def test_first_page():
    assert paginate(ITEMS, 1, 3) == [1, 2, 3]


def test_middle_page():
    assert paginate(ITEMS, 2, 3) == [4, 5, 6]


def test_last_partial_page():
    assert paginate(ITEMS, 4, 3) == [10]


def test_exact_multiple_last_page():
    assert paginate(list(range(1, 10)), 3, 3) == [7, 8, 9]


def test_page_beyond_end():
    assert paginate(ITEMS, 5, 3) == []


def test_page_zero():
    assert paginate(ITEMS, 0, 3) == []


def test_empty_items():
    assert paginate([], 1, 3) == []
