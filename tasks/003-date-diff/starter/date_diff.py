from datetime import datetime


def days_between(d1, d2):
    """Return the number of days between two ISO date strings."""
    dt1 = datetime.fromisoformat(d1)
    dt2 = datetime.fromisoformat(d2)
    return (dt2 - dt1).days
