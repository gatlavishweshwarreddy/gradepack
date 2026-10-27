"""
WorkflowEngine - deterministic tick-based workflow engine.

Contract (invariants that must hold):

- Token bucket per group: each group has (capacity, refill_per_tick).
  Tokens are refilled each tick to min(capacity, tokens+refill). Scheduling
  a step with a group consumes 1 token if available, otherwise the step
  stays READY. Tokens never exceed capacity.

- Max concurrency: at most max_concurrent steps in RUNNING at any time
  across all workflows.

- Dependencies: step becomes READY only when ALL its deps are COMPLETED.
  Steps with no deps are READY on start (subject to backoff). Dependents
  of a FAILED step never become READY.

- Ordering: among READY steps, schedule deterministically by
  (workflow_start_seq, step_insertion_order) FIFO. Must be stable.

- Cancellation: cancel(wf_id) marks workflow cancel_requested. PENDING/READY
  steps become CANCELLED immediately. RUNNING steps are non-cancellable and
  continue to completion. After all RUNNING finish, workflow becomes
  CANCELLED. If no RUNNING at cancel time, workflow is CANCELLED immediately.

- Failure: if a step fails and retries are exhausted, step -> FAILED,
  workflow -> FAILED, and all PENDING/READY steps in that workflow become
  CANCELLED. No further steps become READY.

- Retry: step with retries=n is retried up to n times. After failure with
  retries remaining, step goes to PENDING with ready_at = now + 2^attempt
  (attempt 1-indexed) ticks before it may become READY again.

- Timeout: if a step stays RUNNING for > timeout ticks (elapsed = now - start_tick),
  it is considered failed and retry logic applies. Timeout check happens before
  completion check each tick.

- Performance: dependency resolution must be O(E) total, not O(N^2) per tick.
  The grader instruments _check_count.

Public API: WorkflowEngine(max_concurrent, rate_limits), add_workflow,
start, cancel, tick, get_status, get_tokens
"""

