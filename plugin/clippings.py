import re
from dataclasses import dataclass, field
from datetime import date, datetime

try:
    from calibre_plugins.kindle_vocab_anki.i18n import _
except ImportError:
    # Hors de calibre, dans les tests, les modules du plugin s'importent sans le préfixe calibre_plugins.
    from i18n import _

ENTRY_SEPARATOR = '=========='
TIME = r'(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})'
DATE_PATTERNS = (
    re.compile(rf'(?P<day>\d{{1,2}}) (?P<month>[A-Za-z]+) (?P<year>\d{{4}}) {TIME}'),
    re.compile(rf'(?P<month>[A-Za-z]+) (?P<day>\d{{1,2}}), (?P<year>\d{{4}}) {TIME} (?P<meridiem>[AaPp][Mm])'),
)
MONTHS = {
    name: number for number, name in enumerate(
        ('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
         'november', 'december'), start=1)
}


@dataclass
class Passage:
    book: str
    page: str | None
    start: int
    end: int
    date: datetime
    text: str | None
    notes: list = field(default_factory=list)

    @property
    def reference(self):
        parts = []
        if self.page:
            parts.append(f'p. {self.page}')
        if self.start:
            span = str(self.start) if self.start == self.end else f'{self.start}-{self.end}'
            parts.append(_('emp. {location}').format(location=span))
        parts.append(self.date.strftime('%d/%m/%Y'))
        return ' · '.join(parts)


def parse(content):
    highlights, notes = {}, {}
    for block in content.split(ENTRY_SEPARATOR):
        entry = _parse_entry(block)
        if entry:
            kind, passage = entry
            (highlights if kind == 'highlight' else notes).setdefault(passage.book, []).append(passage)

    passages = []
    for book in dict.fromkeys([*highlights, *notes]):
        passages.extend(_attach_notes(highlights.get(book, []), notes.get(book, [])))
    return passages


def list_books(passages):
    latest, counts = {}, {}
    for passage in passages:
        counts[passage.book] = counts.get(passage.book, 0) + 1
        latest[passage.book] = max(latest.get(passage.book, passage.date), passage.date)
    return [(book, counts[book]) for book in sorted(counts, key=latest.get, reverse=True)]


def filter_passages(passages, book=None, start: date | None = None, end: date | None = None):
    return [
        passage for passage in passages
        if (book is None or passage.book == book)
        and (start is None or passage.date.date() >= start)
        and (end is None or passage.date.date() <= end)
    ]


def to_markdown(passages):
    lines = []
    for book in dict.fromkeys(passage.book for passage in passages):
        lines += [f'# {book}', '']
        for passage in (p for p in passages if p.book == book):
            if passage.text is None:
                lines += [_('**Note** ({reference}) : {note}').format(reference=passage.reference, note=note) + '\n'
                          for note in passage.notes]
                continue
            lines += ['> ' + passage.text.replace('\n', '\n> '), '>', f'> — {passage.reference}', '']
            lines += [_('**Note** : {note}').format(note=note) + '\n' for note in passage.notes]
    return '\n'.join(lines)


def _parse_entry(block):
    lines = [line.strip('﻿\r ') for line in block.strip('\r\n').split('\n')]
    if len(lines) < 2 or not lines[0] or not lines[1].startswith('- Your '):
        return None

    meta = lines[1][len('- Your '):]
    kind = meta.split(' ', 1)[0].lower()
    text = '\n'.join(lines[2:]).strip()
    if kind not in ('highlight', 'note') or not text:
        return None

    raw_date = next((part[len('Added on '):] for part in meta.split(' | ') if part.startswith('Added on ')), None)
    added = _parse_date(raw_date)
    if added is None:
        return None

    start, end = _parse_location(_value_after(meta.lower(), 'location '))
    return kind, Passage(lines[0], _value_after(meta.lower(), 'page '), start, end, added, text)


def _parse_date(raw_date):
    # strptime dépend de la locale, que calibre règle sur la langue de l'interface.
    for pattern in DATE_PATTERNS:
        match = pattern.search(raw_date or '')
        if not match:
            continue
        parts = match.groupdict()
        month = MONTHS.get(parts['month'].lower())
        if month is None:
            continue
        hour = int(parts['hour'])
        if parts.get('meridiem'):
            hour = hour % 12 + (12 if parts['meridiem'].upper() == 'PM' else 0)
        try:
            return datetime(int(parts['year']), month, int(parts['day']), hour, int(parts['minute']), int(parts['second']))
        except ValueError:
            continue
    return None


def _value_after(meta, key):
    index = meta.find(key)
    if index < 0:
        return None
    return meta[index + len(key):].split(' ', 1)[0] or None


def _parse_location(location):
    try:
        bounds = [int(bound) for bound in (location or '').split('-')]
    except ValueError:
        return 0, 0
    return bounds[0], bounds[-1]


def _attach_notes(highlights, notes):
    passages = []
    for highlight in highlights:
        # La Kindle réécrit une entrée identique quand on retouche un surlignage.
        if all(passage.text != highlight.text for passage in passages):
            passages.append(highlight)

    orphans = []
    for note in notes:
        covering = [p for p in passages if p.start <= note.start <= p.end]
        target = next((p for p in covering if p.date == note.date), covering[0] if covering else None)
        if target:
            target.notes.append(note.text)
        else:
            orphans.append(Passage(note.book, note.page, note.start, note.end, note.date, None, [note.text]))

    return sorted(passages + orphans, key=lambda passage: (passage.start, passage.date))
