import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from report import generate
import pytest
import random


def _make_records(n, seed):
    rng = random.Random(seed)
    regions = ["north", "south", "east", "west"]
    products = ["alpha", "beta", "gamma"]
    return [
        {
            "product": rng.choice(products),
            "region":  rng.choice(regions),
            "amount":  str(round(rng.uniform(1.0, 999.99), 2)),
        }
        for _ in range(n)
    ]


def _expected_total(records):
    return round(sum(float(r["amount"]) for r in records), 2)


@pytest.mark.parametrize("seed,n", [(0, 10), (1, 20), (42, 50), (7, 5)])
def test_grand_total_matches_sum(seed, n):
    records = _make_records(n, seed)
    result = generate(records)
    expected = _expected_total(records)
    assert abs(result["grand_total"] - expected) < 0.01, (
        f"seed={seed} n={n}: grand_total={result['grand_total']} expected={expected}"
    )


def test_by_region_keys_present():
    records = _make_records(10, 99)
    result = generate(records)
    assert "by_region" in result
    assert len(result["by_region"]) > 0


def test_by_product_keys_present():
    records = _make_records(10, 99)
    result = generate(records)
    assert "by_product" in result


def test_empty_input():
    result = generate([])
    assert result["grand_total"] == 0.0
