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
        self.tokens += self.refill_rate


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

    def add_task(self, task_id, dependencies=None, priority=0):
        if task_id in self.tasks:
            raise ValueError(f"duplicate task {task_id}")
        deps = dependencies or []
        for d in deps:
            if d not in self.tasks:
                raise ValueError(f"unknown dependency {d}")
        self.tasks[task_id] = Task(task_id, deps, priority)

    def _is_dependency_met(self, dep_state):
        # helper for instrumentation; should return True only if dep is COMPLETED
        return dep_state != TaskState.PENDING and dep_state != TaskState.READY

    def _dependencies_satisfied(self, task):
        for dep_id in task.dependencies:
            dep = self.tasks[dep_id]
            if not self._is_dependency_met(dep.state):
                return False
        return True

    def _update_ready_queue(self):
        for task in self.tasks.values():
            if task.state == TaskState.PENDING:
                if self._dependencies_satisfied(task):
                    task.state = TaskState.READY

    def _running_count(self):
        return sum(1 for t in self.tasks.values() if t.state == TaskState.RUNNING)

    def tick(self):
        self.bucket.refill()
        self._update_ready_queue()
        ready = [t for t in self.tasks.values() if t.state == TaskState.READY]
        ready.sort(key=lambda t: (t.priority, t.task_id))
        for task in ready:
            if self._running_count() <= self.max_concurrent:
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

    def fail(self, task_id):
        task = self.tasks[task_id]
        if task.state != TaskState.RUNNING:
            raise ValueError(f"cannot fail {task_id} in state {task.state}")
        task.state = TaskState.FAILED

    def cancel(self, task_id):
        task = self.tasks[task_id]
        if task.state in (TaskState.PENDING, TaskState.READY, TaskState.RUNNING):
            task.state = TaskState.CANCELLED
            return True
        return False

    def get_state(self, task_id):
        return self.tasks[task_id].state

    def get_run_order(self):
        return list(self._run_order)