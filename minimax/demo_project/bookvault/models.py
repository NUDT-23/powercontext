from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    id: int
    title: str
    author: str
    tags: tuple[str, ...]
    year: int
    rating: float
