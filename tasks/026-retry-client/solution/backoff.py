def wait_seconds(attempt, base=1.0):
    """
    Return the backoff delay for attempt (1-indexed).
    attempt=1 → base, attempt=2 → base*2, attempt=3 → base*4.
    """
    return base * (2 ** (attempt - 1))
