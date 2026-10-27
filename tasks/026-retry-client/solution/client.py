from transport import Response
from backoff import wait_seconds


_RETRYABLE = {500, 502, 503, 504}


class HttpClient:
    def __init__(self, transport, max_retries=3, backoff_base=1.0):
        self._transport = transport
        self._max_retries = max_retries
        self._base = backoff_base
        self._waits = []

    def get(self, url):
        for attempt in range(1, self._max_retries + 2):
            resp = self._transport.request(url)
            if resp.status_code not in _RETRYABLE:
                return resp
            if attempt <= self._max_retries:
                delay = wait_seconds(attempt, self._base)
                self._waits.append(delay)
        return resp
