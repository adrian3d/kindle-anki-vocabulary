from datetime import date

import vocab
from vocab import Filters


def test_it_lists_languages_and_books(vocab_db):
    conn = vocab.open_db(vocab_db)

    assert vocab.list_languages(conn) == [('en', 2), ('fr', 1)]
    assert vocab.list_books(conn) == [('Siege and Storm', 2), ('Vers le Pôle', 1), ('Dune', 1)]
    assert vocab.list_books(conn, 'fr') == [('Vers le Pôle', 1)]


def test_it_groups_lookups_by_word_and_keeps_the_first_one(vocab_db):
    words = vocab.list_words(vocab.open_db(vocab_db))

    stench = next(word for word in words if word.key == 'en:stench')
    assert [word.key for word in words] == ['en:stench', 'fr:banquise', 'en:billowing']
    assert (stench.book, stench.authors, stench.lookups) == ('Dune', 'Frank Herbert', 2)
    assert stench.usage == 'A stench rose from the cave.'
    assert stench.added.date() == date(2025, 12, 31)


def test_it_filters_by_language_book_and_inclusive_dates(vocab_db):
    conn = vocab.open_db(vocab_db)

    def keys(**filters):
        return [word.key for word in vocab.list_words(conn, Filters(**filters))]

    assert keys(lang='fr') == ['fr:banquise']
    assert keys(book='Siege and Storm') == ['en:stench', 'en:billowing']
    assert keys(start=date(2026, 6, 25), end=date(2026, 6, 25)) == ['fr:banquise']
    assert keys(start=date(2026, 11, 18)) == ['en:stench', 'en:billowing']
    assert keys(lang='en', end=date(2025, 12, 31)) == ['en:stench']
    assert keys(lang='fr', book='Dune') == []


def test_it_uses_the_lookup_matching_the_filters_as_context(vocab_db):
    words = vocab.list_words(vocab.open_db(vocab_db), Filters(book='Siege and Storm'))

    assert words[0].usage == 'free of that rotting stench'
    assert words[0].added.date() == date(2026, 11, 18)
