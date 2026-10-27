"""
Scheduler with resource caps, rate limits, priorities and failure propagation.

Contract (read carefully — grader checks these invariants):
- States: PENDING -> READY -> RUNNING -> COMPLETED
                \-> FAILED (if any dependency FAILED/CANCELLED)
                \-> CANCELLED (via cancel(); only PENDING/READY may be cancelled)
  RUNNING is non-cancellable. FAILED/CANCELLED/COMPLETED are terminal.
  FAILED propagates transitively: if a dependency fails/cancels, dependents
  that are PENDING or READY become FAILED (never run).

- Resources: global caps per resource type (e.g. cpu, mem). Sum of resources
  of all RUNNING tasks must never exceed caps. Acquire atomically on start,
  release on completion.

- Rate limit: at most max_starts_per_tick tasks may transition READY->RUNNING
  per tick() call.

- Priority: among READY tasks, start in priority order (lower int = higher
  priority), FIFO tie-break by insertion order.

- Performance: tick() must be amortized O(ready + completions) not O(N^2).
  Grader instruments _dependencies_met call count.

Duration is in ticks. A task started at tick T with duration D completes at
the end of tick T+D (remaining decremented each tick).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import heapq  # intentionally unused in buggy version


@dataclass
class Task:
    id: str
    priority: int = 10
    resources: Dict[str, int] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    duration: int = 1
    remaining: int = field(init=False)

    def __post_init__(self):
        self.remaining = self.duration


class Scheduler:
    def __init__(self, resource_limits: Dict[str, int], max_starts_per_tick: int = 2):
        """
        :param resource_limits: global caps, e.g. {"cpu": 2, "mem": 4}
        :param max_starts_per_tick: max READY->RUNNING per tick()
        """
        self.resource_limits = dict(resource_limits)
        self.max_starts_per_tick = max_starts_per_tick
        self.tasks: Dict[str, Task] = {}
        self.states: Dict[str, str] = {}
        self.insertion_order: Dict[str, int] = {}
        self._next_order = 0
        self.resource_used: Dict[str, int] = {k: 0 for k in self.resource_limits}
        self.time = 0
        # for instrumentation / debugging
        self._check_count = 0

    # ---------- public API ----------
    def add_task(self, task: Task):
        if task.id in self.tasks:
            raise ValueError(f"duplicate task {task.id}")
        # copy to avoid external mutation
        t = Task(
            id=task.id,
            priority=task.priority,
            resources=dict(task.resources),
            dependencies=list(task.dependencies),
            duration=task.duration,
        )
        self.tasks[t.id] = t
        self.states[t.id] = "PENDING"
        self.insertion_order[t.id] = self._next_order
        self._next_order += 1

    def get_state(self, task_id: str) -> Optional[str]:
        return self.states.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """
        Cancel a task. Only PENDING or READY may be cancelled.
        RUNNING is non-cancellable (must return False and not affect resources).
        Returns True if cancelled, False otherwise.
        """
        if task_id not in self.states:
            return False
        state = self.states[task_id]
        # BUG: allows RUNNING to be cancelled
        if state in ("PENDING", "READY", "RUNNING"):
            # BUG: if RUNNING, this incorrectly releases resources that are still in use
            # and marks as CANCELLED
            if state == "RUNNING":
                self._release_resources(self.tasks[task_id])
            self.states[task_id] = "CANCELLED"
            return True
        return False

    def tick(self) -> List[str]:
        """
        Advance one tick. Returns list of task ids that completed this tick.
        Must enforce: completions -> failure propagation -> promotion PENDING->READY
        -> start up to max_starts_per_tick in priority order respecting resource caps.
        """
        self.time += 1
        completed: List[str] = []

        # 1) decrement RUNNING and collect completions
        for tid, task in list(self.tasks.items()):
            if self.states[tid] == "RUNNING":
                task.remaining -= 1
                if task.remaining <= 0:
                    self.states[tid] = "COMPLETED"
                    self._release_resources(task)
                    completed.append(tid)

        # 2) failure propagation: PENDING -> FAILED if any dep FAILED
        # BUG: only checks FAILED, not CANCELLED, and only checks PENDING (not READY)
        for tid in list(self.tasks.keys()):
            if self.states[tid] == "PENDING":
                for dep in self.tasks[tid].dependencies:
                    if dep in self.states and self.states[dep] == "FAILED":
                        self.states[tid] = "FAILED"
                        break

        # 3) promote PENDING -> READY where dependencies met (inefficient O(N^2) scan)
        # BUG: performance - scans all tasks and for each does full dependency check
        # and also re-checks already READY tasks via same path
        ready: List[str] = []
        for tid in self.tasks:
            if self.states[tid] == "PENDING":
                if self._dependencies_met(tid):
                    self.states[tid] = "READY"
                    ready.append(tid)
            elif self.states[tid] == "READY":
                ready.append(tid)

        # 4) start READY tasks respecting priority and rate limit and resource caps
        # BUG: priority reversed (higher number first)
        # BUG: resource check only looks at first resource type
        # BUG: off-by-one on rate limit (allows max+1)
        ready.sort(key=lambda tid: self.tasks[tid].priority, reverse=True)

        started = 0
        for tid in ready:
            if started > self.max_starts_per_tick:  # BUG: should be >=
                break
            if self._can_acquire(self.tasks[tid]):
                self._acquire_resources(self.tasks[tid])
                self.states[tid] = "RUNNING"
                started += 1

        return completed

    def run_until_complete(self, max_ticks: int = 1000) -> int:
        ticks = 0
        while ticks < max_ticks:
            # check if all terminal
            if all(s in ("COMPLETED", "FAILED", "CANCELLED") for s in self.states.values()):
                break
            self.tick()
            ticks += 1
        return ticks

    # ---------- internal helpers ----------
    def _dependencies_met(self, task_id: str) -> bool:
        """Check if all dependencies are COMPLETED."""
        self._check_count += 1
        task = self.tasks[task_id]
        for dep in task.dependencies:
            if dep not in self.states:
                return False
            if self.states[dep] != "COMPLETED":
                return False
        return True

    def _can_acquire(self, task: Task) -> bool:
        # BUG: only checks first resource type, ignores others
        if not task.resources:
            return True
        first_key = next(iter(task.resources))
        need = task.resources[first_key]
        cap = self.resource_limits.get(first_key, 0)
        used = self.resource_used.get(first_key, 0)
        if used + need > cap:
            return False
        return True

    def _acquire_resources(self, task: Task):
        for k, v in task.resources.items():
            self.resource_used[k] = self.resource_used.get(k, 0) + v

    def _release_resources(self, task: Task):
        for k, v in task.resources.items():
            self.resource_used[k] = self.resource_used.get(k, 0) - v
            if self.resource_used[k] < 0:
                self.resource_used[k] = 0