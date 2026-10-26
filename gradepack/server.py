"""
gradepack serve — lightweight read-only HTTP API.

Endpoints:
    GET /tasks           list all tasks (id, title, difficulty, prompt)
    GET /tasks/<id>      task detail with starter and grader file contents

Usage:
    python -m gradepack serve [--port N]
"""
import json
import pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer

from gradepack import core


def _task_summary(task_id: str) -> dict:
    meta = core.load_task_json(task_id)
    return {
        "id":         meta.get("id", task_id),
        "title":      meta.get("title", ""),
        "difficulty": meta.get("difficulty", ""),
        "prompt":     meta.get("prompt", ""),
    }


def _task_detail(task_id: str) -> dict | None:
    task_root = core.task_dir(task_id)
    if not task_root.exists():
        return None
    meta = core.load_task_json(task_id)

    def _read_dir(subdir: str) -> dict[str, str]:
        d = task_root / subdir
        if not d.exists():
            return {}
        return {
            p.name: p.read_text()
            for p in sorted(d.iterdir())
            if p.is_file()
        }

    return {
        "id":           meta.get("id", task_id),
        "title":        meta.get("title", ""),
        "difficulty":   meta.get("difficulty", ""),
        "prompt":       meta.get("prompt", ""),
        "starter_files": _read_dir("starter"),
        "grader_files":  _read_dir("grader"),
        # solution is intentionally omitted
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default access log
        pass

    def _send_json(self, code: int, data) -> None:
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/tasks":
            tasks = [_task_summary(tid) for tid in core.all_task_ids()]
            self._send_json(200, tasks)
        elif path.startswith("/tasks/"):
            task_id = path[len("/tasks/"):]
            detail = _task_detail(task_id)
            if detail is None:
                self._send_json(404, {"error": f"task '{task_id}' not found"})
            else:
                self._send_json(200, detail)
        else:
            self._send_json(404, {"error": "not found"})


def cmd_serve(port: int = 8000) -> None:
    server = HTTPServer(("", port), _Handler)
    print(f"gradepack HTTP server listening on http://localhost:{port}")
    print("  GET /tasks")
    print("  GET /tasks/<id>")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
