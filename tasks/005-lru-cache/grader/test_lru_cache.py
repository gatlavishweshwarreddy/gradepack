import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from lru_cache import LRUCache


def test_get_miss():
    c = LRUCache(2)
    assert c.get(1) == -1


def test_put_and_get():
    c = LRUCache(2)
    c.put(1, 10)
    assert c.get(1) == 10


def test_evict_lru():
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    c.put(3, 3)  # evicts key 1
    assert c.get(1) == -1
    assert c.get(2) == 2
    assert c.get(3) == 3


def test_get_refreshes_recency():
    # put 1, put 2; get 1 (makes 2 LRU); put 3 => evicts 2, not 1
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    c.get(1)     # 1 is now MRU; 2 is LRU
    c.put(3, 3)  # should evict 2
    assert c.get(2) == -1
    assert c.get(1) == 1
    assert c.get(3) == 3


def test_update_existing():
    c = LRUCache(2)
    c.put(1, 1)
    c.put(1, 99)
    assert c.get(1) == 99
