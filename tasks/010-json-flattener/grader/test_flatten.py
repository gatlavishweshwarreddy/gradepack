import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from flatten import flatten


def test_empty():
    assert flatten({}) == {}


def test_flat():
    assert flatten({"a": 1, "b": 2}) == {"a": 1, "b": 2}


def test_one_level_nested():
    assert flatten({"a": {"b": 1}}) == {"a.b": 1}


def test_two_levels_nested():
    assert flatten({"a": {"b": {"c": 42}}}) == {"a.b.c": 42}


def test_mixed():
    assert flatten({"a": {"b": 1, "c": 2}, "d": 3}) == {"a.b": 1, "a.c": 2, "d": 3}


def test_list_is_leaf():
    assert flatten({"a": [1, 2, 3]}) == {"a": [1, 2, 3]}


def test_custom_separator():
    assert flatten({"a": {"b": 1}}, sep="/") == {"a/b": 1}
