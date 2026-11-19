from datetime import date

import clippings

SAMPLE = (
    '﻿Mamu (Alces)\r\n'
    '- Your Note on page 72 | location 1096 | Added on Monday, 12 December 2022 08:50:25\r\n\r\nTrop poli\r\n==========\r\n'
    '﻿Mamu (Alces)\r\n'
    '- Your Highlight on page 72 | location 1096-1096 | Added on Monday, 12 December 2022 08:50:25\r\n\r\n'
    'Puis-je savoir ce que vous regardez ?\r\n==========\r\n'
    '﻿Dune (Frank Herbert)\r\n'
    '- Your Highlight at location 2787-2788 | Added on Wednesday, 31 December 2025 10:31:20\r\n\r\nLa peur tue l\'esprit.\r\n==========\r\n'
    '﻿Dune (Frank Herbert)\r\n'
    '- Your Highlight at location 2787-2788 | Added on Wednesday, 31 December 2025 10:31:24\r\n\r\nLa peur tue l\'esprit.\r\n==========\r\n'
    '﻿Dune (Frank Herbert)\r\n'
    '- Your Bookmark at location 3000 | Added on Wednesday, 31 December 2025 11:00:00\r\n\r\n\r\n==========\r\n'
    '﻿Dune (Frank Herbert)\r\n'
    '- Your Note at location 10 | Added on Thursday, 1 January 2026 09:00:00\r\n\r\nNote isolée\r\n==========\r\n'
)


def test_it_attaches_notes_drops_duplicates_and_bookmarks():
    passages = clippings.parse(SAMPLE)

    assert [(p.book, p.text, p.notes) for p in passages] == [
        ('Mamu (Alces)', 'Puis-je savoir ce que vous regardez ?', ['Trop poli']),
        ('Dune (Frank Herbert)', None, ['Note isolée']),
        ('Dune (Frank Herbert)', 'La peur tue l\'esprit.', []),
    ]
    assert passages[0].reference == 'p. 72 · emp. 1096 · 12/12/2022'
    assert passages[2].reference == 'emp. 2787-2788 · 31/12/2025'


def test_it_lists_books_by_most_recent_activity_and_filters():
    passages = clippings.parse(SAMPLE)

    assert clippings.list_books(passages) == [('Dune (Frank Herbert)', 2), ('Mamu (Alces)', 1)]
    assert len(clippings.filter_passages(passages, book='Dune (Frank Herbert)')) == 2
    assert len(clippings.filter_passages(passages, start=date(2025, 12, 31), end=date(2025, 12, 31))) == 1
    assert clippings.filter_passages(passages, book='Mamu (Alces)', start=date(2023, 1, 1)) == []


def test_it_reads_us_formatted_dates():
    content = 'Livre\r\n- Your Highlight on Location 12-14 | Added on Monday, December 12, 2022 8:44:07 AM\r\n\r\nTexte\r\n==========\r\n'

    passage = clippings.parse(content)[0]

    assert (passage.date.date(), passage.start, passage.end) == (date(2022, 12, 12), 12, 14)


def test_it_renders_markdown_grouped_by_book():
    markdown = clippings.to_markdown(clippings.parse(SAMPLE))

    assert markdown == (
        '# Mamu (Alces)\n\n'
        '> Puis-je savoir ce que vous regardez ?\n>\n> — p. 72 · emp. 1096 · 12/12/2022\n\n'
        '**Note** : Trop poli\n\n'
        '# Dune (Frank Herbert)\n\n'
        '**Note** (emp. 10 · 01/01/2026) : Note isolée\n\n'
        '> La peur tue l\'esprit.\n>\n> — emp. 2787-2788 · 31/12/2025\n'
    )
