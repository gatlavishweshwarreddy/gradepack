from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Set

class TaskState(Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

@dataclass
class Task:
    task_id: str
    dependencies: List[str]
    tokens_needed: int
    state: TaskState
    submission_order: int

class WorkflowOrchestrator:
    """
    Token-gated workflow orchestrator.

    State machine:
        PENDING -> READY -> RUNNING -> COMPLETED
                         -> RUNNING -> FAILED
        PENDING -> CANCELLED
        READY   -> CANCELLED
        RUNNING is non-cancellable (cancel must raise).

    Rules:
    - submit(task_id, dependencies, tokens_needed): creates task.
      dependencies must already exist else ValueError.
      tokens_needed > max_tokens => ValueError.
      Initial state is READY iff all dependencies are COMPLETED,
      otherwise PENDING. Empty dependencies => READY.
    - start(task_id): only READY -> RUNNING. Must enforce
      sum(RUNNING tokens) + tokens_needed <= max_tokens else RuntimeError.
    - complete(task_id): only RUNNING -> COMPLETED, releases tokens,
      promotes dependents whose *all* dependencies are COMPLETED.
    - fail(task_id): only RUNNING -> FAILED, releases tokens,
      does NOT promote dependents.
    - cancel(task_id): only PENDING or READY -> CANCELLED. Must raise
      RuntimeError for RUNNING/COMPLETED/FAILED/CANCELLED.
    - get_runnable_tasks(): returns READY tasks in submission order,
      greedily fitting within remaining token budget (remaining =
      max_tokens - running_tokens). Must be efficient: should not
      re-evaluate dependency graph on each call.
    - Token invariant: running_tokens == sum(tokens of RUNNING) <= max_tokens
    """

    def __init__(self, max_tokens: int = 10):
        self.max_tokens = max_tokens
        self.tasks: Dict[str, Task] = {}
        self.dependents: Dict[str, Set[str]] = {}
        self._order_counter = 0
        self.running_tokens = 0
        self._dependency_check_count = 0
        self.ready_set: Set[str] = set()

    def submit(self, task_id: str, dependencies=None, tokens_needed: int = 1):
        if task_id in self.tasks:
            raise ValueError(f"Task {task_id} already exists")
        if dependencies is None:
            dependencies = []
        if tokens_needed > self.max_tokens:
            raise ValueError("tokens_needed exceeds max_tokens")
        is_ready = True
        for dep in dependencies:
            if dep not in self.tasks:
                is_ready = False
                continue
            dep_task = self.tasks[dep]
            self._dependency_check_count += 1
            if dep_task.state != TaskState.COMPLETED:
                is_ready = False
        state = TaskState.READY if is_ready else TaskState.PENDING
        if not dependencies and is_ready:
            state = TaskState.READY
        task = Task(task_id, list(dependencies), tokens_needed, state, self._order_counter)
        self._order_counter += 1
        self.tasks[task_id] = task
        for dep in dependencies:
            self.dependents.setdefault(dep, set()).add(task_id)
        return task

    def start(self, task_id: str):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        task = self.tasks[task_id]
        if task.state != TaskState.READY:
            raise RuntimeError(f"Cannot start task in state {task.state}")
        task.state = TaskState.RUNNING
        self.running_tokens += task.tokens_needed
        self.ready_set.discard(task_id)

    def complete(self, task_id: str):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        task = self.tasks[task_id]
        if task.state != TaskState.RUNNING:
            raise RuntimeError(f"Cannot complete task in state {task.state}")
        task.state = TaskState.COMPLETED
        self.running_tokens -= task.tokens_needed
        self._promote_dependents(task_id)

    def fail(self, task_id: str):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        task = self.tasks[task_id]
        if task.state != TaskState.RUNNING:
            raise RuntimeError(f"Cannot fail task in state {task.state}")
        task.state = TaskState.FAILED
        self._promote_dependents(task_id)

    def cancel(self, task_id: str):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        task = self.tasks[task_id]
        if task.state not in (TaskState.PENDING, TaskState.READY, TaskState.RUNNING):
            raise RuntimeError(f"Cannot cancel task in state {task.state}")
        if task.state == TaskState.RUNNING:
            self.running_tokens -= task.tokens_needed
        self.ready_set.discard(task_id)
        task.state = TaskState.CANCELLED

    def get_state(self, task_id: str):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id].state

    def get_running_tokens(self):
        return self.running_tokens

    def get_runnable_tasks(self):
        runnable = []
        for tid, task in self.tasks.items():
            if task.state == TaskState.READY:
                for d in task.dependencies:
                    self._dependency_check_count += 1
                runnable.append(task)
        runnable.sort(key=lambda t: t.task_id)
        return [t.task_id for t in runnable]

    def _promote_dependents(self, completed_id: str):
        for dep_id in self.dependents.get(completed_id, set()):
            dep_task = self.tasks.get(dep_id)
            if dep_task is None or dep_task.state != TaskState.PENDING:
                continue
            ready = True
            for d in dep_task.dependencies:
                self._dependency_check_count += 1
                if d not in self.tasks:
                    ready = False
                    break
                ds = self.tasks[d].state
                if ds not in (TaskState.COMPLETED, TaskState.FAILED):
                    ready = False
                    break
            if ready:
                dep_task.state = TaskState.READY
                self.ready_set.add(dep_id)