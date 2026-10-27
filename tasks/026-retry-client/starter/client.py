from transport import Response
from backoff import wait_seconds


# Status codes that should trigger a retry
_RETRYABLE = {500, 502, 503, 504}


class HttpClient:
    def __init__(self, transport, max_retries=3, backoff_base=1.0):
        self._transport = transport
        self._max_retries = max_retries
        self._base = backoff_base
        self._waits = []  # record of wait_seconds calls for testing

    def get(self, url):
        """
        Call transport.request(url) and retry on transient errors.
        BUG: only retries on 500, not on 502/503/504.
        """
        retryable = {500}  # BUG: missing 502, 503, 504
        for attempt in range(1, self._max_retries + 2):
            resp = self._transport.request(url)
            if resp.status_code not in retryable:
                return resp
            if attempt <= self._max_retries:
                delay = wait_seconds(attempt, self._base)
                self._waits.append(delay)
        return resp
