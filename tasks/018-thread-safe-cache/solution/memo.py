import threading


def memoize(fn):
    """
    Cache results of fn with a correct check-then-act pattern:
      1. Check cache under lock.
      2. Release lock, compute fn(*args).
      3. Re-acquire lock; if another thread already stored the result, return that.
         Otherwise store and return.
    """
    cache = {}
    lock = threading.Lock()

    def wrapper(*args):
        with lock:
            if args in cache:
                return cache[args]
        # Compute outside the lock (allows concurrency for different keys).
        result = fn(*args)
        with lock:
            if args in cache:
                return cache[args]   # another thread beat us
            cache[args] = result
        return result

    return wrapper
