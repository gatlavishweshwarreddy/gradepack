def coerce(value, type_name):
    """
    Convert string value to type_name ('int', 'float', 'str').
    Handles float-formatted integers like '1.0' for int type.
    Raises ValueError for non-numeric values.
    """
    if type_name == "int":
        return int(float(value))
    elif type_name == "float":
        return float(value)
    else:
        return str(value)
