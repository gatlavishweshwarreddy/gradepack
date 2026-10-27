import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from merger import merge
import pytest


def test_simple_override():
    base = {"a": 1, "b": 2}
    result = merge(base, {"b": 99})
    assert result == {"a": 1, "b": 99}


def test_adds_new_key():
    base = {"a": 1}
    result = merge(base, {"z": 9})
    assert result == {"a": 1, "z": 9}


def test_deep_merge():
    base = {"db": {"host": "localhost", "port": 5432}}
    result = merge(base, {"db": {"port": 5433}})
    assert result == {"db": {"host": "localhost", "port": 5433}}


def test_base_unchanged_after_merge():
    base = {"db": {"host": "localhost", "port": 5432}, "debug": False}
    _ = merge(base, {"db": {"port": 5433}})
    assert base == {"db": {"host": "localhost", "port": 5432}, "debug": False}


def test_two_merges_same_base():
    base = {"x": {"a": 1, "b": 2}, "y": 0}
    r1 = merge(base, {"x": {"b": 99}})
    r2 = merge(base, {"x": {"a": 55}})
    assert r1 == {"x": {"a": 1, "b": 99}, "y": 0}
    assert r2 == {"x": {"a": 55, "b": 2}, "y": 0}


def test_nested_three_levels():
    base = {"a": {"b": {"c": 1}}}
    r1 = merge(base, {"a": {"b": {"c": 2}}})
    assert r1 == {"a": {"b": {"c": 2}}}
    assert base == {"a": {"b": {"c": 1}}}


def test_override_wins_non_dict():
    base = {"k": {"nested": True}}
    result = merge(base, {"k": "flat"})
    assert result["k"] == "flat"


def test_empty_override():
    base = {"a": 1}
    result = merge(base, {})
    assert result == {"a": 1}
    assert base == {"a": 1}
