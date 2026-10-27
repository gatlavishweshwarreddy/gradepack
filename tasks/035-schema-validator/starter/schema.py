import copy


class Schema:
    def __init__(self):
        self._definitions = {}

    def load(self, definition):
        """Store a schema definition dict."""
        self._definition = definition

    def define(self, name, sub_schema):
        """Register a named sub-schema for $ref resolution."""
        self._definitions[name] = sub_schema

    def expand(self):
        """
        Resolve $ref references.
        BUG: pops 'required' from self._definition on every call,
        so the first call works but the second call finds no 'required'
        field and never validates required fields.
        """
        expanded = copy.deepcopy(self._definition)
        self._resolve(expanded)
        # BUG: removes 'required' from the ORIGINAL definition (not the copy)
        self._definition.pop("required", None)
        return expanded

    def _resolve(self, node):
        if not isinstance(node, dict):
            return
        if "$ref" in node:
            ref_name = node["$ref"]
            if ref_name in self._definitions:
                node.update(self._definitions[ref_name])
                del node["$ref"]
        for v in list(node.values()):
            self._resolve(v)
