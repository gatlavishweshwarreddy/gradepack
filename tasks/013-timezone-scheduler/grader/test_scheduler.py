from datetime import datetime, timezone, timedelta
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

import pytest
from scheduler import EventScheduler


# ---------------------------------------------------------------------------
# Fake clock for deterministic tests
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self, dt: datetime):
        self._now = dt

    def now(self) -> datetime:
        return self._now


BASE_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_add_naive_raises():
    """add_event must reject a naive (tzinfo=None) datetime."""
    sched = EventScheduler(FakeClock(BASE_NOW))
    with pytest.raises(ValueError):
        sched.add_event("meeting", datetime(2024, 6, 1, 13, 0, 0))  # naive


def test_add_aware_accepted():
    sched = EventScheduler(FakeClock(BASE_NOW))
    dt = datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc)
    sched.add_event("lunch", dt)  # should not raise


def test_next_event_correct_delta():
    """next_event_in must return the correct timedelta to the nearest future event."""
    clock = FakeClock(BASE_NOW)
    sched = EventScheduler(clock)
    future = BASE_NOW + timedelta(hours=3)
    sched.add_event("standup", future)
    result = sched.next_event_in("UTC")
    assert result is not None
    name, delta = result
    assert name == "standup"
    assert abs(delta.total_seconds() - 3 * 3600) < 1


def test_next_event_picks_nearest():
    clock = FakeClock(BASE_NOW)
    sched = EventScheduler(clock)
    sched.add_event("far", BASE_NOW + timedelta(hours=10))
    sched.add_event("near", BASE_NOW + timedelta(hours=1))
    name, _ = sched.next_event_in("UTC")
    assert name == "near"


def test_no_future_events_returns_none():
    clock = FakeClock(BASE_NOW)
    sched = EventScheduler(clock)
    sched.add_event("past", BASE_NOW - timedelta(hours=1))
    assert sched.next_event_in("UTC") is None


@pytest.mark.parametrize("offset_hours,tz_name", [
    (5, "UTC"),
    (2, "UTC"),
    (8, "UTC"),
])
def test_parametrized_deltas(offset_hours, tz_name):
    """next_event_in delta must equal offset regardless of named timezone."""
    clock = FakeClock(BASE_NOW)
    sched = EventScheduler(clock)
    future = BASE_NOW + timedelta(hours=offset_hours)
    sched.add_event("e", future)
    _, delta = sched.next_event_in(tz_name)
    assert abs(delta.total_seconds() - offset_hours * 3600) < 1
