import heapq

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}

class FakeClock:
    """Deterministic clock for testing."""
    def __init__(self, start=0.0):
        self._t = float(start)

    def now(self):
        return self._t

    def advance(self, dt):
        if dt < 0:
            raise ValueError("cannot go backwards")
        self._t += float(dt)


class TokenBucket:
    """
    Token bucket rate limiter.
    rate: tokens per second
    burst: max tokens
    Tokens refill continuously. Each task start consumes 1 token.
    """
    def __init__(self, rate, burst, clock):
        self.rate = float(rate)
        self.burst = int(burst)
        self.clock = clock
        self.tokens = float(burst)
        self.last_refill = clock.now()

    def _refill(self):
        now = self.clock.now()
        elapsed = now - self.last_refill
        if elapsed <= 0:
            return
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def try_consume(self, n=1):
        self._refill()
        if self.tokens >= n - 1e-9:
            self.tokens -= n
            return True
        return False

    def time_until_next_token(self):
        self._refill()
        if self.tokens >= 1 - 1e-9:
            return 0.0
        return (1 - self.tokens) / self.rate


class Task:
    def __init__(self, task_id, fn, priority, dependencies, duration, seq):
        self.task_id = task_id
        self.fn = fn
        self.priority = priority
        self.dependencies = dependencies or []
        self.duration = float(duration)
        self.seq = seq
        self.status = "PENDING"
        self.result = None
        self.error = None
        self.start_time = None
        self.end_time = None


class Scheduler:
    """
    Workflow scheduler with:
    - max_concurrent: max RUNNING tasks at once
    - bucket: TokenBucket for rate limiting (1 token per task start)
    - clock: FakeClock
    - priority: lower number