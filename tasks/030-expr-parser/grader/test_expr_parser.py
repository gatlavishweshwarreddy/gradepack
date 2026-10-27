import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from expr import evaluate
import pytest


def test_addition():
    assert evaluate("1 + 2") == 3.0


def test_multiplication():
    assert evaluate("3 * 4") == 12.0


def test_precedence_mul_before_add():
    assert evaluate("3 + 4 * 2") == 11.0, "multiplication must bind tighter than addition"


def test_precedence_add_then_mul():
    assert evaluate("2 * 3 + 4") == 10.0


def test_mixed_precedence():
    assert evaluate("1 + 2 * 3 + 4") == 11.0


def test_parentheses_override_precedence():
    assert evaluate("(3 + 4) * 2") == 14.0


def test_variable_substitution():
    assert evaluate("x * 2 + 1", {"x": 5}) == 11.0


def test_variable_precedence():
    assert evaluate("a + b * c", {"a": 1, "b": 2, "c": 3}) == 7.0


def test_backward_compat_no_variables():
    assert evaluate("10 - 3") == 7.0
    assert evaluate("8 / 4") == 2.0


def test_regression_single_arg():
    assert evaluate("5 + 5") == 10.0
    assert evaluate("2 * 2 * 2") == 8.0
