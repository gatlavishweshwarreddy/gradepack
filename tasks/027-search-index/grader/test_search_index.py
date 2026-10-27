import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from index import SearchIndex
import pytest


def _build_index(n):
    idx = SearchIndex()
    for i in range(n):
        idx.add(f"doc{i}", f"word{i} common token{i % 10}")
    idx.build()
    return idx


def test_search_finds_exact_match():
    idx = _build_index(5)
    results = idx.search("word2")
    assert "doc2" in results


def test_search_finds_common_term():
    idx = _build_index(20)
    results = idx.search("common")
    assert len(results) == 20


def test_search_returns_empty_for_missing():
    idx = _build_index(5)
    assert idx.search("nothere") == []


def test_search_is_case_insensitive():
    idx = SearchIndex()
    idx.add("d1", "Hello World")
    idx.build()
    assert "d1" in idx.search("hello")
    assert "d1" in idx.search("WORLD")


def test_search_comparison_count_is_sublinear_or_linear():
    n = 200
    idx = _build_index(n)
    idx.comparison_count = 0
    idx.search("word50")
    count = idx.comparison_count
    assert count <= 5, (
        f"search() made {count} comparisons for {n} docs — expected at most 5 "
        f"(use an inverted index for O(1) lookup, not a linear scan)."
    )


def test_search_comparison_count_for_common_term():
    n = 200
    idx = _build_index(n)
    idx.comparison_count = 0
    idx.search("common")
    count = idx.comparison_count
    assert count <= 5, (
        f"search() made {count} comparisons for {n} docs — expected at most 5."
    )
