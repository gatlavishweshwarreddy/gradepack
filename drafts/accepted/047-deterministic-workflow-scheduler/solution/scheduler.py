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
import heapq

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
        self._ready_heap = []
        self._remaining_deps = {}
        self._in_heap = set()

    def add_task(self, task):
        if task.id in self._tasks:
            raise ValueError(f"duplicate task id {task.id}")
        self._tasks[task.id] = task
        for dep in task.dependencies:
            self._dependents[dep].append(task.id)

        # Check if any dependency already FAILED/CANCELLED -> immediately cancel
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep is not None and dep.state in (Task.FAILED, Task.CANCELLED):
                self._cancel_transitive(task.id)
                return

        # Count remaining incomplete dependencies
        remaining = 0
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep is None or dep.state != Task.COMPLETED:
                remaining += 1
        self._remaining_deps[task.id] = remaining
        if remaining == 0 and task.state == Task.PENDING:
            self._push_ready(task)

    def _push_ready(self, task):
        if task.id not in self._in_heap and task.state == Task.PENDING:
            heapq.heappush(self._ready_heap, (task.priority, task.id, task.id))
            self._in_heap.add(task.id)

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

    def _cancel_transitive(self, root_id):
        q = deque([root_id])
        visited = set()
        while q:
            cur_id = q.popleft()
            if cur_id in visited:
                continue
            visited.add(cur_id)
            cur = self._tasks.get(cur_id)
            if cur is None:
                continue
            if cur.state == Task.PENDING:
                cur.state = Task.CANCELLED
                # remove from heap tracking if present (lazy, will skip on pop)
                # but also need to ensure remaining_deps not used
            # propagate to dependents if cur is now FAILED/CANCELLED
            # For initial call, we propagate regardless; for dependents, only if they are PENDING
            for dep_id in self._dependents.get(cur_id, []):
                dep_task = self._tasks.get(dep_id)
                if dep_task and dep_task.state == Task.PENDING:
                    q.append(dep_id)

    def tick(self):
        started = []
        # temp list for tasks that didn't fit resources
        skipped = []
        while self._ready_heap and self._running_count < self.max_concurrency:
            # peek ordering is already priority, id
            # we need to iterate in order; heap pop gives smallest
            # But we need to handle skipping: pop all, try to start, collect skipped
            # For maximal behavior, we need to consider all ready tasks in order
            # So drain heap into sorted list, then try each
            break

        # Drain heap into list in order
        ready_ordered = []
        temp_heap = []
        while self._ready_heap:
            pri, tid, _ = heapq.heappop(self._ready_heap)
            self._in_heap.discard(tid)
            t = self._tasks.get(tid)
            if t is None or t.state != Task.PENDING:
                continue
            # check still ready (remaining deps ==0)
            if self._remaining_deps.get(tid, 0) != 0:
                continue
            ready_ordered.append(t)

        # ready_ordered is already sorted by heap order (priority, id)
        for task in ready_ordered:
            if self._running_count >= self.max_concurrency:
                # no more concurrency, keep remaining for next tick
                skipped.append(task)
                continue
            if not self._check_resources(task):
                skipped.append(task)
                continue
            task.state = Task.RUNNING
            self._allocate_resources(task)
            self._running_count += 1
            started.append(task.id)

        # push back skipped tasks
        for t in skipped:
            self._push_ready(t)

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
        # update dependents
        for dep_id in self._dependents.get(task_id, []):
            if dep_id not in self._remaining_deps:
                continue
            # if dependent already cancelled/failed, skip
            dep_task = self._tasks.get(dep_id)
            if dep_task is None or dep_task.state != Task.PENDING:
                continue
            self._remaining_deps[dep_id] -= 1
            if self._remaining_deps[dep_id] == 0:
                # also ensure no failed/cancelled dependency (should have been cancelled already)
                self._push_ready(dep_task)
            elif self._remaining_deps[dep_id] < 0:
                self._remaining_deps[dep_id] = 0

    def fail(self, task_id):
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task {task_id}")
        if task.state != Task.RUNNING:
            raise ValueError(f"task {task_id} not RUNNING")
        self._release_resources(task)
        self._running_count -= 1
        task.state = Task.FAILED
        # transitively cancel dependents
        q = deque(self._dependents.get(task_id, []))
        visited = set()
        while q:
            cur_id = q.popleft()
            if cur_id in visited:
                continue
            visited.add(cur_id)
            cur = self._tasks.get(cur_id)
            if cur and cur.state == Task.PENDING:
                cur.state = Task.CANCELLED
                for nxt in self._dependents.get(cur_id, []):
                    nxt_task = self._tasks.get(nxt)
                    if nxt_task and nxt_task.state == Task.PENDING:
                        q.append(nxt)

    def cancel(self, task_id):
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task {task_id}")
        if task.state != Task.PENDING:
            return False
        # BFS transitive cancel
        q = deque([task_id])
        visited = set()
        while q:
            cur_id = q.popleft()
            if cur_id in visited:
                continue
            visited.add(cur_id)
            cur = self._tasks.get(cur_id)
            if cur and cur.state == Task.PENDING:
                cur.state = Task.CANCELLED
                for nxt in self._dependents.get(cur_id, []):
                    nxt_task = self._tasks.get(nxt)
                    if nxt_task and nxt_task.state == Task.PENDING:
                        q.append(nxt)
        return True

    def get_state(self, task_id):
        t = self._tasks.get(task_id)
        if t is None:
            raise ValueError(f"unknown task {task_id}")
        return t.state