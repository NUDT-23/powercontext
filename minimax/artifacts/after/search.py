"""Book search entry point.

Specs: specs/search-requirements.md (R1-R6), specs/compatibility.md (C1-C3).
"""

from .models import Book


def search_books(
    books: list[Book],
    query: str = "",
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[Book]:
    """Return books matching ``query`` and ``tags``, sorted by rating then id."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")

    q = (query or "").strip().lower()
    normalized_tags = {
        tag.strip().casefold()
        for tag in (tags or [])
        if tag.strip()
    }

    matched: list[Book] = []
    for book in books:
        haystack = f"{book.title} {book.author}".lower()
        if q and q not in haystack:
            continue

        if normalized_tags:
            book_tags = {
                tag.strip().casefold()
                for tag in book.tags
                if tag.strip()
            }
            if not normalized_tags.issubset(book_tags):
                continue

        matched.append(book)

    matched.sort(key=lambda book: (-book.rating, book.id))
    return matched[:limit]
