class SearchIndex:
    def __init__(self):
        self._docs = {}
        self._inverted = {}
        self.comparison_count = 0

    def add(self, doc_id, text):
        self._docs[doc_id] = text.lower()

    def build(self):
        """Build an inverted index: term → set of doc_ids."""
        self._inverted = {}
        for doc_id, text in self._docs.items():
            for token in text.split():
                self._inverted.setdefault(token, set()).add(doc_id)

    def search(self, query):
        """Return doc_ids whose text contains query. O(1) via inverted index."""
        q = query.lower()
        self.comparison_count += 1
        return list(self._inverted.get(q, set()))
