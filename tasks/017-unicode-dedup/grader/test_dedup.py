import os, sys, random, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

import pytest
from dedup import dedup

# NFC 'café' and NFD 'café' look the same but differ in bytes
NFC_CAFE = "caf\u00e9"        # single composed character
NFD_CAFE = "cafe\u0301"       # base + combining accent


def _ref_dedup(strings):
    """Reference using NFC normalisation."""
    seen = set()
    result = []
    for s in strings:
        key = unicodedata.normalize("NFC", s)
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


def test_empty():
    assert dedup([]) == []


def test_no_duplicates():
    assert dedup(["a", "b", "c"]) == ["a", "b", "c"]


def test_ascii_duplicates():
    assert dedup(["a", "b", "a"]) == ["a", "b"]


def test_nfc_nfd_treated_as_duplicate():
    result = dedup([NFC_CAFE, NFD_CAFE])
    assert len(result) == 1, "NFC and NFD forms must be treated as duplicates"


def test_nfd_first_kept():
    """When NFD appears first it should be returned (original form preserved)."""
    result = dedup([NFD_CAFE, NFC_CAFE])
    assert result == [NFD_CAFE]


def test_mixed_list():
    result = dedup(["a", NFC_CAFE, "b", NFD_CAFE, "a"])
    assert result == ["a", NFC_CAFE, "b"]


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 123])
def test_seeded_random(seed):
    rng = random.Random(seed)
    pool = ["a", "b", NFC_CAFE, NFD_CAFE, "x", "y", NFC_CAFE, "b"]
    strings = [rng.choice(pool) for _ in range(20)]
    assert dedup(strings) == _ref_dedup(strings)
