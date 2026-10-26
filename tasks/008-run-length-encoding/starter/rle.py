def encode(s):
    """Return run-length encoding as list of (char, count) tuples."""
    if not s:
        return []
    result = []
    for ch in s:
        result.append((ch, 1))
    return result


def decode(pairs):
    """Reconstruct string from (char, count) pairs."""
    return "".join(ch * (count - 1) for ch, count in pairs)
