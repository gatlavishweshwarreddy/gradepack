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
        return self._tasks.get(task_id)

    def _has_cycle(self, new_id: str, new_deps: List[str]) -> bool:
        # Build adjacency for DFS: edge from task -> its deps
        # Check if adding new_id with new_deps creates a cycle
        # We need to see if any dep can reach new_id via dependencies
        visited = set()
        stack = list(new_deps)
        while stack:
            cur = stack.pop()
            if cur == new_id:
                return True
            if cur in visited:
                continue
            visited.add(cur)
            cur_task = self._tasks.get(cur)
            if cur_task:
                stack.extend(cur_task["deps"])
        return False

    def _cascade_failed(self, initial_ids: List[str]):
        # BFS to mark all transitive dependents as FAILED
        # Build reverse index on the fly
        queue = list(initial_ids)
        visited = set(queue)
        while queue:
            cur_id = queue.pop(0)
            for tid, task in self._tasks.items():
                if task["state"] in (self.PENDING, self.READY):
                    if cur_id in task["deps"]:
                        task["state"] = self.FAILED
                        if tid not in visited:
                            visited.add(tid)
                            queue.append(tid)

    def add_task(self, task_id: str, duration: int, deps: Optional[List[str]] = None, priority: int = 0):
        if task_id in self._tasks:
            raise ValueError(f"task {task_id} already exists")
        if duration <= 0:
            raise ValueError("duration must be >0")
        deps = deps or []
        if self._has_cycle(task_id, deps):
            raise ValueError("cycle detected")

        # immediate FAILED if any dep already FAILED/CANCELLED
        state = self.PENDING
        immediate_failed = False
        for d in deps:
            dep = self._tasks.get(d)
            if dep and dep["state"] in (self.FAILED, self.CANCELLED):
                immediate_failed = True
                break
        if immediate_failed:
            state = self.FAILED
        elif not deps:
            state = self.READY
        else:
            all_done = True
            for d in deps:
                dep = self._tasks.get(d)
                if dep is None or dep["state"] != self.COMPLETED:
                    all_done = False
                    break
            if all_done:
                state = self.READY
            else:
                state = self.PENDING

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
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task["state"] not in (self.PENDING, self.READY):
            return False
        task["state"] = self.CANCELLED
        self._cascade_failed([task_id])
        return True

    def fail_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task["state"] != self.RUNNING:
            return False
        task["state"] = self.FAILED
        self._running -= 1
        self._cascade_failed([task_id])
        return True

    def tick(self) -> List[str]:
        self._tick += 1
        self._tokens = min(self.burst, self._tokens + self.rate_limit)

        completed = []
        # 2) advance RUNNING tasks that were running at start of tick
        running_at_start = [t for t in self._tasks.values() if t["state"] == self.RUNNING]
        for task in running_at_start:
            task["remaining"] -= 1
            if task["remaining"] <= 0:
                task["state"] = self.COMPLETED
                completed.append(task["id"])
                self._running -= 1

        # 3) propagate failures transitively until stable
        changed = True
        while changed:
            changed = False
            for task in self._tasks.values():
                if task["state"] in (self.PENDING, self.READY):
                    for dep_id in task["deps"]:
                        dep = self._tasks.get(dep_id)
                        if dep and dep["state"] in (self.FAILED, self.CANCELLED):
                            task["state"] = self.FAILED
                            changed = True
                            break

        # 4) promote PENDING -> READY where all deps COMPLETED
        for task in self._tasks.values():
            if task["state"] == self.PENDING:
                if not task["deps"]:
                    task["state"] = self.READY
                else:
                    all_done = True
                    for dep_id in task["deps"]:
                        dep = self._tasks.get(dep_id)
                        if dep is None or dep["state"] != self.COMPLETED:
                            all_done = False
                            break
                    if all_done:
                        task["state"] = self.READY

        # 5) schedule READY in priority order
        ready = [t for t in self._tasks.values() if t["state"] == self.READY]
        ready.sort(key=lambda t: (-t["priority"], t["insertion_order"]))
        for task in ready:
            if self._running >= self.max_concurrent:
                break
            if self._tokens <= 0:
                break
            task["state"] = self.RUNNING
            self._tokens -= 1
            self._running += 1

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