class SearchIndex:
    def __init__(self):
        self._docs = {}
        self._built = False
        self.comparison_count = 0

    def add(self, doc_id, text):
        self._docs[doc_id] = text.lower()
        self._built = False

    def build(self):
        # BUG: no inverted index built — search does a linear scan
        self._built = True

    def search(self, query):
        """Return doc_ids whose text contains query. BUG: O(N) scan per query."""
        q = query.lower()
        results = []
        for doc_id, text in self._docs.items():
            self.comparison_count += 1
            if q in text:
                results.append(doc_id)
        return results
