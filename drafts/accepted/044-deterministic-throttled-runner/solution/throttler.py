"""
Deterministic Throttled Runner - correct contract (implementation is buggy).

Contract:
- max_concurrent: at most this many RUNNING tasks
- token bucket: burst tokens initially, replenished at rps per second on tick(now), capped at burst
- tick(now) must be monotonic; replenishes tokens then starts as many PENDING tasks as possible
  respecting both token count (1 per task) and concurrency, in priority order (higher priority first,
  FIFO within same priority). Returns list of task_ids started. Tokens only consumed when a task actually starts.
- submit(task_id, fn, priority): deduplicates if task_id already PENDING or RUNNING (return False),
  otherwise creates PENDING (return True). Allows resubmit after terminal states (COMPLETED/FAILED/CANCELLED).
- cancel(task_id): only PENDING can be cancelled (return True), RUNNING cannot (return False). Terminal/unknown also False.
- complete(task_id, success): RUNNING -> COMPLETED if success else FAILED, frees concurrency slot. Raises ValueError if not RUNNING.
- get_state: returns PENDING/RUNNING/COMPLETED/FAILED/CANCELLED/UNKNOWN
- set_rate(rps, burst): updates rate and caps tokens to new burst
"""
import heapq

class ThrottledRunner:
    def __init__(self, max_concurrent: int, rps: float, burst: int):
        if max_concurrent <= 0 or rps <= 0 or burst <= 0:
            raise ValueError("invalid limits")
        self.max_concurrent = max_concurrent
        self.rps = rps
        self.burst = burst
        self._tokens = float(burst)
        self._last_tick = 0.0
        self._seq = 0
        self._tasks = {}
        self._pending = []
        self._running = set()

    def submit(self, task_id: str, fn=None, priority: int = 0) -> bool:
        existing = self._tasks.get(task_id)
        if existing and existing["state"] in ("PENDING", "RUNNING"):
            return False
        self._seq += 1
        self._tasks[task_id] = {"fn": fn, "priority": priority, "state": "PENDING", "seq": self._seq}
        heapq.heappush(self._pending, (-priority, self._seq, task_id))
        return True

    def cancel(self, task_id: str) -> bool:
        t = self._tasks.get(task_id)
        if not t or t["state"] != "PENDING":
            return False
        t["state"] = "CANCELLED"
        return True

    def tick(self, now: float) -> list[str]:
        if now < self._last_tick:
            raise ValueError("time must be monotonic")
        elapsed = now - self._last_tick
        self._tokens = min(float(self.burst), self._tokens + elapsed * self.rps)
        self._last_tick = now
        started = []
        while self._pending and self._tokens >= 1 and len(self._running) < self.max_concurrent:
            neg_prio, seq, tid = heapq.heappop(self._pending)
            info = self._tasks.get(tid)
            if not info or info["state"] != "PENDING" or info["seq"] != seq:
                continue
            info["state"] = "RUNNING"
            self._running.add(tid)
            self._tokens -= 1
            started.append(tid)
        return started

    def complete(self, task_id: str, success: bool = True) -> None:
        info = self._tasks.get(task_id)
        if not info or info["state"] != "RUNNING":
            raise ValueError(f"task {task_id} not running")
        info["state"] = "COMPLETED" if success else "FAILED"
        self._running.remove(task_id)

    def get_state(self, task_id: str) -> str:
        info = self._tasks.get(task_id)
        if not info:
            return "UNKNOWN"
        return info["state"]

    def set_rate(self, rps: float, burst: int) -> None:
        if rps <= 0 or burst <= 0:
            raise ValueError("invalid rate")
        self.rps = rps
        self.burst = burst
        if self._tokens > burst:
            self._tokens = float(burst)