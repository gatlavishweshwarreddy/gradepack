from order import Order
from pricer import apply_bulk_discount
from tax import calculate_tax


def process(order):
    subtotal = order.total()
    discounted = apply_bulk_discount(subtotal)
    return round(discounted + calculate_tax(discounted), 2)
