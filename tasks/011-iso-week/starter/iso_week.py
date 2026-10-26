from datetime import date


def iso_week(date_str):
    """Return (iso_year, week_number) for an ISO date string."""
    d = date.fromisoformat(date_str)
    # BUG: %Y is calendar year, %W is 0-indexed Monday week — both wrong for ISO
    return (int(d.strftime("%Y")), int(d.strftime("%W")))
