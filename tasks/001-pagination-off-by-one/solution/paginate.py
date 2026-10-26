import math


def paginate(items, page, per_page):
    """Return the items on a 1-indexed page."""
    total_pages = math.ceil(len(items) / per_page) if items else 0
    if page < 1 or page > total_pages:
        return []
    start = (page - 1) * per_page
    return items[start:start + per_page]
