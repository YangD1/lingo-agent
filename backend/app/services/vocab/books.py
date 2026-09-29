"""Word books: named slices of `words`, defined here rather than in a table (ADR 0011).

A book is a filter, not a copy: the words carrying an exam tag, or the Oxford 3000.
"""

from dataclasses import dataclass

from sqlalchemy import ColumnElement

from app.db.models import Word


@dataclass(frozen=True, slots=True)
class Book:
    id: str
    name_zh: str
    name_en: str
    # ECDICT exam tag; None for the Oxford 3000, which is a flag instead.
    tag: str | None

    def words(self) -> ColumnElement[bool]:
        """WHERE clause for the book's words (`@>` uses the GIN index on tags)."""
        if self.tag is None:
            return Word.oxford.is_(True)
        return Word.tags.contains([self.tag])


BOOKS: tuple[Book, ...] = (
    Book("oxford3000", "牛津 3000 核心词", "Oxford 3000", None),
    Book("zk", "中考", "Zhongkao (senior high entrance)", "zk"),
    Book("gk", "高考", "Gaokao (college entrance)", "gk"),
    Book("cet4", "大学英语四级", "CET-4", "cet4"),
    Book("cet6", "大学英语六级", "CET-6", "cet6"),
    Book("ky", "考研", "Postgraduate entrance", "ky"),
    Book("ielts", "雅思", "IELTS", "ielts"),
    Book("toefl", "托福", "TOEFL", "toefl"),
    Book("gre", "GRE", "GRE", "gre"),
)
_BY_ID = {book.id: book for book in BOOKS}


def get_book(book_id: str) -> Book | None:
    return _BY_ID.get(book_id)