class WorkflowEngine:
    def __init__(self, max_concurrent=2, rate_limits=None):
        self.time = 0
        self.max_concurrent = max_concurrent
        self.rate_limits = rate_limits or {}
        self.buckets = {g: cap for g, (cap, _) in self.rate_limits.items()}
        self.workflows = {}
        self._start_seq = 0
        self._check_count = 0

    def add_workflow(self, wf_id, steps):
        if wf_id in self.workflows:
            raise ValueError("workflow exists")
        steps_dict = {}
        adj = {}
        indegree = {}
        for idx, s in enumerate(steps):
            sid = s["id"]
            if sid in steps_dict:
                raise ValueError("duplicate step")
            deps = list(s.get("deps", []))
            steps_dict[sid] = {
                "id": sid,
                "deps": deps,
                "group": s.get("group"),
                "fn": s.get("fn"),
                "duration": s.get("duration", 1),
                "retries": s.get("retries", 0),
                "timeout": s.get("timeout", 5),
                "state": "PENDING",
                "attempts": 0,
                "start_tick": None,
                "ready_at": 0,
                "order": idx,
            }
            indegree[sid] = len(deps)
            adj[sid] = []
        for sid, step in steps_dict.items():
            for dep in step["deps"]:
                if dep not in steps_dict:
                    raise ValueError(f"unknown dep {dep}")
                adj[dep].append(sid)
        self.workflows[wf_id] = {
            "id": wf_id,
            "steps": steps_dict,
            "state": "PENDING",
            "start_seq": None,
            "cancel_requested": False,
            "adj": adj,
            "indegree": indegree,
        }

    def start(self, wf_id):
        wf = self.workflows[wf_id]
        if wf["state"] != "PENDING":
            raise ValueError("not pending")
        wf["state"] = "RUNNING"
        self._start_seq += 1
        wf["start_seq"] = self._start_seq
        for sid, deg in wf["indegree"].items():
            if deg == 0:
                wf["steps"][sid]["state"] = "READY"

    def cancel(self, wf_id):
        wf = self.workflows.get(wf_id)
        if not wf or wf["state"] not in ("RUNNING", "PENDING"):
            return
        wf["cancel_requested"] = True
        for step in wf["steps"].values():
            if step["state"] in ("PENDING", "READY", "RUNNING"):
                step["state"] = "CANCELLED"
        wf["state"] = "CANCELLED"

    def tick(self):
        self.time += 1
        self._refill_tokens()
        self._handle_timeouts()
        self._handle_completions()
        self._promote_pending_to_ready()
        self._schedule_ready()
        self._update_workflow_states()

    def _refill_tokens(self):
        for group, (cap, refill) in self.rate_limits.items():
            self.buckets[group] += refill

    def _handle_timeouts(self):
        for wf in self.workflows.values():
            for step in wf["steps"].values():
                if step["state"] != "RUNNING":
                    continue
                elapsed = self.time - step["start_tick"]
                if elapsed >= step["timeout"]:
                    step["attempts"] += 1
                    if step["attempts"] <= step["retries"]:
                        step["state"] = "PENDING"
                        step["ready_at"] = self.time + (2 ** step["attempts"])
                        step["start_tick"] = None
                    else:
                        step["state"] = "FAILED"
                        wf["state"] = "FAILED"

    def _handle_completions(self):
        for wf in self.workflows.values():
            for step in list(wf["steps"].values()):
                if step["state"] != "RUNNING":
                    continue
                elapsed = self.time - step["start_tick"]
                if elapsed < step["duration"]:
                    continue
                try:
                    if step["fn"]:
                        step["fn"]()
                except Exception:
                    step["attempts"] += 1
                    if step["attempts"] <= step["retries"]:
                        step["state"] = "PENDING"
                        step["ready_at"] = self.time + (2 ** step["attempts"])
                        step["start_tick"] = None
                    else:
                        step["state"] = "FAILED"
                        wf["state"] = "FAILED"
                    continue
                step["state"] = "COMPLETED"
                step["start_tick"] = None
                for dep_id in wf["adj"].get(step["id"], []):
                    wf["indegree"][dep_id] -= 1
                    self._check_count += 1

    def _promote_pending_to_ready(self):
        for wf in self.workflows.values():
            if wf["state"] != "RUNNING":
                continue
            for step in wf["steps"].values():
                if step["state"] != "PENDING":
                    continue
                ready = False
                if not step["deps"]:
                    ready = True
                else:
                    for dep_id in step["deps"]:
                        for s in wf["steps"].values():
                            self._check_count += 1
                            if s["id"] == dep_id and s["state"] == "COMPLETED":
                                ready = True
                                break
                        if ready:
                            break
                if ready:
                    step["state"] = "READY"

    def _schedule_ready(self):
        ready = []
        for wf in self.workflows.values():
            for step in wf["steps"].values():
                if step["state"] == "READY":
                    ready.append((wf, step))
        ready.sort(key=lambda x: x[1]["id"], reverse=True)
        running = sum(1 for wf in self.workflows.values() for s in wf["steps"].values() if s["state"] == "READY")
        for wf, step in ready:
            if running >= self.max_concurrent:
                break
            group = step.get("group")
            if group:
                if self.buckets[group] <= 0:
                    continue
                self.buckets[group] -= 1
            step["state"] = "RUNNING"
            step["start_tick"] = self.time
            running += 1

    def _update_workflow_states(self):
        for wf in self.workflows.values():
            if wf["state"] in ("FAILED", "CANCELLED", "COMPLETED"):
                continue
            all_completed = all(s["state"] == "COMPLETED" for s in wf["steps"].values())
            if all_completed:
                wf["state"] = "COMPLETED"

    def get_status(self, wf_id):
        wf = self.workflows[wf_id]
        return {
            "workflow": wf["state"],
            "steps": {sid: s["state"] for sid, s in wf["steps"].items()},
            "time": self.time,
        }

    def get_tokens(self, group):
        return self.buckets.get(group)