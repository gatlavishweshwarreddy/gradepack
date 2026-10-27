class EventStore:
    def __init__(self):
        self._events = []

    def append(self, event):
        self._events.append(event)

    def replay(self, from_seq=0):
        """
        Return events with sequence >= from_seq in sequence order.
        BUG 1: uses > from_seq instead of >= from_seq (skips the boundary event).
        BUG 2: does not sort by sequence before returning.
        """
        return [e for e in self._events if e.sequence > from_seq]
