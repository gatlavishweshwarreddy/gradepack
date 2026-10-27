def filter_level(entries, level):
    """Return only entries whose level matches (case-sensitive)."""
    return [e for e in entries if e.level == level]
