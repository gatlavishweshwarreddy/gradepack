"""
Workflow scheduler with deterministic ordering, resource caps, and cancellation.

Contract (intended semantics):
- Tasks have states: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED.
- A task is ready when it is PENDING and all dependencies are COMPLETED.
- If any dependency is FAILED or CANCELLED at add time or becomes FAILED/CANCELLED,
  the dependent must become CANCELLED transitively (if still PENDING).
- tick() starts ready tasks in order (priority asc, id asc) maximally:
  iterate ready tasks in order, start each if it fits within resource_caps and
  max_concurrency. If a task does not fit due to resources, skip it and try
  the next lower-priority task (do not block).
- max_concurrency is a hard cap on RUNNING tasks.
- Resource caps are per-resource: sum of RUNNING tasks' resources must not exceed caps.
- complete(task_id) and fail(task_id) require RUNNING state, release ALL resources,
  and free concurrency slot. fail() additionally cancels all transitive PENDING dependents.
- cancel(task_id) only cancels PENDING tasks (and their transitive PENDING dependents).
  RUNNING tasks are non-cancellable: cancel() returns False and has no effect.
  Returns True if cancelled, False otherwise.
- FAILED state is terminal and never overwritten.
- Performance: tick() must not scan all tasks to find ready ones. _is_ready should
  be called O(n) total, not O(n^2). Use incremental tracking (heap + remaining deps).
"""

from collections import defaultdict, deque

class Task:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    def __init__(self, id, priority=0, resources=None, dependencies=None):
        self.id = id
        self.priority = priority
        self.resources = resources or {}
        self.dependencies = dependencies or []
        self.state = Task.PENDING

    def __repr__(self):
        return f"Task(id={self.id}, pri={self.priority}, state={self.state})"


class Scheduler:
    """
    Scheduler manages tasks with dependencies, priorities, resource caps.

    Performance requirement: tick() must be efficient. Do not call _is_ready
    for every task on every tick. Maintain a heap of ready tasks and update
    incrementally when dependencies resolve.
    """

    def __init__(self, max_concurrency, resource_caps):
        self.max_concurrency = max_concurrency
        self.resource_caps = dict(resource_caps)
        self._tasks = {}
        self._dependents = defaultdict(list)
        self._used_resources = {k: 0 for k in self.resource_caps}
        self._running_count = 0

    def add_task(self, task):
        if task.id in self._tasks:
            raise ValueError(f"duplicate task id {task.id}")
        self._tasks[task.id] = task
        for dep in task.dependencies:
            self._dependents[dep].append(task.id)

    def _is_ready(self, task):
        if task.state != Task.PENDING:
            return False
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep is None or dep.state != Task.COMPLETED:
                return False
        return True

    def _check_resources(self, task):
        for r, cap in self.resource_caps.items():
            if r == "cpu":
                if self._used_resources.get(r, 0) + task.resources.get(r, 0) > cap:
                    return False
        return True

    def _allocate_resources(self, task):
        for r, v in task.resources.items():
            if r in self._used_resources:
                self._used_resources[r] += v

    def _release_resources(self, task):
        for r, v in task.resources.items():
            if r in self._used_resources:
                self._used_resources[r] -= v

    def tick(self):
        ready = []
        for t in self._tasks.values():
            if self._is_ready(t):
                ready.append(t)
        ready.sort(key=lambda t: (t.priority, t.id), reverse=True)
        started = []
        for task in ready:
            if self._running_count > self.max_concurrency:
                break
            if not self._check_resources(task):
                break
            task.state = Task.RUNNING
            self._allocate_resources(task)
            self._running_count += 1
            started.append(task.id)
        return started

    def complete(self, task_id):
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task {task_id}")
        if task.state != Task.RUNNING:
            raise ValueError(f"task {task_id} not RUNNING")
        self._release_resources(task)
        self._running_count -= 1
        task.state = Task.COMPLETED

    def fail(self, task_id):
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task {task_id}")
        if task.state != Task.RUNNING:
            raise ValueError(f"task {task_id} not RUNNING")
        self._used_resources["cpu"] -= task.resources.get("cpu", 0)
        self._running_count -= 1
        task.state = Task.FAILED
        for dep_id in self._dependents.get(task_id, []):
            dep = self._tasks.get(dep_id)
            if dep and dep.state == Task.PENDING:
                dep.state = Task.CANCELLED

    def cancel(self, task_id):
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task {task_id}")
        if task.state in (Task.PENDING, Task.RUNNING):
            task.state = Task.CANCELLED
            for dep_id in self._dependents.get(task_id, []):
                dep = self._tasks.get(dep_id)
                if dep and dep.state == Task.PENDING:
                    dep.state = Task.CANCELLED
            return True
        return False

    def get_state(self, task_id):
        t = self._tasks.get(task_id)
        if t is None:
            raise ValueError(f"unknown task {task_id}")
        return t.state