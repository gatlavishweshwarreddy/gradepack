import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from importer import import_csv
from coerce import coerce
import pytest


def test_integer_column_plain():
    rows = [{"qty": "5"}]
    result = import_csv(rows, {"qty": "int"})
    assert result[0]["qty"] == 5


def test_integer_column_float_string():
    rows = [{"qty": "1.0"}]
    result = import_csv(rows, {"qty": "int"})
    assert result[0]["qty"] == 1


def test_integer_column_float_string_42():
    rows = [{"qty": "42.0"}]
    result = import_csv(rows, {"qty": "int"})
    assert result[0]["qty"] == 42


def test_float_column():
    rows = [{"price": "9.99"}]
    result = import_csv(rows, {"price": "float"})
    assert result[0]["price"] == pytest.approx(9.99)


def test_str_column():
    rows = [{"name": "Alice"}]
    result = import_csv(rows, {"name": "str"})
    assert result[0]["name"] == "Alice"


def test_mixed_schema():
    rows = [{"name": "Bob", "qty": "3.0", "price": "12.50"}]
    result = import_csv(rows, {"name": "str", "qty": "int", "price": "float"})
    assert result[0]["name"] == "Bob"
    assert result[0]["qty"] == 3
    assert result[0]["price"] == pytest.approx(12.50)


def test_invalid_int_raises():
    rows = [{"qty": "abc"}]
    with pytest.raises(ValueError):
        import_csv(rows, {"qty": "int"})


def test_invalid_schema_type():
    from schema import validate_schema
    with pytest.raises(ValueError):
        validate_schema({"col": "boolean"})


def test_multiple_rows():
    rows = [{"x": "1.0"}, {"x": "2.0"}, {"x": "3.0"}]
    result = import_csv(rows, {"x": "int"})
    assert [r["x"] for r in result] == [1, 2, 3]
