def apply_bulk_discount(subtotal):
    if subtotal >= 100.0:
        return subtotal * 0.90
    elif subtotal >= 50.0:
        return subtotal * 0.95
    return subtotal
