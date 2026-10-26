from datetime import datetime, timezone, timedelta
import zoneinfo


class EventScheduler:
    def __init__(self, clock):
        self._clock = clock
        self._events: list[tuple[str, datetime]] = []

    def add_event(self, name: str, utc_dt: datetime) -> None:
        # BUG 1: silently accepts naive datetimes instead of raising ValueError
        if utc_dt.tzinfo is not None:
            self._events.append((name, utc_dt))
        else:
            # strip tzinfo silently — wrong
            self._events.append((name, utc_dt))

    def next_event_in(self, tz_name: str) -> tuple[str, timedelta] | None:
        tz = zoneinfo.ZoneInfo(tz_name)
        # BUG 2: builds naive 'now' instead of using self._clock.now()
        now = datetime.utcnow()  # naive — wrong for aware comparisons
        upcoming = [
            (name, dt) for name, dt in self._events
            if dt.replace(tzinfo=None) > now  # compares aware dt to naive now
        ]
        if not upcoming:
            return None
        upcoming.sort(key=lambda x: x[1])
        name, dt = upcoming[0]
        delta = dt.astimezone(tz) - dt.astimezone(tz).replace(
            hour=now.hour, minute=now.minute, second=now.second, microsecond=now.microsecond
        )
        return name, dt - self._clock.now()
