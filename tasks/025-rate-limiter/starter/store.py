class RequestStore:
    """Stores per-key request timestamps."""

    def __init__(self):
        self._data = {}

    def add(self, key, timestamp):
        self._data.setdefault(key, []).append(timestamp)

    def get_since(self, key, since):
        """Return timestamps for key that are >= since."""
        return [t for t in self._data.get(key, []) if t >= since]

    def prune(self, key, since):
        """Remove timestamps older than since."""
        self._data[key] = self.get_since(key, since)
