class TokenBucket:
    def __init__(self, rate, capacity):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last = None

    def consume(self, n, now):
        if self._last is not None:
            elapsed = now - self._last
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False
