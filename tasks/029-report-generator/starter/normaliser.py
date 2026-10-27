def normalise(records):
    """Convert amount to float; fill missing region with 'unknown'."""
    result = []
    for r in records:
        result.append({
            "product": r.get("product", ""),
            "region":  r.get("region", "unknown"),
            "amount":  float(r.get("amount", 0)),
        })
    return result
