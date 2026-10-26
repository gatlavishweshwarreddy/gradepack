class Accumulator:
    def __init__(self, initial=None):
        self.items = list(initial) if initial is not None else []

    def add(self, value):
        self.items.append(value)
        return self

    def total(self):
        return sum(self.items)

    def values(self):
        return list(self.items)
