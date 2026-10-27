import json


def load_config(path):
    """Load a JSON config file and return a dict."""
    with open(path) as f:
        return json.load(f)
