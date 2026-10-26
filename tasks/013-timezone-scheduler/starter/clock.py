from datetime import datetime, timezone


class UtcClock:
    """Returns current UTC time as a timezone-aware datetime."""

    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)
