from reservation import ReservationLog


class Inventory:
    def __init__(self):
        self._stock = {}
        self._log = ReservationLog()

    def add_stock(self, item, qty):
        self._stock[item] = self._stock.get(item, 0) + qty

    def available(self, item):
        return self._stock.get(item, 0) - self._log.total_reserved(item)

    def reserve(self, item, qty):
        if self.available(item) >= qty:
            self._log.record(item, qty)
            return True
        return False

    def reservations(self):
        return self._log
