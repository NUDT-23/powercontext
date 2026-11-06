"""Regression tests for C1-C3. They must pass before and after the change."""

from bookvault.data import BOOKS
from bookvault.search import search_books


def ids(books):
    return [book.id for book in books]


def test_query_matches_title():
    """C1: query matches title."""
    assert ids(search_books(BOOKS, query="python")) == [5]


def test_query_matches_author_case_insensitive():
    """C1: query matches author case-insensitively."""
    assert ids(search_books(BOOKS, query="MARTIN")) == [1, 3]


def test_empty_query_returns_all():
    """C1: empty query returns all books."""
    assert ids(search_books(BOOKS)) == [2, 1, 3, 4, 5]


def test_results_sorted_by_rating_then_id():
    """C2: rating descending, id ascending."""
    assert ids(search_books(BOOKS, limit=100)) == [2, 1, 3, 4, 5]


def test_limit_truncates_after_sorting():
    """C3: limit truncates after sorting."""
    assert ids(search_books(BOOKS, limit=3)) == [2, 1, 3]


def test_query_and_limit_combined():
    """C1/C3: query and limit combine."""
    assert ids(search_books(BOOKS, query="martin", limit=1)) == [1]
