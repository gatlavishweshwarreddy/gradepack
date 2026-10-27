import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from invoice import Invoice
import pytest


def _ref_total(lines, discount_rate, tax_rate):
    sub = sum(p * q for _, p, q in lines)
    discounted = sub * (1.0 - discount_rate)
    return round(discounted * (1.0 + tax_rate), 2)


def test_no_discount_no_tax():
    inv = Invoice()
    inv.add_line("Widget", 10.0, 3)
    assert inv.total(0.0) == 30.0


def test_tax_only():
    inv = Invoice()
    inv.add_line("Widget", 100.0, 1)
    assert inv.total(0.10) == 110.0


def test_discount_only():
    inv = Invoice()
    inv.add_line("Widget", 100.0, 1)
    inv.discount(0.20)
    assert inv.total(0.0) == 80.0


def test_discount_then_tax():
    inv = Invoice()
    inv.add_line("Widget", 100.0, 1)
    inv.discount(0.10)
    result = inv.total(0.10)
    expected = _ref_total([("Widget", 100.0, 1)], 0.10, 0.10)
    assert result == expected


def test_multiple_lines_with_discount_and_tax():
    inv = Invoice()
    inv.add_line("A", 50.0, 2)
    inv.add_line("B", 25.0, 4)
    inv.discount(0.15)
    result = inv.total(0.08)
    lines = [("A", 50.0, 2), ("B", 25.0, 4)]
    expected = _ref_total(lines, 0.15, 0.08)
    assert result == expected


@pytest.mark.parametrize("unit,qty,disc,tax", [
    (10.0, 5, 0.0, 0.0),
    (10.0, 5, 0.10, 0.0),
    (10.0, 5, 0.0, 0.10),
    (10.0, 5, 0.25, 0.20),
    (99.99, 1, 0.05, 0.07),
    (1.0, 100, 0.50, 0.15),
])
def test_parametrized_combinations(unit, qty, disc, tax):
    inv = Invoice()
    inv.add_line("Item", unit, qty)
    inv.discount(disc)
    result = inv.total(tax)
    expected = _ref_total([("Item", unit, qty)], disc, tax)
    assert result == expected
