"""
WorkflowEngine - deterministic tick-based workflow engine (correct implementation).
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
                step = wf["steps"][sid]
                if step["ready_at"] <= self.time:
                    step["state"] = "READY"

    def cancel(self, wf_id):
        wf = self.workflows.get(wf_id)
        if not wf or wf["state"] not in ("RUNNING", "PENDING"):
            return
        wf["cancel_requested"] = True
        has_running = any(s["state"] == "RUNNING" for s in wf["steps"].values())
        for step in wf["steps"].values():
            if step["state"] in ("PENDING", "READY"):
                step["state"] = "CANCELLED"
        if not has_running:
            wf["state"] = "CANCELLED"
        # else remain RUNNING until _update_workflow_states transitions

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
            self.buckets[group] = min(cap, self.buckets[group] + refill)

    def _handle_timeouts(self):
        for wf in self.workflows.values():
            for step in wf["steps"].values():
                if step["state"] != "RUNNING":
                    continue
                elapsed = self.time - step["start_tick"]
                if elapsed > step["timeout"]:
                    step["attempts"] += 1
                    if step["attempts"] <= step["retries"]:
                        step["state"] = "PENDING"
                        step["ready_at"] = self.time + (2 ** step["attempts"])
                        step["start_tick"] = None
                    else:
                        step["state"] = "FAILED"
                        wf["state"] = "FAILED"
                        for s in wf["steps"].values():
                            if s["state"] in ("PENDING", "READY"):
                                s["state"] = "CANCELLED"

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
                        for s in wf["steps"].values():
                            if s["state"] in ("PENDING", "READY"):
                                s["state"] = "CANCELLED"
                    continue
                step["state"] = "COMPLETED"
                step["start_tick"] = None
                for dep_id in wf["adj"].get(step["id"], []):
                    wf["indegree"][dep_id] -= 1
                    self._check_count += 1

    def _promote_pending_to_ready(self):
        for wf in self.workflows.values():
            if wf["state"] not in ("RUNNING",):
                continue
            if wf["cancel_requested"]:
                continue
            if wf["state"] == "FAILED":
                continue
            for step in wf["steps"].values():
                if step["state"] != "PENDING":
                    continue
                if step["ready_at"] > self.time:
                    continue
                if wf["indegree"][step["id"]] == 0