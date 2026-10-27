import datetime


def duration_seconds(entries):
    """
    Return elapsed seconds between first and last entry.
    Returns 0 if fewer than 2 entries.
    Handles log sequences that span midnight by adding 86400 seconds
    when the last time is earlier than the first time.
    """
    if len(entries) < 2:
        return 0
    base = datetime.date(2000, 1, 1)
    next_day = datetime.date(2000, 1, 2)
    first_dt = datetime.datetime.combine(base, entries[0].time)
    last_t = entries[-1].time
    # If last time is earlier than first time, the log spans midnight
    if last_t < entries[0].time:
        last_dt = datetime.datetime.combine(next_day, last_t)
    else:
        last_dt = datetime.datetime.combine(base, last_t)
    delta = last_dt - first_dt
    return delta.total_seconds()
