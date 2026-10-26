import functools


def retry(max_attempts, exceptions=(Exception,)):
    """Decorator: retry the wrapped function on specified exceptions."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except BaseException:   # BUG 1: catches everything
                    attempt += 1
                    if attempt >= max_attempts + 1:  # BUG 2: allows extra attempt
                        raise
        return wrapper
    return decorator
