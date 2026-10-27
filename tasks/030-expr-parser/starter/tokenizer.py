def tokenize(expr):
    """Split expression into list of tokens (numbers, operators, parens)."""
    import re
    tokens = []
    for m in re.finditer(r'\d+\.?\d*|[+\-*/()]|\b[a-zA-Z_]\w*\b', expr):
        tokens.append(m.group())
    return tokens
