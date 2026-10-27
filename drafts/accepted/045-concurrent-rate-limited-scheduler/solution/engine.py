"""
Concurrent Rate-Limited Scheduler - Workflow Engine

Invariants (normative):
1. TokenBucket: tokens must never exceed capacity. refill() adds refill_rate
   but caps at capacity. consume(n) only succeeds if enough tokens.
2. Scheduler concurrency: number of RUNNING tasks never exceeds max_concurrent.
3. State machine:
   PENDING -> READY -> RUNNING -> COMPLETED
                      -> CANCELLED (only from PENDING/READY)
                      -> FAILED (only from RUNNING)
   RUNNING tasks are NOT cancellable. cancel() on RUNNING must return False
   and leave state unchanged. COMPLETED/FAILED/CANCELLED are terminal.
4. Dependencies: task becomes READY only when ALL dependencies are COMPLETED.
   If any dependency is FAILED or CANCELLED, the dependent must NEVER become
   READY (permanently blocked). PENDING/RUNNING/READY dependencies also block.
5. Ordering: each tick(), after refill and promoting PENDING->READY, the
   scheduler starts as many READY tasks as possible (in priority order) while
   respecting concurrency and token availability. Higher priority value starts
   first; tie-break by lexicographic task_id ascending. Must be deterministic.
6. Performance: dependency promotion must be O(1) amortized per state change,
   not O(N) scan per tick. The grader instruments _is_dependency_met() calls;
   for a chain of N tasks completed one-by-one with tick() after each, total
   calls must be O(N), not O(N^2).

API:
  TokenBucket(capacity, refill_rate)
  Scheduler(max_concurrent, bucket)
    add_task(task_id, dependencies=None, priority=0)
    tick()  # refill, promote, then start tasks
    complete(task_id)  # RUNNING -> COMPLETED
    fail(task_id)      # RUNNING -> FAILED
    cancel(task_id) -> bool
    get_state(task_id) -> TaskState
    get_run_order() -> list[str]  # order tasks entered RUNNING
"""

from enum import Enum
from collections import defaultdict, deque


class TaskState(Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TokenBucket:
    def __init__(self, capacity, refill_rate):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity

    def consume(self, n=1):
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def refill(self):
        self.tokens = min(self.capacity, self.tokens + self.refill_rate)


class Task:
    def __init__(self, task_id, dependencies, priority):
        self.task_id = task_id
        self.dependencies = list(dependencies) if dependencies else []
        self.priority = priority
        self.state = TaskState.PENDING


class Scheduler:
    def __init__(self, max_concurrent, bucket):
        self.max_concurrent = max_concurrent
        self.bucket = bucket
        self.tasks = {}
        self._run_order = []
        # efficient tracking
        self._remaining_deps = {}  # task_id -> count of unmet dependencies
        self._dependents = defaultdict(list)  # dep_id -> [dependent_ids]
        self._blocked = set()  # tasks permanently blocked due to failed/cancelled dep
        self._ready_queue = deque()

    def add_task(self, task_id, dependencies=None, priority=0):
        if task_id in self.tasks:
            raise ValueError(f"duplicate task {task_id}")
        deps = dependencies or []
        for d in deps:
            if d not in self.tasks:
                raise ValueError(f"unknown dependency {d}")
        task = Task(task_id, deps, priority)
        self.tasks[task_id] = task

        # check if any dependency already terminal failed/cancelled -> blocked
        blocked = False
        unmet = 0
        for dep_id in deps:
            dep = self.tasks[dep_id]
            if dep.state in (TaskState.FAILED, TaskState.CANCELLED):
                blocked = True
            elif dep.state != TaskState.COMPLETED:
                unmet += 1
            # if COMPLETED, no unmet
            self._dependents[dep_id].append(task_id)

        if blocked:
            self._blocked.add(task_id)
            self._remaining_deps[task_id] = float('inf')
        else:
            self._remaining_deps[task_id] = unmet
            if unmet == 0:
                task.state = TaskState.READY

    def _is_dependency_met(self, dep_state):
        return dep_state == TaskState.COMPLETED

    def _dependencies_satisfied(self, task):
        for dep_id in task.dependencies:
            dep = self.tasks[dep_id]
            if not self._is_dependency_met(dep.state):
                return False
        return True

    def _update_ready_queue(self):
        # No-op in efficient version: promotion happens via _on_dependency_completed
        # and add_task. Kept for compatibility but does not scan.
        pass

    def _on_task_terminal(self, task_id, new_state):
        # if task failed/cancelled, block all transitive dependents
        if new_state in (TaskState.FAILED, TaskState.CANCELLED):
            queue = deque([task_id])
            visited = set()
            while queue:
                cur = queue.popleft()
                for dep_id in self._dependents.get(cur, []):
                    if dep_id in visited:
                        continue
                    visited.add(dep_id)
                    if dep_id not in self._blocked:
                        self._blocked.add(dep_id)
                        # ensure it never becomes ready
                        self._remaining_deps[dep_id] = float('inf')
                    queue.append(dep_id)
        elif new_state == TaskState.COMPLETED:
            for dep_id in self._dependents.get(task_id, []):
                if dep_id in self._blocked:
                    continue
                # decrement remaining deps if not already ready/running/completed
                if self._remaining_deps.get(dep_id, 0) > 0:
                    self._remaining_deps[dep_id] -= 1
                    if self._remaining_deps[dep_id] == 0:
                        t = self.tasks[dep_id]
                        if t.state == TaskState.PENDING:
                            t.state = TaskState.READY

    def _running_count(self):
        return sum(1 for t in self.tasks.values() if t.state == TaskState.RUNNING)

    def tick(self):
        self.bucket.refill()
        self._update_ready_queue()
        ready = [t for t in self.tasks.values() if t.state == TaskState.READY]
        ready.sort(key=lambda t: (-t.priority, t.task_id))
        for task in ready:
            if self._running_count() < self.max_concurrent:
                if self.bucket.consume(1):
                    task.state = TaskState.RUNNING
                    self._run_order.append(task.task_id)
                else:
                    break
            else:
                break

    def complete(self, task_id):
        task = self.tasks[task_id]
        if task.state != TaskState.RUNNING:
            raise ValueError(f"cannot complete {task_id} in state {task.state}")
        task.state = TaskState.COMPLETED
        self._on_task_terminal(task_id, TaskState.COMPLETED)

    def fail(self, task_id):
        task = self.tasks[task_id]
        if task.state != TaskState.RUNNING:
            raise ValueError(f"cannot fail {task_id} in state {task.state}")
        task.state = TaskState.FAILED
        self._on_task_terminal(task_id, TaskState.FAILED)

    def cancel(self, task_id):
        task = self.tasks[task_id]
        if task.state in (TaskState.PENDING, TaskState.READY):
            task.state = TaskState.CANCELLED
            self._on_task_terminal(task_id, TaskState.CANCELLED)
            return True
        return False

    def get_state(self, task_id):
        return self.tasks[task_id].state

    def get_run_order(self):
        return list(self._run_order)