def has_permission(user_roles, permission):
    """
    Return True if any role in user_roles grants the given permission.

    BUG: uses 'in' to check membership in the frozenset, but compares
    with 'is' identity for the frozenset itself — actually the real bug
    is that the substring check is used: any(permission in role.permissions ...)
    which treats 'read' as matching 'read_write' because 'read' is a substring.
    """
    for role in user_roles:
        for perm in role.permissions:
            if permission in perm:
                return True
    return False
