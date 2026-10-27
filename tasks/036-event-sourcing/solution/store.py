class EventStore:
    def __init__(self):
        self._events = []

    def append(self, event):
        self._events.append(event)

    def replay(self, from_seq=0):
        """Return events with sequence >= from_seq, sorted by sequence."""
        filtered = [e for e in self._events if e.sequence >= from_seq]
        return sorted(filtered, key=lambda e: e.sequence)
