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
from collections import defaultdict, deque

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
        if self.tasks[task_id].state in ("COMPLETED", "CANCELLED", "FAILED"):
            return
        # transitive BFS cancellation
        queue = deque([task_id])
        visited = set()
        while queue:
            cur = queue.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            if cur not in self.tasks:
                continue
            t = self.tasks[cur]
            if t.state in ("COMPLETED", "FAILED"):
                continue
            if t.state == "CANCELLED":
                # still need to propagate to dependents
                pass
            else:
                if t.state in ("PENDING", "WAITING", "READY", "RUNNING"):
                    t.state = "CANCELLED"
                else:
                    continue
            for dep_id in self.reverse_deps.get(cur, []):
                if dep_id not in visited:
                    dep_task = self.tasks.get(dep_id)
                    if dep_task and dep_task.state in ("PENDING", "WAITING", "READY"):
                        queue.append(dep_id)
                    elif dep_task and dep_task.state == "WAITING":
                        queue.append(dep_id)

    def _refill(self):
        elapsed = self.current_tick - self.last_refill_tick
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill_tick = self.current_tick

    def _on_task_completed(self, completed_id: str):
        # only check direct dependents - O(E) total
        for dep_id in self.reverse_deps.get(completed_id, []):
            dep_task = self.tasks.get(dep_id)
            if dep_task is None or dep_task.state != "WAITING":
                continue
            self.dependency_checks += 1
            # check if any dep cancelled/failed -> cancel this task
            has_cancelled = False
            for d in dep_task.deps:
                if d in self.tasks and self.tasks[d].state in ("CANCELLED", "FAILED"):
                    has_cancelled = True
                    break
            if has_cancelled:
                self.cancel(dep_id)
                continue
            # check if all deps completed
            all_done = True
            for d in dep_task.deps:
                if d not in self.tasks or self.tasks[d].state != "COMPLETED":
                    all_done = False
                    break
            if all_done:
                dep_task.state = "READY"
                heapq.heappush(self.ready_heap, (-dep_task.priority, dep_task.seq, dep_task))

    def _initialize_states(self):
        for task in self.tasks.values():
            if not task.deps:
                if task.state == "PENDING":
                    task.state = "READY"
                    heapq.heappush(self.ready_heap, (-task.priority, task.seq, task))
            else:
                if