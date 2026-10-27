import os
import sys
import math
import struct
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))
from codec import Codec


def test_basic_roundtrip():
    c = Codec()
    cases = [None, True, False, 0, 1, 42, 3.14, -2.5, "hello", b"bytes", [1, 2, 3], {"a": 1, "b": 2}, {1, 2, 3}]
    for obj in cases:
        data = c.dumps(obj)
        out = c.loads(data)
        assert out == obj


def test_negative_and_large_integers():
    c = Codec()
    nums = [-1, -2, -1000, -2**31, -2**63 + 1, 0, 1, 127, 128, 255, 256, 2**31 - 1, 2**63 - 1, 2**70, 2**100, -2**70, -2**100]
    for n in nums:
        data = c.dumps(n)
        out = c.loads(data)
        assert out == n, f"failed for {n}: got {out}"


def test_float_roundtrip():
    c = Codec()
    floats = [0.0, -0.0, 1.5, -1.5, 1e100, -1e-100, float('inf'), float('-inf'), 3.141592653589793]
    for f in floats:
        data = c.dumps(f)
        out = c.loads(data)
        if math.isnan(f):
            assert math.isnan(out)
        else:
            assert out == f, f"float mismatch {f} vs {out}"
            assert data == c.dumps(f)


def test_unicode_strings():
    c = Codec()
    cases = ["hello", "café", "naïve", "😀😁😂", "a" * 200, "é" * 200, "hello 🌍 world", ""]
    for s in cases:
        data = c.dumps(s)
        out = c.loads(data)
        assert out == s, f"unicode mismatch for {s!r}"
    assert c.loads(c.dumps(b"\xff\x00\xfe")) == b"\xff\x00\xfe"
    assert c.loads(c.dumps(b"")) == b""
    long_bytes = b"a" * 500
    assert c.loads(c.dumps(long_bytes)) == long_bytes


def test_shared_reference_identity():
    c = Codec()
    inner = [1, 2, 3]
    outer = [inner, inner]
    data = c.dumps(outer)
    out = c.loads(data)
    assert out[0] == [1, 2, 3]
    assert out[1] == [1, 2, 3]
    assert out[0] is out[1], "shared list identity not preserved"
    inner2 = {"x": 1}
    outer2 = [inner2, inner2]
    out2 = c.loads(c.dumps(outer2))
    assert out2[0] is out2[1]
    assert out2[0] == {"x": 1}
    inner3 = [10, 20]
    outer3 = {"a": inner3, "b": inner3}
    out3 = c.loads(c.dumps(outer3))
    assert out3["a"] is out3["b"]


def test_cyclic_structure():
    c = Codec()
    a = []
    a.append(a)
    data = c.dumps(a)
    out = c.loads(data)
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0] is out, "cyclic list not preserved"
    d = {}
    d["self"] = d
    data2 = c.dumps(d)
    out2 = c.loads(data2)
    assert isinstance(out2, dict)
    assert out2["self"] is out2
    lst = []
    d2 = {"lst": lst}
    lst.append(d2)
    data3 = c.dumps(lst)
    out3 = c.loads(data3)
    assert out3[0]["lst"] is out3


def test_canonical_dict_encoding():
    c = Codec()
    d1 = {"b": 2, "a": 1, "c": 3}
    d2 = {"a": 1, "c": 3, "b": 2}
    d3 = {"c": 3, "b": 2, "a": 1}
    assert c.dumps(d1) == c.dumps(d2) == c.dumps(d3)
    d4 = {"z": {"b": 2, "a": 1}, "a": 1}
    d5 = {"a": 1, "z": {"a": 1, "b": 2}}
    assert c.dumps(d4) == c.dumps(d5)
    assert c.dumps(d1) == c.dumps(d1)


def test_canonical_set_encoding():
    c = Codec()
    s1 = {3, 1, 2}
    s2 = {2, 3, 1}
    s3 = {1, 2, 3}
    assert c.dumps(s1) == c.dumps(s2) == c.dumps(s3)
    nested = [{1, 2}, {3, 4}]
    assert c.loads(c.dumps(nested)) == nested


def test_compact_shared_encoding():
    c = Codec()
    inner = [1, 2, 3] * 50
    outer = [inner] * 100
    data = c.dumps(outer)
    assert len(data) < 5000, f"encoded too large: {len(data)} suggests sharing not implemented"
    out = c.loads(data)
    assert out[0] == inner
    assert out[0] is out[1]
    assert out[1] is out[50]
    large_str = "a" * 500
    assert c.loads(c.dumps(large_str)) == large_str
    large_list = list(range(200))
    data2 = c.dumps(large_list)
    assert c.loads(data2) == large_list
    large_bytes = b"x" * 300
    assert c.loads(c.dumps(large_bytes)) == large_bytes


def test_invalid_input_rejection():
    c = Codec()
    data = c.dumps([1, 2, 3])
    with pytest.raises(ValueError):
        c.loads(data + b"\x00")
    with pytest.raises(ValueError):
        c.loads(data[:-1])
    with pytest.raises(ValueError):
        c.loads(b"\xff")
    with pytest.raises(ValueError):
        c.loads(b"")
    with pytest.raises(TypeError):
        c.loads("not bytes")
    with pytest.raises(ValueError):
        c.loads(b"\x0a\x00")
    truncated_float = struct.pack('B', 0x04) + b"\x00\x01"
    with pytest.raises(ValueError):
        c.loads(truncated_float)