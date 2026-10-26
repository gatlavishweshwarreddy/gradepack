import threading


def memoize(fn):
    """Cache results of fn. Thread-safe read, but write is outside the lock (BUG)."""
    cache = {}
    lock = threading.Lock()

    def wrapper(*args):
        with lock:
            if args in cache:
                return cache[args]
        # BUG: lock released before write — race window between check and store.
        # Additionally: uses id(args) as key instead of args, so cache never hits
        # on the second call (tuples with same content have different id each time).
        result = fn(*args)
        cache[id(args)] = result  # BUG: id(args) is never the same tuple
        return result

    return wrapper
