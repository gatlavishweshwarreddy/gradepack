import heapq


class Graph:
    def __init__(self):
        self._adj = {}

    def add_edge(self, u, v, weight):
        self._adj.setdefault(u, []).append((v, weight))
        self._adj.setdefault(v, [])

    def shortest_path(self, source, target):
        dist = {source: 0.0}
        pq = [(0.0, source)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, float('inf')):
                continue
            if u == target:
                return d
            for v, w in self._adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, float('inf')):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return None
