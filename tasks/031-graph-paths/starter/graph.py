import heapq


class Graph:
    def __init__(self):
        self._adj = {}

    def add_edge(self, u, v, weight):
        self._adj.setdefault(u, []).append((v, weight))
        self._adj.setdefault(v, [])  # ensure v is in graph

    def shortest_path(self, source, target):
        """
        Dijkstra's algorithm.
        BUG: skips relaxation when dist[neighbor] is already set (even if the
        new path is shorter), so it never improves on the first path found.
        """
        dist = {source: 0.0}
        pq = [(0.0, source)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == target:
                return d
            for v, w in self._adj.get(u, []):
                # BUG: should be `v not in dist or d + w < dist[v]`
                if v not in dist:
                    dist[v] = d + w
                    heapq.heappush(pq, (dist[v], v))
        return None
