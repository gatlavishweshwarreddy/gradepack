import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from event import Event
from store import EventStore
from projector import Projector
import pytest


def _make_store():
    store = EventStore()
    # Insert out of order
    store.append(Event(3, "set",       {"key": "c", "value": 30}))
    store.append(Event(1, "set",       {"key": "a", "value": 10}))
    store.append(Event(4, "increment", {"key": "a", "by": 5}))
    store.append(Event(2, "set",       {"key": "b", "value": 20}))
    store.append(Event(5, "delete",    {"key": "b"}))
    return store


def test_replay_from_zero_all_events():
    store = _make_store()
    proj = Projector()
    state = proj.apply(store.replay(0))
    assert state == {"a": 15, "c": 30}, f"Got: {state}"


def test_replay_from_seq_includes_boundary():
    store = _make_store()
    proj = Projector()
    state = proj.apply(store.replay(3))
    assert state == {"c": 30, "a": 5}, f"Got: {state}"


def test_replay_sorted_order():
    store = _make_store()
    events = store.replay(0)
    seqs = [e.sequence for e in events]
    assert seqs == sorted(seqs), f"Events not in sequence order: {seqs}"


def test_replay_from_seq_1():
    store = _make_store()
    proj = Projector()
    state = proj.apply(store.replay(1))
    assert state.get("a") is not None


def test_empty_replay():
    store = EventStore()
    assert store.replay(0) == []
