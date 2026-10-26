def encode(s):
    """Return run-length encoding as list of (char, count) tuples."""
    if not s:
        return []
    result = []
    for ch in s:
        if result and result[-1][0] == ch:
            result[-1] = (ch, result[-1][1] + 1)
        else:
            result.append((ch, 1))
    return result


def decode(pairs):
    """Reconstruct string from (char, count) pairs."""
    return "".join(ch * count for ch, count in pairs)
