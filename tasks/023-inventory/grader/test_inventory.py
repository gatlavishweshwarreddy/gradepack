import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from inventory import Inventory
import pytest
import random


def test_single_reserve_success():
    inv = Inventory()
    inv.add_stock("apple", 5)
    assert inv.reserve("apple", 3) is True


def test_single_reserve_failure_over_stock():
    inv = Inventory()
    inv.add_stock("apple", 2)
    assert inv.reserve("apple", 5) is False


def test_sequential_reservations_do_not_overbook():
    inv = Inventory()
    inv.add_stock("apple", 5)
    assert inv.reserve("apple", 3) is True
    assert inv.reserve("apple", 3) is False


def test_exact_stock_reserve():
    inv = Inventory()
    inv.add_stock("apple", 4)
    assert inv.reserve("apple", 4) is True
    assert inv.reserve("apple", 1) is False


def test_different_items_independent():
    inv = Inventory()
    inv.add_stock("apple", 3)
    inv.add_stock("banana", 3)
    assert inv.reserve("apple", 3) is True
    assert inv.reserve("banana", 3) is True


def test_total_reserved_never_exceeds_stock():
    rng = random.Random(42)
    inv = Inventory()
    stock = 10
    inv.add_stock("widget", stock)
    for _ in range(20):
        qty = rng.randint(1, 4)
        inv.reserve("widget", qty)
    total = inv.reservations().total_reserved("widget")
    assert total <= stock, f"Overbooked: {total} > {stock}"


def test_available_decreases_after_reserve():
    inv = Inventory()
    inv.add_stock("thing", 10)
    inv.reserve("thing", 4)
    assert inv.available("thing") == 6
