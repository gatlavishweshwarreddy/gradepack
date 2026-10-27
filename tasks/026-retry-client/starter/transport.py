class Response:
    def __init__(self, status_code, body=""):
        self.status_code = status_code
        self.body = body


class FakeTransport:
    """Controllable test double for HTTP transport."""

    def __init__(self, responses):
        """responses: list of Response objects returned in order."""
        self._queue = list(responses)
        self.call_count = 0

    def request(self, url):
        self.call_count += 1
        if not self._queue:
            raise RuntimeError("FakeTransport: no more responses configured")
        return self._queue.pop(0)
