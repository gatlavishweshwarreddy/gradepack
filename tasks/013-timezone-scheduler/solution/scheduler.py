from datetime import datetime, timezone, timedelta
import zoneinfo


class EventScheduler:
    def __init__(self, clock):
        self._clock = clock
        self._events: list[tuple[str, datetime]] = []

    def add_event(self, name: str, utc_dt: datetime) -> None:
        if utc_dt.tzinfo is None:
            raise ValueError(f"utc_dt must be timezone-aware, got naive datetime: {utc_dt!r}")
        self._events.append((name, utc_dt))

    def next_event_in(self, tz_name: str) -> tuple[str, timedelta] | None:
        tz = zoneinfo.ZoneInfo(tz_name)
        now = self._clock.now()  # UTC-aware
        upcoming = [
            (name, dt) for name, dt in self._events
            if dt > now
        ]
        if not upcoming:
            return None
        upcoming.sort(key=lambda x: x[1])
        name, dt = upcoming[0]
        return name, dt - now
