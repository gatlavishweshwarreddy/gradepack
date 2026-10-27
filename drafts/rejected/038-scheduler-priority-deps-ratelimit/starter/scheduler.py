"""
TaskScheduler — contract (read carefully):

- Each task has id (str), priority (int, higher = earlier), deps (list[str]), duration (int ticks, >=1).
- States: PENDING -> WAITING (has unmet deps) or READY (no deps) -> RUNNING -> COMPLETED
          Any WAITING/READY/PENDING -> CANCELLED via cancel() and transitive propagation.
          WAITING -> CANCELLED if any dependency is CANCELLED/FAILED.
          WAITING -> READY only when *all* dependencies are COMPLETED.
          RUNNING/COMPLETED/CANCELLED are terminal for cancellation purposes.

- Scheduling: each tick: refill token bucket, complete running tasks (remaining--), promote
  WAITING->READY, then start as many READY tasks as possible while tokens>0 and
  len(running)<max_concurrent, in priority order (higher first, tie-break by insertion seq).

- Rate limiting: token bucket with capacity and refill_per_tick. Start tokens=capacity.
  Each task start consumes 1 token. Tokens refill each tick: tokens = min(capacity, tokens + elapsed*refill).
  Must not allow burst beyond capacity.

- Dependency checks must be O(V+E): only dependents of a completed/cancelled task should be inspected,
  not a full scan each tick. Exposed as `dependency_checks` counter.

- Execution order and start_tick must be deterministic.
"""

import heapq
from collections import defaultdict

class Task:
    def __init__(self, task_id, priority, deps, duration, seq):
        self.task_id = task_id
        self.priority = priority
        self.deps = deps or []
        self.duration = duration
        self.seq = seq
        self.state = "PENDING"
        self.start_tick = None

class TaskScheduler:
    def __init__(self, rate_capacity=5, rate_refill_per_tick=1, max_concurrent=1):
        self.capacity = rate_capacity
        self.refill_rate = rate_refill_per_tick
        self.max_concurrent = max_concurrent
        self.tasks = {}
        self.reverse_deps = defaultdict(list)
        self.ready_heap = []
        self.seq_counter = 0
        self.current_tick = 0
        self.tokens = self.capacity
        self.last_refill_tick = 0
        self.dependency_checks = 0
        self.execution_order = []
        self.completion_order = []
        self._seq_map = {}

    def add_task(self, task_id: str, priority: int = 0, deps=None, duration: int = 1):
        if task_id in self.tasks:
            raise ValueError(f"duplicate task {task_id}")
        if duration < 1:
            raise ValueError("duration must be >=1")
        seq = self.seq_counter
        self.seq_counter += 1
        task = Task(task_id, priority, deps or [], duration, seq)
        self.tasks[task_id] = task
        self._seq_map[task_id] = seq
        for d in task.deps:
            self.reverse_deps[d].append(task_id)

    def get_state(self, task_id: str) -> str:
        return self.tasks[task_id].state

    def get_execution_order(self):
        return list(self.execution_order)

    def get_completion_order(self):
        return list(self.completion_order)

    def get_start_tick(self, task_id: str):
        return self.tasks[task_id].start_tick

    def cancel(self, task_id: str):
        if task_id not in self.tasks:
            return
        task = self.tasks[task_id]
        if task.state in ("COMPLETED", "CANCELLED", "FAILED"):
            return
        # BUG: only direct dependents, not transitive
        task.state = "CANCELLED"
        for other_id, other in self.tasks.items():
            if task_id in other.deps:
                if other.state in ("WAITING", "READY", "PENDING"):
                    other.state = "CANCELLED"

    def _refill(self):
        # BUG: no cap, always adds refill_rate regardless of elapsed, and wrong initial
        self.tokens += self.refill_rate
        self.last_refill_tick = self.current_tick

    def _refresh_ready_queue(self):
        # BUG: full scan every tick (O(V^2)) and uses `any` instead of `all`
        # BUG: heap key uses task_id lexicographic instead of seq
        for tid, task in self.tasks.items():
            if task.state == "WAITING":
                self.dependency_checks += 1
                # should be all(), but uses any()
                if any(self.tasks[d].state == "COMPLETED" for d in task.deps if d in self.tasks):
                    task.state = "READY"
                    heapq.heappush(self.ready_heap, (-task.priority, task.task_id, task))
                elif any(self.tasks[d].state in ("CANCELLED", "FAILED") for d in task.deps if d in self.tasks):
                    task.state = "CANCELLED"

    def _initialize_states(self):
        for task in self.tasks.values():
            if not task.deps:
                if task.state == "PENDING":
                    task.state = "READY"
                    heapq.heappush(self.ready_heap, (-task.priority, task.task_id, task))
            else:
                if task.state == "PENDING":
                    task.state = "WAITING"

    def run(self, max_ticks: int = 1000):
        self.current_tick = 0
        self.tokens = self.capacity
        self.last_refill_tick = 0
        self.execution_order = []
        self.completion_order = []
        self.ready_heap = []
        self.dependency_checks = 0

        self._initialize_states()

        running = []  # list of (task, remaining)

        for tick in range(max_ticks):
            self.current_tick = tick
            self._refill()

            # complete running tasks
            new_running = []
            for task, remaining in running:
                remaining -= 1
                if remaining <= 0:
                    task.state = "COMPLETED"
                    self.completion_order.append(task.task_id)
                else:
                    new_running.append((task, remaining))
            running = new_running

            # promote waiting -> ready (buggy full scan)
            self._refresh_ready_queue()

            # start new tasks while tokens and concurrency allow
            # BUG: allows tokens >=0 (one extra burst)
            while self.ready_heap and self.tokens >= 0 and len(running) < self.max_concurrent:
                _, _, task = heapq.heappop(self.ready_heap)
                if task.state != "READY":
                    continue
                task.state = "RUNNING"
                task.start_tick = tick
                self.tokens -= 1
                self.execution_order.append(task.task_id)
                running.append((task, task.duration))

            # termination: no running and no ready and no waiting that could be unblocked
            if not running and not self.ready_heap:
                waiting = [t for t in self.tasks.values() if t.state == "WAITING"]
                if not waiting:
                    break
                # if waiting exists but nothing running, deadlock -> break
                break

        return list(self.completion_order)

    def tick(self):
        # single tick helper not used in tests
        return self.run(max_ticks=self.current_tick+1)