class ReservationLog:
    def __init__(self):
        self._log = []

    def record(self, item, qty):
        self._log.append((item, qty))

    def total_reserved(self, item):
        return sum(q for i, q in self._log if i == item)

    def all_reservations(self):
        return list(self._log)
