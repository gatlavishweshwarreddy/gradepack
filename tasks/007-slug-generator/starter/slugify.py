import re


def slugify(text):
    """Convert text to a URL slug."""
    # Replace non-alphanumeric characters with hyphens
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text)
    return slug
