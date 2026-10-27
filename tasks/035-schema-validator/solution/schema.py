import copy


class Schema:
    def __init__(self):
        self._definitions = {}

    def load(self, definition):
        self._definition = definition

    def define(self, name, sub_schema):
        self._definitions[name] = sub_schema

    def expand(self):
        """Return an expanded copy without mutating the original definition."""
        expanded = copy.deepcopy(self._definition)
        self._resolve(expanded)
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
