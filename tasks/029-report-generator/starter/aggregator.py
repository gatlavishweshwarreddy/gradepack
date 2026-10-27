def group_by(records, key):
    """Group records by field `key`. Returns dict: key_value -> list of records."""
    groups = {}
    for r in records:
        groups.setdefault(r[key], []).append(r)
    return groups


def sum_field(group, field):
    """Sum a numeric field across records in a group."""
    return sum(r[field] for r in group)
