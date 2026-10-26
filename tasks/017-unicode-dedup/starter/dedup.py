def dedup(strings: list[str]) -> list[str]:
    """Return strings with duplicates removed, preserving first occurrence."""
    seen = set()
    result = []
    for s in strings:
        # BUG: compares raw strings, misses NFD/NFC equivalents
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result
