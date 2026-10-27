from schema import validate_schema
from coerce import coerce


def import_csv(rows, schema):
    """
    Convert list-of-dicts rows using schema (col -> type name).
    Returns list of dicts with values coerced to the schema types.
    Raises ValueError for invalid values.
    """
    validate_schema(schema)
    result = []
    for row in rows:
        converted = {}
        for col, type_name in schema.items():
            raw = row.get(col, "")
            converted[col] = coerce(raw, type_name)
        result.append(converted)
    return result
