import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from order import Order
from pipeline import process
import pytest


def _ref_process(subtotal):
    if subtotal >= 100.0:
        disc = subtotal * 0.90
    elif subtotal >= 50.0:
        disc = subtotal * 0.95
    else:
        disc = subtotal
    return round(disc * 1.08, 2)


@pytest.mark.parametrize("subtotal,expected", [
    (40.0,  round(40.0 * 1.08, 2)),
    (50.0,  round(50.0 * 0.95 * 1.08, 2)),
    (75.0,  round(75.0 * 0.95 * 1.08, 2)),
    (100.0, round(100.0 * 0.90 * 1.08, 2)),
    (150.0, round(150.0 * 0.90 * 1.08, 2)),
    (200.0, round(200.0 * 0.90 * 1.08, 2)),
])
def test_process_matches_reference(subtotal, expected):
    o = Order()
    o.add_item("X", subtotal, 1)
    result = process(o)
    assert result == expected, (
        f"subtotal={subtotal}: expected {expected}, got {result}"
    )


def test_no_discount_below_50():
    o = Order()
    o.add_item("A", 10.0, 3)  # subtotal=30
    assert process(o) == round(30.0 * 1.08, 2)


def test_multi_item_order():
    o = Order()
    o.add_item("A", 60.0, 1)
    o.add_item("B", 50.0, 1)
    result = process(o)
    expected = _ref_process(110.0)
    assert result == expected
