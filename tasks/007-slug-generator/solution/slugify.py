import re


def slugify(text):
    """Convert text to a URL slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text)
    slug = slug.lower().strip("-")
    return slug
