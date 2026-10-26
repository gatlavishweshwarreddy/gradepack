class TokenBucket:
    def __init__(self, rate, capacity):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last = None

    def consume(self, n, now):
        if self._last is not None:
            elapsed = now - self._last
            # BUG 1: no cap at capacity
            self._tokens += elapsed * self.rate
        # BUG 2: _last updated even on failure, but also not updated on failure path below
        self._last = now
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False
