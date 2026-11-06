"""Target tests for R2-R5. They must fail before the change and pass after it."""

from bookvault.data import BOOKS
from bookvault.search import search_books


def ids(books):
    return [book.id for book in books]


def test_filter_by_single_tag():
    """R2: a single tag filters the catalog."""
    assert ids(search_books(BOOKS, tags=["programming"])) == [2, 1, 3]


def test_multiple_tags_use_and_semantics():
    """R2: multiple tags use AND semantics."""
    assert ids(search_books(BOOKS, tags=["programming", "design"])) == [3]


def test_blank_tags_are_ignored():
    """R3: blank and whitespace-only tags are ignored."""
    assert ids(search_books(BOOKS, tags=["", "   ", "programming"])) == [2, 1, 3]


def test_tag_matching_is_case_insensitive():
    """R4: tag matching is case-insensitive."""
    assert ids(search_books(BOOKS, tags=["PROGRAMMING"])) == [2, 1, 3]


def test_unknown_tag_returns_empty():
    """R2: an unknown tag matches no books."""
    assert search_books(BOOKS, tags=["nonexistent"]) == []


def test_limit_out_of_range_raises():
    """R5: limit outside 1..100 raises ValueError."""
    for bad in (0, -1, 101):
        try:
            search_books(BOOKS, limit=bad)
        except ValueError:
            continue
        raise AssertionError(f"limit={bad} should raise ValueError")


def test_limit_boundary_values_are_accepted():
    """R5: limit 1 and 100 are accepted."""
    assert len(search_books(BOOKS, limit=1)) == 1
    assert len(search_books(BOOKS, limit=100)) == len(BOOKS)
