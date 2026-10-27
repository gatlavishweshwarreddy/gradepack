import datetime


def duration_seconds(entries):
    """
    Return elapsed seconds between first and last entry.
    Returns 0 if fewer than 2 entries.
    BUG: uses datetime.time subtraction directly via datetime.datetime.combine
    with the same arbitrary date for both, so spans crossing midnight
    produce a negative or wrong result.
    """
    if len(entries) < 2:
        return 0
    base = datetime.date(2000, 1, 1)
    first = datetime.datetime.combine(base, entries[0].time)
    last = datetime.datetime.combine(base, entries[-1].time)
    delta = last - first
    return delta.total_seconds()
