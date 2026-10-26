import os, sys, random
from decimal import Decimal, ROUND_HALF_UP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

import pytest
from ledger import Ledger


def _ref_balance(amounts):
    """Reference: sum using Decimal."""
    total = sum(Decimal(a) for a in amounts)
    return str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@pytest.mark.parametrize("amounts,expected", [
    (["0.10", "0.20"], "0.30"),
    (["0.10", "0.10", "0.10"], "0.30"),
    (["1.005"], "1.01"),        # rounds half-up at 2dp
    (["100.00", "-50.00"], "50.00"),
    (["0.01"] * 100, "1.00"),
])
def test_parametrized_exact(amounts, expected):
    ledger = Ledger()
    for a in amounts:
        ledger.add(a)
    assert ledger.balance() == expected


def test_invalid_amount_raises():
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.add("not-a-number")


def test_balance_format():
    """balance() must return exactly 2 decimal places."""
    ledger = Ledger()
    ledger.add("1")
    assert ledger.balance() == "1.00"


def test_initial_balance():
    ledger = Ledger(initial_balance="100.00")
    assert ledger.balance() == "100.00"


@pytest.mark.parametrize("seed", [0, 1, 13, 42, 99])
def test_seeded_random_cents(seed):
    rng = random.Random(seed)
    # Random cent amounts as strings to avoid float precision at generation time
    amounts = [f"{rng.randint(-100, 100)}.{rng.randint(0,99):02d}" for _ in range(20)]
    ledger = Ledger()
    for a in amounts:
        ledger.add(a)
    assert ledger.balance() == _ref_balance(amounts)
