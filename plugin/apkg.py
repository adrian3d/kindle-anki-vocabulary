import csv
import hashlib
import html
import itertools
import json
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from dataclasses import dataclass, field

# Un nouveau type de note plutôt qu'un champ ajouté à l'ancien : modifier ses champs forcerait une
# synchronisation complète avec AnkiWeb.
MODEL_ID = 1763596800003
MODEL_NAME = 'Kindle vocabulary (audio)'
FIELDS = ('Word', 'Translation', 'Sentence', 'Book', 'Note', 'Reverse', 'Audio')
CSV_FIELDS = 5
FIELD_SEPARATOR = '\x1f'

TTS_LOCALES = {
    'en': 'en_US', 'fr': 'fr_FR', 'de': 'de_DE', 'es': 'es_ES', 'it': 'it_IT', 'pt': 'pt_PT', 'nl': 'nl_NL',
    'sv': 'sv_SE', 'da': 'da_DK', 'nb': 'nb_NO', 'pl': 'pl_PL', 'cs': 'cs_CZ', 'ru': 'ru_RU', 'uk': 'uk_UA',
    'ja': 'ja_JP', 'zh': 'zh_CN', 'ko': 'ko_KR', 'tr': 'tr_TR', 'el': 'el_GR', 'fi': 'fi_FI', 'hu': 'hu_HU',
    'ro': 'ro_RO', 'ca': 'ca_ES',
}


def tts_locale(lang):
    return TTS_LOCALES.get(lang, lang)


CSS = '''.card { font-family: sans-serif; font-size: 22px; text-align: center; color: #222; background: #fdfdfd; }
.nightMode.card, .night_mode.card { color: #eee; background: #2b2b2b; }
.word { font-size: 30px; font-weight: bold; }
.passage { font-size: 21px; font-weight: normal; font-style: italic; text-align: left; }
.sentence { margin-top: 18px; font-style: italic; font-size: 19px; }
.note { margin-top: 18px; font-size: 16px; text-align: left; border-left: 3px solid #5b9bd5; padding-left: 10px; }
.book { margin-top: 18px; color: #888; font-size: 14px; }
'''

DETAILS = '''{{#Sentence}}<div class="sentence">{{Sentence}}</div>{{/Sentence}}
{{#Note}}<div class="note">{{Note}}</div>{{/Note}}
{{#Book}}<div class="book">{{Book}}</div>{{/Book}}'''

TEMPLATES = (
    {
        'name': 'Word → Translation',
        'qfmt': '<div class="word">{{Word}}</div>{{Audio}}{{#Sentence}}<div class="sentence">{{Sentence}}</div>{{/Sentence}}',
        'afmt': '<div class="word">{{Word}}</div><hr id="answer"><div>{{Translation}}</div>' + DETAILS,
    },
    {
        'name': 'Translation → Word',
        'qfmt': '{{#Reverse}}<div>{{Translation}}</div>{{/Reverse}}',
        'afmt': '<div>{{Translation}}</div><hr id="answer"><div class="word">{{Word}}</div>{{Audio}}' + DETAILS,
    },
)

# @see https://github.com/kerrickstaley/genanki/blob/main/genanki/apkg_schema.py
SCHEMA = '''
CREATE TABLE col (
    id integer primary key, crt integer not null, mod integer not null, scm integer not null,
    ver integer not null, dty integer not null, usn integer not null, ls integer not null,
    conf text not null, models text not null, decks text not null, dconf text not null, tags text not null
);
CREATE TABLE notes (
    id integer primary key, guid text not null, mid integer not null, mod integer not null,
    usn integer not null, tags text not null, flds text not null, sfld integer not null,
    csum integer not null, flags integer not null, data text not null
);
CREATE TABLE cards (
    id integer primary key, nid integer not null, did integer not null, ord integer not null,
    mod integer not null, usn integer not null, type integer not null, queue integer not null,
    due integer not null, ivl integer not null, factor integer not null, reps integer not null,
    lapses integer not null, left integer not null, odue integer not null, odid integer not null,
    flags integer not null, data text not null
);
CREATE TABLE revlog (
    id integer primary key, cid integer not null, usn integer not null, ease integer not null,
    ivl integer not null, lastIvl integer not null, factor integer not null, time integer not null,
    type integer not null
);
CREATE TABLE graves (usn integer not null, oid integer not null, type integer not null);
CREATE INDEX ix_notes_usn on notes (usn);
CREATE INDEX ix_cards_usn on cards (usn);
CREATE INDEX ix_revlog_usn on revlog (usn);
CREATE INDEX ix_cards_nid on cards (nid);
CREATE INDEX ix_cards_sched on cards (did, queue, due);
CREATE INDEX ix_revlog_cid on revlog (cid);
CREATE INDEX ix_notes_csum on notes (csum);
'''

