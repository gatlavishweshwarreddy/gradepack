VALID_TYPES = {"int", "float", "str"}


def validate_schema(schema):
    """Raise ValueError if any type name is not valid."""
    for col, type_name in schema.items():
        if type_name not in VALID_TYPES:
            raise ValueError(f"Unknown type {type_name!r} for column {col!r}")
