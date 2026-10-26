def word_frequency(text):
    """Return a dict of word -> count."""
    counts = {}
    for word in text.split():
        counts[word] = counts.get(word, 0) + 1
    return counts
