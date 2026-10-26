from datetime import date


def days_between(d1, d2):
    """Return the absolute number of days between two ISO date strings."""
    dt1 = date.fromisoformat(d1)
    dt2 = date.fromisoformat(d2)
    return abs((dt2 - dt1).days)
