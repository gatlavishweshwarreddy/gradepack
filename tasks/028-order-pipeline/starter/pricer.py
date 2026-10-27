def apply_bulk_discount(subtotal):
    """
    Apply bulk discount.
    BUG: wrong tier boundaries — uses > instead of >=, so subtotal==100 only
    gets 5% discount instead of 10%.
    """
    if subtotal > 100.0:
        return subtotal * 0.90
    elif subtotal > 50.0:
        return subtotal * 0.95
    return subtotal
