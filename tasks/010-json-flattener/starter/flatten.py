def flatten(obj, sep="."):
    """Flatten a nested dict to dot-separated keys."""
    result = {}

    def _recurse(current, prefix):
        for key, value in current.items():
            # BUG: always adds sep before key, producing '.key' at top level
            new_key = prefix + sep + key
            if isinstance(value, dict):
                _recurse(value, new_key)
            else:
                result[new_key] = value

    _recurse(obj, "")
    return result
