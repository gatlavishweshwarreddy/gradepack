class Accumulator:
    # BUG: mutable default argument — shared across all instances
    def __init__(self, initial=[]):
        self.items = initial

    def add(self, value):
        self.items.append(value)
        return self

    def total(self):
        return sum(self.items)

    def values(self):
        return list(self.items)
