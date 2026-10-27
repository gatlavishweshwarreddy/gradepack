from parser import parse_and_eval


def evaluate(expr_str, variables=None):
    """Evaluate an arithmetic expression string. variables is an optional dict."""
    return parse_and_eval(expr_str, variables or {})
