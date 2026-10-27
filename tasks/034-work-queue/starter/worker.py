class Worker:
    def __init__(self, queue, results):
        self._queue = queue
        self._results = results

    def run(self):
        while not self._queue.is_done():
            item = self._queue.get()
            if item is not None:
                self._results.append(item * 2)
