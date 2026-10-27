def coerce(value, type_name):
    """
    Convert string value to type_name ('int', 'float', 'str').
    Raises ValueError for non-numeric values when type is int or float.

    BUG: coerces int directly via int(value), so '1.0' raises ValueError
    instead of succeeding (should convert via float first then truncate).
    """
    if type_name == "int":
        return int(value)
    elif type_name == "float":
        return float(value)
    else:
        return str(value)
