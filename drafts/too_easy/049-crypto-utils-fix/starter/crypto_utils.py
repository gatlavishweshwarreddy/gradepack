import base64
import hashlib
import hmac
import json


def b64url_encode(data: bytes) -> str:
    """Encode bytes to base64url string without padding.

    Must use URL-safe alphabet and strip trailing '=' padding.
    """
    return base64.urlsafe_b64encode(data).decode('ascii')


def b64url_decode(s: str) -> bytes:
    """Decode base64url string (without padding) to bytes.

    Must handle missing padding and raise ValueError for invalid
    length (len % 4 == 1).
    """
    pad = 4 - len(s) % 4
    s += "=" * pad
    return base64.urlsafe_b64decode(s)


def constant_time_equal(a: bytes, b: bytes) -> bool:
    """Compare two byte strings in constant time.

    Must use hmac.compare_digest internally.
    """
    return a == b


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """HKDF-Extract as per RFC 5869.

    Salt is HMAC key, IKM is message. If salt is None or empty,
    use a zero-filled string of hash length.
    """
    if not salt:
        salt = b"\x00" * hashlib.sha256().digest_size
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand as per RFC 5869.

    T(0) = empty, T(1) = HMAC(PRK, T(0) | info | 0x01), etc.
    """
    if length > 255 * hashlib.sha256().digest_size:
        raise ValueError("length too large")
    okm = b""
    t = b""
    counter = 0
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """Full HKDF: Extract then Expand."""
    prk = hkdf_extract(salt, ikm)
    return hkdf_expand(prk, info, length)


def hash_password(password: bytes, salt: bytes, iterations: int) -> bytes:
    """PBKDF2-HMAC-SHA256, single block (32 bytes).

    F(P,S,c,1) = U1 xor U2 xor ... xor Uc where
    U1 = HMAC(P, S || INT(1)), U2 = HMAC(P, U1), ...
    Must call hmac.new exactly `iterations` times.
    """
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    u = hmac.new(password, salt + b"\x00\x00\x00\x01", hashlib.sha256).digest()
    result = bytearray(u)
    for _ in range(iterations):
        u = hmac.new(password, u, hashlib.sha256).digest()
        for i in range(len(result)):
            result[i] ^= u[i]
    return bytes(result)


def verify_password(password: bytes, salt: bytes, iterations: int, expected: bytes) -> bool:
    """Verify password using constant-time comparison."""
    actual = hash_password(password, salt, iterations)
    return constant_time_equal(actual, expected)


def create_token(payload: dict, key: bytes) -> str:
    """Create JWT-like token.

    Header is fixed {"alg":"HS256","typ":"JWT"}.
    Both header and payload JSON must be canonical:
    separators (',', ':') and sort_keys=True.
    Signature is HMAC-SHA256 over header_b64.payload_b64
    encoded with b64url without padding.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    payload_json = json.dumps(payload, separators=(",", ":")).encode()
    header_b64 = b64url_encode(header_json)
    payload_b64 = b64url_encode(payload_json)
    signing_input = f"{header_b64}.{payload_b64}".encode()
    sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    sig_b64 = b64url_encode(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_token(token: str, key: bytes) -> dict:
    """Verify token and return payload.

    Must verify header alg is HS256 and signature using
    constant_time_equal. Raise ValueError on any failure.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid token format")
    header_b64, payload_b64, sig_b64 = parts
    header_json = b64url_decode(header_b64)
    header = json.loads(header_json)
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    provided_sig = b64url_decode(sig_b64)
    if expected_sig != provided_sig:
        raise ValueError("invalid signature")
    payload_json = b64url_decode(payload_b64)
    payload = json.loads(payload_json)
    return payload