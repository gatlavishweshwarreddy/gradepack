from order import Order
from pricer import apply_bulk_discount
from tax import calculate_tax


def process(order):
    """
    BUG 2: tax applied to original subtotal, not discounted total.
    """
    subtotal = order.total()
    discounted = apply_bulk_discount(subtotal)
    # BUG: should be calculate_tax(discounted), not calculate_tax(subtotal)
    return round(discounted + calculate_tax(subtotal), 2)
