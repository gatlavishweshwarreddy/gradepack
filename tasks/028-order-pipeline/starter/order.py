class Order:
    def __init__(self):
        self._items = []

    def add_item(self, name, price, qty):
        self._items.append((name, price, qty))

    def total(self):
        return sum(p * q for _, p, q in self._items)
