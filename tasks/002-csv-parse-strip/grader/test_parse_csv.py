import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from parse_csv import parse_csv


def test_empty_string():
    assert parse_csv("") == []


def test_headers_stripped():
    result = parse_csv(" name , age\nAlice,30")
    assert result[0]["name"] == "Alice"
    assert result[0]["age"] == "30"


def test_values_stripped():
    result = parse_csv("name,age\n Alice , 30 ")
    assert result[0]["name"] == "Alice"
    assert result[0]["age"] == "30"


def test_both_stripped():
    result = parse_csv(" name , age\nAlice , 30\n Bob,25")
    assert result == [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]


def test_no_whitespace_unaffected():
    result = parse_csv("x,y\n1,2")
    assert result == [{"x": "1", "y": "2"}]
