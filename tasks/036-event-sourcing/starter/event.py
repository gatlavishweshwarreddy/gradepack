class Event:
    def __init__(self, sequence, type_, payload):
        self.sequence = sequence
        self.type = type_
        self.payload = payload

    def __repr__(self):
        return f"Event(seq={self.sequence}, type={self.type!r}, payload={self.payload!r})"
