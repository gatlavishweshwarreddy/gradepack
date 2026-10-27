class Projector:
    def apply(self, events):
        """Fold events into state dict."""
        state = {}
        for e in events:
            if e.type == "set":
                state[e.payload["key"]] = e.payload["value"]
            elif e.type == "delete":
                state.pop(e.payload["key"], None)
            elif e.type == "increment":
                k = e.payload["key"]
                state[k] = state.get(k, 0) + e.payload["by"]
        return state