CONF = {
    'activeDecks': [1], 'addToCur': True, 'collapseTime': 1200, 'curDeck': 1, 'curModel': str(MODEL_ID),
    'dueCounts': True, 'estTimes': True, 'newBury': True, 'newSpread': 0, 'nextPos': 1,
    'sortBackwards': False, 'sortType': 'noteFld', 'timeLim': 0,
}

DECK_CONF = {
    '1': {
        'autoplay': True, 'id': 1, 'maxTaken': 60, 'mod': 0, 'name': 'Default', 'replayq': True, 'timer': 0, 'usn': 0,
        'lapse': {'delays': [10], 'leechAction': 0, 'leechFails': 8, 'minInt': 1, 'mult': 0},
        'new': {'bury': True, 'delays': [1, 10], 'initialFactor': 2500, 'ints': [1, 4, 7], 'order': 1,
                'perDay': 20, 'separate': True},
        'rev': {'bury': True, 'ease4': 1.3, 'fuzz': 0.05, 'ivlFct': 1, 'maxIvl': 36500, 'minSpace': 1, 'perDay': 100},
    }
}

BASE91 = (
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    '!#$%&()*+,-./:;<=>?@[]^_`{|}~'
)


@dataclass(frozen=True)
class Note:
    key: str
    word: str
    translation: str
    sentence: str = ''
    highlight: str = ''
    book: str = ''
    tags: tuple = field(default_factory=tuple)
    note: str = ''
    passage: bool = False
    lang: str = ''
    audio: str = ''


def write_apkg(path, deck_name, notes, reverse=True, timestamp=None, media_dir=None):
    timestamp = time.time() if timestamp is None else timestamp
    media = sorted({note.audio for note in notes if note.audio and media_dir})
    handle, db_path = tempfile.mkstemp(suffix='.anki2')
    os.close(handle)
    try:
        with closing(sqlite3.connect(db_path)) as conn, conn:
            _write_collection(conn, deck_name, notes, reverse, timestamp)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as package:
            package.write(db_path, 'collection.anki2')
            for index, filename in enumerate(media):
                package.write(os.path.join(media_dir, filename), str(index))
            package.writestr('media', json.dumps({str(index): filename for index, filename in enumerate(media)}))
    finally:
        os.remove(db_path)


def audio_field(note):
    if note.passage:
        return ''
    if note.audio:
        return f'[sound:{note.audio}]'
    if note.lang:
        # Lu par la voix de synthèse de l'appareil quand Wiktionary n'a pas d'enregistrement.
        return f'[anki:tts lang={tts_locale(note.lang)}]{html.escape(note.word, quote=False)}[/anki:tts]'
    return ''


def write_csv(path, deck_name, notes):
    with open(path, 'w', encoding='utf-8', newline='') as file:
        # @see https://docs.ankiweb.net/importing/text-files.html#file-headers
        file.write('#separator:Comma\n#html:true\n')
        file.write(f'#deck:{deck_name}\n')
        # Pas d'en-tête #columns : sans noms, Anki associe les colonnes aux champs par position
        # (mot → recto, traduction → verso), alors qu'avec des noms inconnus il laisse le verso vide.
        file.write(f'#tags column:{CSV_FIELDS + 1}\n#guid column:{CSV_FIELDS + 2}\n')
        writer = csv.writer(file, lineterminator='\n')
        for note in notes:
            writer.writerow([*_fields(note), ' '.join(tag for tag in note.tags if tag), _guid(note.key)])


def _fields(note):
    word = html.escape(note.word, quote=False)
    if note.passage:
        word = '<div class="passage">' + word.replace('\n', '<br>') + '</div>'
    return (
        word,
        html.escape(note.translation, quote=False),
        highlight_sentence(note.sentence, note.highlight),
        html.escape(note.book, quote=False),
        html.escape(note.note, quote=False),
    )


