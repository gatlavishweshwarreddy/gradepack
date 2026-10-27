import threading
# workqueue.py (not queue.py — avoids shadowing stdlib queue)


class WorkQueue:
    def __init__(self):
        self._items = []
        self._lock = threading.Lock()
        self._done = False

    def put(self, item):
        with self._lock:
            self._items.append(item)

    def get(self):
        with self._lock:
            if self._items:
                return self._items.pop(0)
            return None

    def done(self):
        self._done = True

    def is_done(self):
        return self._done and not self._items
