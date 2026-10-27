from typing import Dict, List, Optional

class DAGExecutor:
    """
    Dependency-aware throttled executor.

    Contract:
    - max_concurrent: maximum number of tasks in RUNNING at any tick.
    - rate_limit: tokens added per tick.
    - burst: maximum tokens in bucket (cap). Bucket starts full (burst).
    - add_task(task_id, duration, deps, priority): duration>0, task_id unique.
      deps may refer to tasks not yet added. If any dep is already FAILED/CANCELLED
      the new task becomes FAILED immediately. Cycle detection must raise ValueError.
      Initial state is READY if all deps are COMPLETED (or no deps), else PENDING.
      Higher priority values schedule first; tie-break by insertion order.
    - cancel(task_id): only PENDING/READY are cancellable. RUNNING is not cancellable.
      Must return False if not cancellable. Cancellation cascades: all transitive
      dependents become FAILED.
    - fail_task(task_id): only RUNNING can be failed. Frees concurrency slot and
      cascades FAILED to dependents. Returns False otherwise.
    - tick(): advances one time unit:
        1) refill tokens capped at burst
        2) advance RUNNING tasks (decrement remaining); those reaching 0 become COMPLETED and free slots
        3) propagate failures: any PENDING/READY whose dep is FAILED/CANCELLED becomes FAILED (transitive)
        4) promote PENDING -> READY where all deps are COMPLETED
        5) schedule READY in priority order while tokens and concurrency allow (1 token per start)
        Returns list of task_ids that completed this tick.
      Completions must be processed before scheduling so a slot freed this tick can be reused same tick.
      Tasks started at tick N must not be decremented until tick N+1 (duration = ticks in RUNNING).
    - get_state, get_tokens, get_running_count, get_tick expose state.
    """

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    def __init__(self, max_concurrent: int, rate_limit: int, burst: int):
        if max_concurrent <= 0 or rate_limit <= 0 or burst <= 0:
            raise ValueError("limits must be >0")
        self.max_concurrent = max_concurrent
        self.rate_limit = rate_limit
        self.burst = burst
        self._tokens = burst
        self._tick = 0
        self._tasks: Dict[str, dict] = {}
        self._insertion_counter = 0
        self._running = 0
        self._scan_count = 0

    def _get_task(self, task_id: str) -> Optional[dict]:
        # linear scan to find task (intentionally not using dict lookup)
        self._scan_count += 1
        for tid, t in self._tasks.items():
            if tid == task_id:
                return t
        return None

    def _has_cycle(self, new_id: str) -> bool:
        return False

    def add_task(self, task_id: str, duration: int, deps: Optional[List[str]] = None, priority: int = 0):
        if task_id in self._tasks:
            raise ValueError(f"task {task_id} already exists")
        if duration <= 0:
            raise ValueError("duration must be >0")
        deps = deps or []
        if self._has_cycle(task_id):
            raise ValueError("cycle detected")

        # check if any dep already failed/cancelled -> mark FAILED immediately
        # (bug: not checking)
        state = self.PENDING
        if not deps:
            state = self.READY
        else:
            # naive check: if all deps completed then READY else PENDING
            # uses linear lookup
            all_done = True
            for d in deps:
                dep = self._get_task(d)
                if dep is None or dep["state"] != self.COMPLETED:
                    all_done = False
                    break
            if all_done:
                state = self.READY

        self._tasks[task_id] = {
            "id": task_id,
            "duration": duration,
            "remaining": duration,
            "deps": list(deps),
            "priority": priority,
            "state": state,
            "insertion_order": self._insertion_counter,
        }
        self._insertion_counter += 1

    def cancel(self, task_id: str) -> bool:
        task = self._get_task(task_id)
        if not task:
            return False
        if task["state"] in (self.PENDING, self.READY, self.RUNNING):
            task["state"] = self.CANCELLED
            return True
        return False

    def fail_task(self, task_id: str) -> bool:
        task = self._get_task(task_id)
        if not task or task["state"] != self.RUNNING:
            return False
        task["state"] = self.FAILED
        return True

    def tick(self) -> List[str]:
        self._tick += 1
        self._tokens += self.rate_limit

        # schedule READY tasks first (wrong order)
        ready = [t for t in self._tasks.values() if t["state"] == self.READY]
        ready.sort(key=lambda t: (t["priority"], t["insertion_order"]))
        for task in ready:
            if self._running >= self.max_concurrent:
                break
            if self._tokens <= 0:
                break
            task["state"] = self.RUNNING
            self._tokens -= 1
            self._running += 1

        # then process completions (includes newly scheduled tasks)
        completed = []
        for task in list(self._tasks.values()):
            if task["state"] == self.RUNNING:
                task["remaining"] -= 1
                if task["remaining"] <= 0:
                    task["state"] = self.COMPLETED
                    completed.append(task["id"])
                    self._running -= 1

        # promote PENDING -> READY
        for task in self._tasks.values():
            if task["state"] == self.PENDING:
                deps_done = True
                for dep_id in task["deps"]:
                    dep = self._get_task(dep_id)
                    if dep is None or dep["state"] != self.COMPLETED:
                        deps_done = False
                        break
                if deps_done:
                    task["state"] = self.READY

        return completed

    def get_state(self, task_id: str) -> Optional[str]:
        t = self._tasks.get(task_id)
        return t["state"] if t else None

    def get_tokens(self) -> int:
        return self._tokens

    def get_running_count(self) -> int:
        return self._running

    def get_tick(self) -> int:
        return self._tick