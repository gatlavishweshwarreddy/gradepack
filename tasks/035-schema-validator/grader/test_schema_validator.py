import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from schema import Schema
from validator import validate
import pytest


def _make_schema():
    s = Schema()
    s.define("address", {"type": "string"})
    s.load({
        "required": ["name", "age"],
        "properties": {
            "name": {"$ref": "address"},
            "age":  {"type": "integer"},
        }
    })
    return s


def test_valid_data_no_errors():
    s = _make_schema()
    errors = validate({"name": "Alice", "age": 30}, s)
    assert errors == [], f"Expected no errors, got: {errors}"


def test_missing_required_field():
    s = _make_schema()
    errors = validate({"name": "Bob"}, s)
    assert any("age" in e for e in errors)


def test_wrong_type():
    s = _make_schema()
    errors = validate({"name": "Carol", "age": "thirty"}, s)
    assert any("age" in e for e in errors)


def test_two_calls_same_schema_both_correct():
    s = _make_schema()
    errors1 = validate({"name": "Dave", "age": 25}, s)
    errors2 = validate({"name": "Eve",  "age": 40}, s)
    assert errors1 == [], f"First call errors: {errors1}"
    assert errors2 == [], f"Second call errors (schema mutation bug?): {errors2}"


def test_two_calls_second_catches_error():
    s = _make_schema()
    errors1 = validate({"name": "Fred", "age": 1}, s)
    errors2 = validate({"age": 2}, s)  # missing name
    assert errors1 == []
    assert any("name" in e for e in errors2), \
        f"Second call should catch missing 'name', got: {errors2}"
