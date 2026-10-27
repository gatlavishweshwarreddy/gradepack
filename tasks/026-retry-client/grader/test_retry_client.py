import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from client import HttpClient
from transport import FakeTransport, Response
from backoff import wait_seconds
import pytest


def test_backoff_attempt_1():
    assert wait_seconds(1, base=1.0) == 1.0


def test_backoff_attempt_2():
    assert wait_seconds(2, base=1.0) == 2.0


def test_backoff_attempt_3():
    assert wait_seconds(3, base=1.0) == 4.0


def test_backoff_custom_base():
    assert wait_seconds(1, base=2.0) == 2.0
    assert wait_seconds(2, base=2.0) == 4.0


def test_200_no_retry():
    t = FakeTransport([Response(200, "ok")])
    c = HttpClient(t, max_retries=3)
    resp = c.get("/")
    assert resp.status_code == 200
    assert t.call_count == 1


def test_500_retries():
    t = FakeTransport([Response(500), Response(500), Response(200)])
    c = HttpClient(t, max_retries=3, backoff_base=0.0)
    resp = c.get("/")
    assert resp.status_code == 200
    assert t.call_count == 3


def test_503_retries():
    t = FakeTransport([Response(503), Response(200)])
    c = HttpClient(t, max_retries=3, backoff_base=0.0)
    resp = c.get("/")
    assert resp.status_code == 200
    assert t.call_count == 2


def test_502_retries():
    t = FakeTransport([Response(502), Response(200)])
    c = HttpClient(t, max_retries=3, backoff_base=0.0)
    resp = c.get("/")
    assert resp.status_code == 200
    assert t.call_count == 2


def test_504_retries():
    t = FakeTransport([Response(504), Response(200)])
    c = HttpClient(t, max_retries=3, backoff_base=0.0)
    resp = c.get("/")
    assert resp.status_code == 200
    assert t.call_count == 2


def test_exhausted_retries_returns_last_response():
    t = FakeTransport([Response(500)] * 4)
    c = HttpClient(t, max_retries=3, backoff_base=0.0)
    resp = c.get("/")
    assert resp.status_code == 500
