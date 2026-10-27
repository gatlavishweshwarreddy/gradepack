from tokenizer import tokenize


def _parse_expr(tokens, pos, variables):
    left, pos = _parse_term(tokens, pos, variables)
    while pos < len(tokens) and tokens[pos] in ('+', '-'):
        op = tokens[pos]
        pos += 1
        right, pos = _parse_term(tokens, pos, variables)
        if op == '+': left = left + right
        else:         left = left - right
    return left, pos


def _parse_term(tokens, pos, variables):
    left, pos = _parse_atom(tokens, pos, variables)
    while pos < len(tokens) and tokens[pos] in ('*', '/'):
        op = tokens[pos]
        pos += 1
        right, pos = _parse_atom(tokens, pos, variables)
        if op == '*': left = left * right
        else:         left = left / right
    return left, pos


def _parse_atom(tokens, pos, variables):
    tok = tokens[pos]
    if tok == '(':
        val, pos = _parse_expr(tokens, pos + 1, variables)
        pos += 1  # skip ')'
        return val, pos
    elif tok in variables:
        return float(variables[tok]), pos + 1
    else:
        return float(tok), pos + 1


def parse_and_eval(expr_str, variables=None):
    if variables is None:
        variables = {}
    tokens = tokenize(expr_str)
    result, _ = _parse_expr(tokens, 0, variables)
    return result
