def has_permission(user_roles, permission):
    """Return True if any role in user_roles grants the given permission (exact match)."""
    for role in user_roles:
        if permission in role.permissions:
            return True
    return False
