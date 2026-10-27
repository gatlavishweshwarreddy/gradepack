from store import RequestStore


class RateLimiter:
    def __init__(self, max_requests, window_seconds):
        self._max = max_requests
        self._window = window_seconds
        self._store = RequestStore()

    def allow(self, key, now):
        """
        Return True and record the request if the key has made fewer than
        max_requests in the last window_seconds. Return False otherwise.

        BUG: uses <= self._max instead of < self._max, so max_requests+1
        requests are allowed within the window instead of max_requests.
        """
        since = now - self._window
        recent = self._store.get_since(key, since)
        if len(recent) <= self._max:
            self._store.add(key, now)
            return True
        return False
