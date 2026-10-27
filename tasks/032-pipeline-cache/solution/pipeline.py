from cache import ResultCache


class Pipeline:
    def __init__(self, transforms):
        self._transforms = transforms
        self._cache = ResultCache()

    def run(self, data):
        result = data
        for t in self._transforms:
            # Use tuple(result) as key so mutations are detected
            key = (t.name, tuple(result))
            if self._cache.has(key):
                result = self._cache.get(key)
            else:
                result = t.apply(result)
                self._cache.set(key, result)
        return result