def highlight_sentence(sentence, word):
    escaped = html.escape(sentence.strip(), quote=False)
    if not word:
        return escaped
    pattern = re.compile(r'(?<!\w)' + re.escape(html.escape(word, quote=False)) + r'(?!\w)', re.IGNORECASE)
    return pattern.sub(lambda match: f'<b>{match.group(0)}</b>', escaped, count=1)


def make_tag(text):
    return re.sub(r'[^\w-]+', '-', text.strip().lower()).strip('-')[:60]


def _write_collection(conn, deck_name, notes, reverse, timestamp):
    seconds, deck_id = int(timestamp), _deck_id(deck_name)
    conn.executescript(SCHEMA)
    conn.execute(
        'INSERT INTO col VALUES (null, ?, ?, ?, 11, 0, 0, 0, ?, ?, ?, ?, ?)',
        (
            seconds, seconds * 1000, seconds * 1000,
            json.dumps(CONF),
            json.dumps({str(MODEL_ID): _model(deck_id, seconds)}),
            json.dumps({'1': _deck(1, 'Default', seconds), str(deck_id): _deck(deck_id, deck_name, seconds)}),
            json.dumps(DECK_CONF),
            '{}',
        ),
    )

    ids = itertools.count(int(timestamp * 1000))
    for position, note in enumerate(notes):
        note_id = next(ids)
        fields = (*_fields(note), '1' if reverse else '', audio_field(note))
        conn.execute(
            'INSERT INTO notes VALUES (?, ?, ?, ?, -1, ?, ?, ?, ?, 0, \'\')',
            (
                note_id, _guid(note.key), MODEL_ID, seconds,
                ' ' + ' '.join(tag for tag in note.tags if tag) + ' ',
                FIELD_SEPARATOR.join(fields), note.word, _checksum(note.word),
            ),
        )
        for ordinal in range(2 if reverse else 1):
            conn.execute(
                'INSERT INTO cards VALUES (?, ?, ?, ?, ?, -1, 0, 0, ?, 0, 0, 0, 0, 0, 0, 0, 0, \'\')',
                (next(ids), note_id, deck_id, ordinal, seconds, position),
            )


def _model(deck_id, seconds):
    return {
        'css': CSS, 'did': deck_id, 'id': str(MODEL_ID), 'name': MODEL_NAME, 'mod': seconds, 'usn': -1,
        'sortf': 0, 'type': 0, 'tags': [], 'vers': [], 'latexsvg': False,
        'latexPre': '\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n\\usepackage{amssymb,amsmath}\n'
                    '\\pagestyle{empty}\n\\setlength{\\parindent}{0in}\n\\begin{document}\n',
        'latexPost': '\\end{document}',
        'req': [[0, 'any', [0]], [1, 'any', [5]]],
        'flds': [
            {'name': name, 'ord': index, 'font': 'Liberation Sans', 'media': [], 'rtl': False, 'size': 20, 'sticky': False}
            for index, name in enumerate(FIELDS)
        ],
        'tmpls': [
            {**template, 'ord': index, 'bafmt': '', 'bqfmt': '', 'bfont': '', 'bsize': 0, 'did': None}
            for index, template in enumerate(TEMPLATES)
        ],
    }


def _deck(deck_id, name, seconds):
    return {
        'id': deck_id, 'name': name, 'mod': seconds, 'usn': -1, 'collapsed': False, 'conf': 1, 'desc': '', 'dyn': 0,
        'extendNew': 10, 'extendRev': 50,
        'lrnToday': [0, 0], 'newToday': [0, 0], 'revToday': [0, 0], 'timeToday': [0, 0],
    }


def _deck_id(deck_name):
    return 1 << 40 | int(hashlib.sha256(deck_name.encode('utf-8')).hexdigest()[:10], 16)


def _checksum(text):
    return int(hashlib.sha1(text.encode('utf-8')).hexdigest()[:8], 16)


def _guid(key):
    number = int.from_bytes(hashlib.sha256(f'kindle-vocab__{key}'.encode('utf-8')).digest()[:8], 'big')
    characters = []
    while number > 0:
        number, remainder = divmod(number, len(BASE91))
        characters.append(BASE91[remainder])
    return ''.join(reversed(characters))
