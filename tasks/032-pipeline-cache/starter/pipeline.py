from cache import ResultCache


class Pipeline:
    def __init__(self, transforms):
        self._transforms = transforms
        self._cache = ResultCache()

    def run(self, data):
        result = data
        for t in self._transforms:
            # BUG: cache key is `(t.name, id(data))` — id() is reused
            # after the list is mutated, so a mutated list with the same
            # id() as a previous list returns stale cached results.
            key = (t.name, id(result))
            if self._cache.has(key):
                result = self._cache.get(key)
            else:
                result = t.apply(result)
                self._cache.set(key, result)
        return result
