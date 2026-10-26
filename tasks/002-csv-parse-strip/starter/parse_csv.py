def parse_csv(text):
    """Parse a CSV string and return a list of dicts."""
    lines = text.strip().splitlines()
    if not lines:
        return []
    headers = lines[0].split(",")
    result = []
    for line in lines[1:]:
        values = line.split(",")
        result.append(dict(zip(headers, values)))
    return result
