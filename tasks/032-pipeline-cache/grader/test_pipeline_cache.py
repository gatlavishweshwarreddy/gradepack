import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from pipeline import Pipeline
from transform import Transform
import pytest


def _double(data):
    return [x * 2 for x in data]


def _add_one(data):
    return [x + 1 for x in data]


def test_pipeline_basic():
    p = Pipeline([Transform(_double, "double")])
    assert p.run([1, 2, 3]) == [2, 4, 6]


def test_pipeline_chain():
    p = Pipeline([Transform(_double, "double"), Transform(_add_one, "add_one")])
    assert p.run([1, 2, 3]) == [3, 5, 7]


def test_cache_invalidated_on_mutation():
    p = Pipeline([Transform(_double, "double")])
    data = [1, 2, 3]
    r1 = p.run(data)
    assert r1 == [2, 4, 6]
    data[0] = 10
    r2 = p.run(data)
    assert r2 == [20, 4, 6], f"Cache should be invalidated after mutation, got {r2}"


def test_same_content_same_result():
    p = Pipeline([Transform(_double, "double")])
    assert p.run([5, 6]) == p.run([5, 6])


def test_different_inputs_different_results():
    p = Pipeline([Transform(_double, "double")])
    r1 = p.run([1, 2])
    r2 = p.run([3, 4])
    assert r1 == [2, 4]
    assert r2 == [6, 8]
