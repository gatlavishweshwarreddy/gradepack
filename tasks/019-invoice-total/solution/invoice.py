from tax import apply_tax
from discount import apply_discount


class Invoice:
    def __init__(self):
        self._lines = []
        self._discount_rate = 0.0

    def add_line(self, description, unit_price, quantity):
        self._lines.append((description, unit_price, quantity))

    def discount(self, rate):
        self._discount_rate = rate

    def subtotal(self):
        return sum(p * q for _, p, q in self._lines)

    def total(self, tax_rate=0.0):
        sub = self.subtotal()
        discounted = apply_discount(sub, self._discount_rate)
        return round(apply_tax(discounted, tax_rate), 2)
