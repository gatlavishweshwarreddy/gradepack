import unicodedata


def dedup(strings: list[str]) -> list[str]:
    """Return strings with duplicates removed (NFC-normalised comparison)."""
    seen: set[str] = set()
    result: list[str] = []
    for s in strings:
        key = unicodedata.normalize("NFC", s)
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result
