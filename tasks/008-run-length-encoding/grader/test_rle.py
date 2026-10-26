import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from rle import encode, decode


def test_encode_empty():
    assert encode("") == []


def test_encode_single():
    assert encode("a") == [("a", 1)]


def test_encode_run():
    assert encode("aaabbc") == [("a", 3), ("b", 2), ("c", 1)]


def test_encode_all_same():
    assert encode("xxxx") == [("x", 4)]


def test_encode_alternating():
    assert encode("ababab") == [("a", 1), ("b", 1), ("a", 1), ("b", 1), ("a", 1), ("b", 1)]


def test_decode_basic():
    assert decode([("a", 3), ("b", 2), ("c", 1)]) == "aaabbc"


def test_decode_single():
    assert decode([("z", 1)]) == "z"


def test_roundtrip():
    s = "aaabbc"
    assert decode(encode(s)) == s
