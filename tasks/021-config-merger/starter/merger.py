def merge(base, override):
    """
    Deep-merge override into base. Keys only in base are kept.
    Keys only in override are added. When both values are dicts,
    merge recursively; otherwise override wins.

    BUG: for nested dict keys, updates base[k] directly in place
    before assigning to result, which mutates the original base dict.
    """
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            # BUG: updates result[k] (which IS base[k]) in place
            result[k].update(v)
        else:
            result[k] = v
    return result
