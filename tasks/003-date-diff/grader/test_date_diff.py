import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from date_diff import days_between


def test_forward_order():
    assert days_between("2024-01-01", "2024-01-10") == 9


def test_reverse_order():
    assert days_between("2024-01-10", "2024-01-01") == 9


def test_year_boundary():
    assert days_between("2023-12-31", "2024-01-01") == 1


def test_leap_year_feb():
    assert days_between("2024-02-28", "2024-03-01") == 2


def test_same_day():
    assert days_between("2024-06-15", "2024-06-15") == 0
