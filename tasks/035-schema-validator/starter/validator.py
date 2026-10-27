from schema import Schema


def validate(data, schema_obj):
    """
    Validate data dict against schema_obj.
    Returns list of error strings (empty = valid).
    """
    expanded = schema_obj.expand()
    errors = []
    required = expanded.get("required", [])
    properties = expanded.get("properties", {})
    for field in required:
        if field not in data:
            errors.append(f"missing required field: {field!r}")
    for field, value in data.items():
        if field in properties:
            expected_type = properties[field].get("type")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"{field!r}: expected string, got {type(value).__name__}")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"{field!r}: expected integer, got {type(value).__name__}")
    return errors
