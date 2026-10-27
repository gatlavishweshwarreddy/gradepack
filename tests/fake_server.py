"""
tests/fake_server.py — local HTTP server imitating OpenAI-compatible /chat/completions.

The server reads the ``model`` field from the JSON request body to select behaviour.
Set BASE_URL to the server's base URL and MODEL to one of the mode names.

Modes (set as MODEL env var):
  normal              — content = corrected file in a fenced block
  reasoning           — content is null, text only in reasoning_content
  starter_path        — uses "starter/paginate.py" and "./paginate.py" as filename labels
  length_empty        — finish_reason "length", content is empty string
  length_retry        — first call: finish_reason "length" empty; second call: normal
  rate_limit          — HTTP 429 on first call, then normal on retry
  always_500          — always HTTP 500
  slow                — hangs for 60s (simulates timeout)
  probe_always_pass   — always returns correct solution (probe always passes → too_easy)
  probe_fail_once     — first call fails (wrong answer), subsequent calls pass (discriminating)
  probe_always_fail   — always returns wrong answer (all probes fail → discriminating)
"""
import http.server
import json
import socketserver
import threading
import time


# A minimal valid fix for task 001-pagination-off-by-one
_FIXED_PAGINATE = '''\
def paginate(items, page, per_page):
    """Return the items on a 1-indexed page."""
    total_pages = (len(items) + per_page - 1) // per_page
    if page < 1 or page > total_pages:
        return []
    start = (page - 1) * per_page
    return items[start:start + per_page]
'''


def _make_response(content, finish_reason="stop", reasoning_content=None):
    msg = {"role": "assistant", "content": content}
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    return {
        "id": "test-id",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # suppress output

    def do_POST(self):
        # Read request body
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length)
        try:
            req_data = json.loads(body_bytes)
        except Exception:
            req_data = {}

        mode = req_data.get("model", "normal")
        server_state = self.server.state  # type: ignore[attr-defined]

        if mode == "always_500":
            self._respond(500, b"Internal Server Error")
            return

        if mode == "rate_limit":
            count = server_state.setdefault("rate_limit_count", 0)
            server_state["rate_limit_count"] = count + 1
            if count == 0:
                # 429 with Retry-After header
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "0")
                payload = json.dumps({"error": "rate limited"}).encode()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            # Second call succeeds
            resp = _make_response(f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```")
            self._respond_json(resp)
            return

        if mode == "slow":
            time.sleep(60)
            resp = _make_response(f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```")
            self._respond_json(resp)
            return

        if mode == "reasoning":
            # content is null/absent, text only in reasoning_content
            resp = _make_response(
                content=None,
                reasoning_content=f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```",
            )
            self._respond_json(resp)
            return

        if mode == "length_empty":
            resp = _make_response(content="", finish_reason="length")
            self._respond_json(resp)
            return

        if mode == "length_retry":
            count = server_state.setdefault("length_retry_count", 0)
            server_state["length_retry_count"] = count + 1
            if count == 0:
                # First call: truncated with no usable content
                resp = _make_response(content="", finish_reason="length")
            else:
                # Retry call: normal answer
                resp = _make_response(f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```")
            self._respond_json(resp)
            return

        if mode == "starter_path":
            # filenames have directory prefixes that should be stripped
            resp = _make_response(
                f"starter/paginate.py\n```python\n{_FIXED_PAGINATE}\n```"
            )
            self._respond_json(resp)
            return

        # ── Agentic-specific modes ────────────────────────────────────────────

        if mode == "agentic_length_then_ok":
            # Turn 1 (call 1): length + empty content
            # Turn 1 retry (call 2): normal answer
            # Tests Fix 1 — intra-turn retry on length
            count = server_state.setdefault("aglen_count", 0)
            server_state["aglen_count"] = count + 1
            if count == 0:
                resp = _make_response(content="", finish_reason="length")
            else:
                resp = _make_response(
                    f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```"
                )
            self._respond_json(resp)
            return

        if mode == "agentic_invalid_then_ok":
            # Call 1: garbled (no fenced block) — triggers format correction
            # Call 2: normal answer after correction prompt
            # Tests Fix 2 — format-correction turn
            count = server_state.setdefault("aginv_count", 0)
            server_state["aginv_count"] = count + 1
            if count == 0:
                resp = _make_response("Here is my answer: sorry I forgot the fences.")
            else:
                resp = _make_response(
                    f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```"
                )
            self._respond_json(resp)
            return

        if mode == "agentic_exhaust":
            # Always garbled — all turns exhaust without solving
            # Tests Fix 3 — exhaustion of all turns
            resp = _make_response("I'm not sure how to format this, sorry.")
            self._respond_json(resp)
            return

        # ── Probe-specific modes ──────────────────────────────────────────────

        if mode == "probe_always_pass":
            # Always returns the correct fix — probe always passes → too_easy
            resp = _make_response(f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```")
            self._respond_json(resp)
            return

        if mode == "probe_fail_once":
            # Call 1: wrong answer (probe fails); call 2+: correct → discriminating
            count = server_state.setdefault("probe_fail_once_count", 0)
            server_state["probe_fail_once_count"] = count + 1
            if count == 0:
                # Return starter (broken) — will fail tests
                resp = _make_response(
                    "paginate.py\n```python\n"
                    "def paginate(items, page, per_page):\n"
                    "    total_pages = len(items) // per_page\n"
                    "    if page < 1 or page > total_pages:\n"
                    "        return []\n"
                    "    start = (page - 1) * per_page\n"
                    "    return items[start:start + per_page]\n"
                    "```"
                )
            else:
                resp = _make_response(f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```")
            self._respond_json(resp)
            return

        if mode == "probe_always_fail":
            # Always returns broken starter — all probes fail → discriminating
            resp = _make_response(
                "paginate.py\n```python\n"
                "def paginate(items, page, per_page):\n"
                "    total_pages = len(items) // per_page\n"
                "    if page < 1 or page > total_pages:\n"
                "        return []\n"
                "    start = (page - 1) * per_page\n"
                "    return items[start:start + per_page]\n"
                "```"
            )
            self._respond_json(resp)
            return

        # default: normal
        resp = _make_response(f"paginate.py\n```python\n{_FIXED_PAGINATE}\n```")
        self._respond_json(resp)

    def _respond_json(self, data: dict):
        payload = json.dumps(data).encode()
        self._respond(200, payload, content_type="application/json")

    def _respond(self, status: int, body: bytes, content_type: str = "text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeServer:
    """Context manager that starts a fake completions server on a random free port."""

    def __init__(self):
        self.server = None
        self.thread = None
        self.base_url = None

    def __enter__(self):
        self.server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
        self.server.state = {}  # shared mutable state for stateful modes
        port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        if self.server:
            self.server.shutdown()

    def reset(self):
        """Reset stateful counters between tests."""
        self.server.state = {}
