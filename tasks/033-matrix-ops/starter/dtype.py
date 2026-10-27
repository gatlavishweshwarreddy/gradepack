def coerce_element(v):
    """
    Convert v to an appropriate numeric type.
    BUG: always converts to int, silently truncating fractional values.
    """
    try:
        return int(v)
    except (TypeError, ValueError):
        return float(v)
