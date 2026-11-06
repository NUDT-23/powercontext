from .models import Book

BOOKS: list[Book] = [
    Book(1, "Clean Code", "Robert C. Martin", ("programming", "software"), 2008, 4.7),
    Book(2, "The Pragmatic Programmer", "Andrew Hunt", ("programming", "career"), 1999, 4.8),
    Book(3, "Refactoring", "Martin Fowler", ("programming", "design"), 1999, 4.6),
    Book(4, "Domain-Driven Design", "Eric Evans", ("design", "architecture"), 2003, 4.5),
    Book(5, "Python Cookbook", "David Beazley", ("python", "cookbook"), 2013, 4.4),
]
