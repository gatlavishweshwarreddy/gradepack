import copy


def merge(base, override):
    """
    Deep-merge override into base without mutating base.
    """
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = merge(result[k], v)
        else:
            result[k] = v
    return result
