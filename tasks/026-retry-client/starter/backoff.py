def wait_seconds(attempt, base=1.0):
    """
    Return the backoff delay for a given attempt number (1-indexed).
    attempt=1 → base, attempt=2 → base*2, attempt=3 → base*4, etc.

    BUG: uses attempt instead of attempt-1 as the exponent, so:
    attempt=1 → base*2 (wrong, should be base*1)
    attempt=2 → base*4 (wrong, should be base*2)
    """
    return base * (2 ** attempt)
