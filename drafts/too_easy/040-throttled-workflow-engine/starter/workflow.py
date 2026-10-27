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
        # refill tokens based on elapsed time
        self.tokens += elapsed * self.rate
        self.last_refill = now

    def try_consume(self, n=1):
        self._refill()
        if self.tokens >= n - 1e-9:
            self.tokens -= n
            return True
        return False

    def time_until_next_token(self):
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
    - priority: lower number = higher priority, tie-break by submission order
    - dependencies: DAG, task can run only after all dependencies SUCCEEDED
    - cancellation: only PENDING or QUEUED can be cancelled
    - failure: task raising exception -> FAILED, dependents -> FAILED
    """
    def __init__(self, max_concurrent, bucket, clock):
        self.max_concurrent = max_concurrent
        self.bucket = bucket
        self.clock = clock
        self.tasks = {}
        self._ready_heap = []
        self._queued_ids = set()
        self._running = {}  # task_id -> completion_time
        self._seq_counter = 0

    def submit(self, task_id, fn, priority=0, dependencies=None, duration=0):
        if task_id in self.tasks:
            raise ValueError(f"duplicate task_id {task_id}")
        dependencies = dependencies or []
        seq = self._seq_counter
        self._seq_counter += 1
        task = Task(task_id, fn, priority, dependencies, duration, seq)
        self.tasks[task_id] = task
        # initial transition if no dependencies
        self._refresh_pending()
        self._enqueue_ready()
        return task

    def get_status(self, task_id):
        return self.tasks[task_id].status

    def get_result(self, task_id):
        return self.tasks[task_id].result

    def get_error(self, task_id):
        return self.tasks[task_id].error

    def cancel(self, task_id):
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        if task.status in ("PENDING", "QUEUED", "RUNNING"):
            task.status = "CANCELLED"
            # remove from ready heap if present (lazy removal, handled in start)
            return True
        return False

    def _refresh_pending(self):
        """Move PENDING tasks to QUEUED or FAILED based on dependencies."""
        for task in self.tasks.values():
            if task.status != "PENDING":
                continue
            if not task.dependencies:
                task.status = "QUEUED"
                continue
            # check dependency statuses
            dep_statuses = []
            for dep_id in task.dependencies:
                if dep_id not in self.tasks:
                    dep_statuses.append("PENDING")
                else:
                    dep_statuses.append(self.tasks[dep_id].status)
            # if any dependency failed, this task fails
            if any(s == "FAILED" for s in dep_statuses):
                task.status = "FAILED"
                task.error = RuntimeError(f"dependency failed for {task.task_id}")
                continue
            if all(s == "SUCCEEDED" for s in dep_statuses):
                task.status = "QUEUED"

    def _enqueue_ready(self):
        for task in self.tasks.values():
            if task.status == "QUEUED" and task.task_id not in self._queued_ids and task.task_id not in self._running:
                heapq.heappush(self._ready_heap, (task.priority, task.task_id, task.task_id))
                self._queued_ids.add(task.task_id)

    def _start_ready_tasks(self):
        started = 0
        while self._ready_heap and len(self._running) <= self.max_concurrent:
            # consume token first
            if not self.bucket.try_consume(1):
                break
            priority, _, task_id = heapq.heappop(self._ready_heap)
            self._queued_ids.remove(task_id)
            task = self.tasks[task_id]
            if task.status != "QUEUED":
                # was cancelled after enqueue, refund token? no, token already consumed
                continue
            task.status = "RUNNING"
            task.start_time = self.clock.now()
            completion_time = self.clock.now() + task.duration
            self._running[task_id] = completion_time
            started += 1
        return started

    def _complete_due_tasks(self):
        now = self.clock.now()
        due = [tid for tid, ct in self._running.items() if ct <= now + 1e-9]
        for tid in due:
            task = self.tasks[tid]
            del self._running[tid]
            try:
                result = task.fn()
                task.result = result
                task.status = "SUCCEEDED"
            except Exception as e:
                task.result = None
                task.status = "SUCCEEDED"
                task.error = e
            task.end_time = now

    def run_until_complete(self):
        self._refresh_pending()
        self._enqueue_ready()
        max_iter = 10000
        it = 0
        while it < max_iter:
            it += 1
            self._complete_due_tasks()
            self._refresh_pending()
            self._enqueue_ready()
            self._start_ready_tasks()

            if all(t.status in TERMINAL for t in self.tasks.values()):
                break
            if not self._running and not self._ready_heap:
                # check if any PENDING remain that could become ready later
                # if no running tasks, we are done or deadlocked
                break

            if self._running:
                next_completion = min(self._running.values())
                if self._ready_heap:
                    if len(self._running) >= self.max_concurrent:
                        self.clock.advance(next_completion - self.clock.now())
                    else:
                        dt = self.bucket.time_until_next_token()
                        token_time = self.clock.now() + dt
                        next_event = min(next_completion, token_time)
                        if next_event <= self.clock.now() + 1e-9:
                            next_event = next_completion
                        self.clock.advance(next_event - self.clock.now())
                else:
                    self.clock.advance(next_completion - self.clock.now())
            else:
                if self._ready_heap:
                    dt = self.bucket.time_until_next_token()
                    if dt > 1e-9:
                        self.clock.advance(dt)
                    else:
                        # avoid busy loop
                        break
                else:
                    break
        return