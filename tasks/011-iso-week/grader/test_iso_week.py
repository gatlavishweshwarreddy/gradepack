import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from iso_week import iso_week


def test_year_boundary_end():
    # 2024-12-30 is in ISO week 1 of 2025
    assert iso_week("2024-12-30") == (2025, 1)


def test_year_boundary_start():
    # 2025-01-01 is in ISO week 1 of 2025
    assert iso_week("2025-01-01") == (2025, 1)


def test_prior_year_week():
    # 2023-01-01 is in ISO week 52 of 2022
    assert iso_week("2023-01-01") == (2022, 52)


def test_midyear():
    # 2024-07-15 is in ISO week 29 of 2024
    assert iso_week("2024-07-15") == (2024, 29)


def test_normal_start():
    # 2024-01-08 is in ISO week 2 of 2024
    assert iso_week("2024-01-08") == (2024, 2)
