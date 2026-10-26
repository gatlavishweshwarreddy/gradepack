import re


def word_frequency(text):
    """Return a dict of normalised word -> count."""
    counts = {}
    for word in text.split():
        word = re.sub(r"[^a-zA-Z0-9]", "", word).lower()
        if word:
            counts[word] = counts.get(word, 0) + 1
    return counts
