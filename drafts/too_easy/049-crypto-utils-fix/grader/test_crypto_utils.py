import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'starter'))

import base64
import hashlib
import hmac
import json
import crypto_utils


def test_b64url_encode_no_padding():
    for data in [b"", b"a", b"ab", b"abc", b"abcd", b"hello world", b"\x00\xff\x10\xfe"]:
        enc = crypto_utils.b64url_encode(data)
        assert "=" not in enc, f"padding found in {enc!r} for {data!r}"
        padded = enc + "=" * (-len(enc) % 4)
        assert base64.urlsafe_b64decode(padded) == data


def test_b64url_roundtrip():
    cases = [b"", b"a", b"ab", b"abc", b"abcd", b"abcde", b"abcdef", b"\x00\x01\x02\xff\xfe", b"hello", b"\x00"*10]
    for data in cases:
        enc = crypto_utils.b64url_encode(data)
        dec = crypto_utils.b64url_decode(enc)
        assert dec == data, f"roundtrip failed for {data!r}: {enc!r} -> {dec!r}"
    assert crypto_utils.b64url_decode("YQ") == b"a"
    assert crypto_utils.b64url_decode("YWI") == b"ab"
    assert crypto_utils.b64url_decode("YWJj") == b"abc"
    assert crypto_utils.b64url_decode("") == b""
    assert crypto_utils.b64url_decode("SGVsbG8") == b"Hello"


def test_b64url_rejects_invalid_length():
    try:
        crypto_utils.b64url_decode("A")
        assert False, "should have raised ValueError for len%4==1"
    except ValueError:
        pass
    try:
        crypto_utils.b64url_decode("AAAAA")
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_constant_time_equal_uses_compare_digest():
    orig = hmac.compare_digest
    called = []
    def fake(a, b):
        called.append(1)
        return orig(a, b)
    hmac.compare_digest = fake
    try:
        assert crypto_utils.constant_time_equal(b"abc", b"abc") is True
        assert crypto_utils.constant_time_equal(b"abc", b"abd") is False
        assert crypto_utils.constant_time_equal(b"abc", b"ab") is False
        assert crypto_utils.constant_time_equal(b"", b"") is True
        assert len(called) >= 4, f"constant_time_equal must use hmac.compare_digest, called {len(called)} times"
    finally:
        hmac.compare_digest = orig


def test_hkdf_rfc_vector():
    ikm = bytes.fromhex("0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b")
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = crypto_utils.hkdf(salt, ikm, info, 42)
    expected = bytes.fromhex("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865")
    assert okm == expected


def test_hkdf_expand_counter():
    prk = bytes.fromhex("077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = crypto_utils.hkdf_expand(prk, info, 42)
    expected = bytes.fromhex("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865")
    assert okm == expected
    # test longer output requiring multiple blocks
    okm2 = crypto_utils.hkdf_expand(prk, info, 64)
    assert len(okm2) == 64
    assert okm2[:42] == expected


def test_hash_password_correctness():
    for it in [1, 2, 10, 100]:
        expected = hashlib.pbkdf2_hmac('sha256', b"password", b"salt", it, dklen=32)
        actual = crypto_utils.hash_password(b"password", b"salt", it)
        assert actual == expected, f"mismatch for iterations={it}"
    expected = hashlib.pbkdf2_hmac('sha256', b"hello", b"world", 50, dklen=32)
    actual = crypto_utils.hash_password(b"hello", b"world", 50)
    assert actual == expected
    # verify_password should work
    pw = b"secret"
    salt = b"salty"
    h = crypto_utils.hash_password(pw, salt, 20)
    assert crypto_utils.verify_password(pw, salt, 20, h) is True
    assert crypto_utils.verify_password(b"wrong", salt, 20, h) is False


def test_hash_password_operation_count():
    orig = hmac.new
    count = 0
    def counting(*args, **kwargs):
        nonlocal count
        count += 1
        return orig(*args, **kwargs)
    hmac.new = counting
    try:
        count = 0
        crypto_utils.hash_password(b"pw", b"salt", 5)
        assert count == 5, f"expected 5 HMAC calls, got {count}"
        count = 0
        crypto_utils.hash_password(b"pw", b"salt", 1)
        assert count == 1, f"expected 1 HMAC call, got {count}"
        count = 0
        crypto_utils.hash_password(b"pw", b"salt", 100)
        assert count == 100, f"expected 100 HMAC calls, got {count}"
    finally:
        hmac.new = orig


def test_token_determinism():
    key = b"secretkey123"
    payload1 = {"b": 2, "a": 1, "c": 3}
    payload2 = {"a": 1, "c": 3, "b": 2}
    token1 = crypto_utils.create_token(payload1, key)
    token2 = crypto_utils.create_token(payload2, key)
    assert token1 == token2, f"tokens differ with different key order: {token1} vs {token2}"
    assert "=" not in token1, "token must not contain padding"
    decoded = crypto_utils.verify_token(token1, key)
    assert decoded == {"a": 1, "b": 2, "c": 3}
    # nested payload determinism
    p1 = {"z": [3, 2, 1], "a": {"y": 1, "x": 2}}
    p2 = {"a": {"x": 2, "y": 1}, "z": [3, 2, 1]}
    assert crypto_utils.create_token(p1, key) == crypto_utils.create_token(p2, key)


def test_token_verify_tamper_and_alg():
    key = b"supersecret"
    payload = {"user": "alice", "role": "admin"}
    token = crypto_utils.create_token(payload, key)
    assert crypto_utils.verify_token(token, key) == payload
    parts = token.split(".")
    # tampered payload
    tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"
    try:
        crypto_utils.verify_token(tampered_token, key)
        assert False, "tampered payload should be rejected"
    except ValueError:
        pass
    # wrong key
    try:
        crypto_utils.verify_token(token, b"wrongkey")
        assert False, "wrong key should be rejected"
    except ValueError:
        pass
    # tampered signature
    tampered_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
    tampered_sig_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"
    try:
        crypto_utils.verify_token(tampered_sig_token, key)
        assert False, "tampered signature should be rejected"
    except ValueError:
        pass
    # wrong alg should be rejected
    def b64url_enc(d):
        return base64.urlsafe_b64encode(d).decode().rstrip("=")
    header = {"alg": "HS384", "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    header_b64 = b64url_enc(header_json)
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload_b64 = b64url_enc(payload_json)
    signing_input = f"{header_b64}.{payload_b64}".encode()
    sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    sig_b64 = b64url_enc(sig)
    fake_token = f"{header_b64}.{payload_b64}.{sig_b64}"
    try:
        crypto_utils.verify_token(fake_token, key)
        assert False, "wrong alg should be rejected"
    except ValueError:
        pass
    # verify uses constant_time_equal
    orig = hmac.compare_digest
    called = []
    def fake(a, b):
        called.append(1)
        return orig(a, b)
    hmac.compare_digest = fake
    try:
        crypto_utils.verify_token(token, key)
        assert len(called) >= 1, "verify_token must use constant_time_equal / compare_digest"
    finally:
        hmac.compare_digest = orig


def test_token_invalid_format():
    key = b"k"
    try:
        crypto_utils.verify_token("only.two", key)
        assert False
    except ValueError:
        pass
    try:
        crypto_utils.verify_token("a.b.c.d", key)
        assert False
    except ValueError:
        pass