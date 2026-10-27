import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from graph import Graph
import pytest
import random


def _ref_dijkstra(edges, source, target):
    """Reference implementation using correct relaxation."""
    import heapq
    adj = {}
    for u, v, w in edges:
        adj.setdefault(u, []).append((v, w))
        adj.setdefault(v, [])
    dist = {source: 0.0}
    pq = [(0.0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float('inf')):
            continue
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float('inf')):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist.get(target)


def test_triangle_shorter_indirect():
    g = Graph()
    g.add_edge('A', 'B', 10)
    g.add_edge('A', 'C', 1)
    g.add_edge('C', 'B', 2)
    assert g.shortest_path('A', 'B') == 3.0


def test_direct_edge():
    g = Graph()
    g.add_edge('X', 'Y', 5)
    assert g.shortest_path('X', 'Y') == 5.0


def test_unreachable():
    g = Graph()
    g.add_edge('A', 'B', 1)
    assert g.shortest_path('A', 'C') is None


def test_longer_chain():
    g = Graph()
    g.add_edge('A', 'B', 10)
    g.add_edge('A', 'C', 2)
    g.add_edge('C', 'D', 2)
    g.add_edge('D', 'B', 2)
    assert g.shortest_path('A', 'B') == 6.0


@pytest.mark.parametrize("seed", [0, 1, 7, 42])
def test_random_graph_matches_reference(seed):
    rng = random.Random(seed)
    nodes = [str(i) for i in range(8)]
    edges = []
    for _ in range(16):
        u, v = rng.sample(nodes, 2)
        w = rng.uniform(1, 10)
        edges.append((u, v, w))
    g = Graph()
    for u, v, w in edges:
        g.add_edge(u, v, w)
    source, target = nodes[0], nodes[-1]
    result = g.shortest_path(source, target)
    expected = _ref_dijkstra(edges, source, target)
    assert result == pytest.approx(expected, abs=1e-6), (
        f"seed={seed}: got {result}, expected {expected}"
    )
