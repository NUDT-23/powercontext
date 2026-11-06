"""BookVault: a small library catalog used as the competition demo project."""

from .models import Book
from .data import BOOKS
from .search import search_books

__all__ = ["Book", "BOOKS", "search_books"]
