import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from word_frequency import word_frequency


def test_empty():
    assert word_frequency("") == {}


def test_case_insensitive():
    result = word_frequency("Hello hello")
    assert result == {"Hello": 2} or result == {"hello": 2}


def test_punctuation_stripped():
    result = word_frequency("word. word")
    # both tokens should map to the same normalised key
    total = sum(result.values())
    assert total == 2
    assert len(result) == 1


def test_mixed():
    result = word_frequency("Hello, hello! World.")
    assert result.get("hello") == 2 or result.get("Hello") == 2
    assert result.get("world") == 1 or result.get("World") == 1
    assert len(result) == 2


def test_no_punctuation_unaffected():
    assert word_frequency("a b a") == {"a": 2, "b": 1}
