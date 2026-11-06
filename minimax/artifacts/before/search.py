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
    """Return books matching ``query``, sorted by rating then id.

    ``tags`` is part of the public signature so callers can pass filters;
    tag filtering is implemented by the pending change described in R2-R5.
    """
    q = (query or "").strip().lower()
    matched: list[Book] = []
    for book in books:
        haystack = f"{book.title} {book.author}".lower()
        if q and q not in haystack:
            continue
        matched.append(book)
    matched.sort(key=lambda book: (-book.rating, book.id))
    return matched[:limit]
