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
        # BUG: applies discount savings as a subtraction and tax as an addition
        # on the original subtotal, rather than taxing the post-discount amount.
        # discount_amount = sub * discount_rate, tax_amount = sub * tax_rate
        discount_amount = sub * self._discount_rate
        tax_amount = sub * tax_rate
        return round(sub - discount_amount + tax_amount, 2)
