import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


@dataclass(frozen=True)
class Word:
    key: str
    word: str
    stem: str
    lang: str
    usage: str
    book: str
    authors: str
    added: datetime
    lookups: int


@dataclass(frozen=True)
class Filters:
    lang: str | None = None
    book: str | None = None
    start: date | None = None
    end: date | None = None


def open_db(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def list_languages(conn):
    return conn.execute(
        'SELECT lang, COUNT(*) FROM WORDS GROUP BY lang ORDER BY COUNT(*) DESC'
    ).fetchall()


def list_books(conn, lang=None):
    return conn.execute(
        '''SELECT b.title, COUNT(DISTINCT l.word_key)
           FROM LOOKUPS l
           JOIN WORDS w ON w.id = l.word_key
           JOIN BOOK_INFO b ON b.id = l.book_key
           WHERE :lang IS NULL OR w.lang = :lang
           GROUP BY b.title
           ORDER BY MAX(l.timestamp) DESC''',
        {'lang': lang},
    ).fetchall()


def list_words(conn, filters=Filters()):
    rows = conn.execute(
        '''SELECT w.id, w.word, w.stem, w.lang, l.usage, b.title, b.authors, l.timestamp
           FROM LOOKUPS l
           JOIN WORDS w ON w.id = l.word_key
           LEFT JOIN BOOK_INFO b ON b.id = l.book_key
           WHERE (:lang IS NULL OR w.lang = :lang)
             AND (:book IS NULL OR b.title = :book)
             AND (:start IS NULL OR l.timestamp >= :start)
             AND (:end IS NULL OR l.timestamp < :end)
           ORDER BY l.timestamp''',
        {
            'lang': filters.lang,
            'book': filters.book,
            'start': _to_millis(filters.start),
            'end': _to_millis(filters.end + timedelta(days=1)) if filters.end else None,
        },
    ).fetchall()

    first_lookups, counts = {}, {}
    for row in rows:
        first_lookups.setdefault(row[0], row)
        counts[row[0]] = counts.get(row[0], 0) + 1

    return [
        Word(
            key=key,
            word=word,
            stem=stem or word,
            lang=lang,
            usage=(usage or '').strip(),
            book=title or '',
            authors=authors or '',
            added=datetime.fromtimestamp(timestamp / 1000),
            lookups=counts[key],
        )
        for key, word, stem, lang, usage, title, authors, timestamp in first_lookups.values()
    ]


def _to_millis(day):
    if day is None:
        return None
    return int(datetime.combine(day, time.min).timestamp() * 1000)
